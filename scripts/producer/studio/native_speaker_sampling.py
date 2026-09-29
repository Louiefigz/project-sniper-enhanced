"""What speaker observations sample, on which frame clock (P2-06). Everything here is pure.

Each approved script names inclusive transcript word ranges. A range is retained source time from its
first word's start to its last word's end. Its source frames are the frames on screen during that time,
from ``floor(start * rate)`` to ``ceil(end * rate)`` exclusive. Word times are read as the decimals the
transcript wrote (``repr``), not as binary floats, so no frame outside the range is sampled (REVIEW m1).

Inside a range every 6th frame is sampled, counted from the range's first frame. Every frame is sampled
where a picture can change: the last 1.0 s of the range (exits) and the first 0.5 s after its start (cut
joins). The last 0.5 s before its end lies inside the 1.0 s tail. Frames shared by two clips are sampled
once, and dense wins. More than 6000 frames is refused (E-S6), so a caller can refuse an oversized batch
before any media is opened.

Frame times come from a ``FrameClock``, which is one of two kinds:
- the nominal ``n / rate``, used only by the early E-S6 plan, before any media is read;
- the video packets' own presentation timestamps, on the transcript's clock, used by the worker (X78 DM1).

The packet clock is exact with no threshold. A range is sampled from the frame on screen at its start
through the last frame that starts before its end. A range outside the video's frames is sampled only up
to the nearest frame, and ``clipped_limits`` names it.
"""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import TYPE_CHECKING

from studio.native_budget_schema import SHA256
from studio.native_budget_selection import expand_words
from studio.native_budget_store import require_clip_id
from studio.native_budget_transcript import index_space_problem, read_transcript

if TYPE_CHECKING:
    from studio.native_speaker_observations import ObservationRequest

EVERY_NTH_FRAME = 6
DENSE_TAIL_SECONDS = Fraction(1)
DENSE_BOUNDARY_SECONDS = Fraction(1, 2)
MAX_FRAMES = 6000
CAP_MESSAGE = 'Speaker observation sampling exceeds 6000 frames'
SCRIPT_KEYS = frozenset({'clipId', 'scriptIdentity', 'wordRanges'})


def checked_scripts(scripts: object, word_count: int) -> list[dict]:
    """Approved scripts as exact ``{clipId, scriptIdentity, wordRanges}`` rows, sorted by clip.

    Args:
        scripts: The request's scripts (from the batch approvals, or a file in tests).
        word_count: Words in the admitted transcript; every range must lie inside it.

    Returns:
        New rows sorted by ``clipId``, the order the record keeps.

    Raises:
        ValueError: A row is malformed, a clip repeats, or a range is out of order or out of range.
    """
    if not isinstance(scripts, (list, tuple)) or not scripts:
        raise ValueError('Speaker observations need at least one approved script')
    rows = sorted((_script(row, word_count) for row in scripts), key=lambda row: row['clipId'])
    if len({row['clipId'] for row in rows}) != len(rows):
        raise ValueError('Speaker observation scripts name a clip more than once')
    return rows


def _script(row: object, word_count: int) -> dict:
    """One script row with its exact keys, a script identity and ordered in-range word ranges."""
    if not isinstance(row, dict) or set(row) != SCRIPT_KEYS:
        raise ValueError(f'A speaker observation script has exactly the keys {sorted(SCRIPT_KEYS)}')
    clip = require_clip_id(row['clipId'])
    identity = row['scriptIdentity']
    if type(identity) is not str or SHA256.fullmatch(identity) is None:
        raise ValueError(f'Clip {clip} names no script identity (64 lowercase hex characters)')
    if not _ordered_ranges(row['wordRanges'], word_count):
        raise ValueError(f'Clip {clip} word ranges must be ordered, non-overlapping inclusive [first, last] '
                         f'pairs inside the {word_count}-word transcript')
    return {'clipId': clip, 'scriptIdentity': identity, 'wordRanges': [list(pair) for pair in row['wordRanges']]}


def _ordered_ranges(ranges: object, word_count: int) -> bool:
    """Inclusive integer ``[first, last]`` pairs in transcript order, each after the previous one."""
    if type(ranges) is not list or not ranges or not all(
            type(pair) is list and len(pair) == 2 and all(type(value) is int for value in pair) for pair in ranges):
        return False
    inside = 0 <= ranges[0][0] and ranges[-1][1] < word_count
    return inside and all(first <= last for first, last in ranges) \
        and all(before[1] < after[0] for before, after in zip(ranges, ranges[1:]))


def source_words(path: Path, sha256: str, duration: float) -> list[dict]:
    """The transcript's words as ``{sourceWord, text, start, end}`` rows in the approvals' index space.

    Args:
        path: The admitted utterance transcript.
        sha256: The SHA-256 of its exact bytes.
        duration: The source's duration in seconds; a word's end is clipped to it (the writer's rule).

    Returns:
        One row per raw flattened word; ``sourceWord`` equals the row's index.

    Raises:
        ValueError: The bytes differ, or the writer's numbering would differ from the raw numbering.
    """
    words = read_transcript(path, sha256)
    problem = 'it has no words' if not words else index_space_problem(words, duration)
    if problem:
        raise ValueError(f'Speaker observations refuse the transcript because {problem}')
    return [{'sourceWord': index, 'text': word['text'], 'start': float(word['start']),
             'end': float(min(word['end'], duration))} for index, word in enumerate(words)]


def _word(words: list[dict], index: int) -> dict:
    """The word row at a transcript index, which must carry that index."""
    if not 0 <= index < len(words) or words[index].get('sourceWord') != index:
        raise ValueError(f'Speaker observation words do not hold source word {index} at its index')
    return words[index]


def retained_ranges(scripts: list[dict], words: list[dict]) -> list[dict]:
    """Each approved word range as retained source seconds.

    Args:
        scripts: Checked script rows (``checked_scripts``).
        words: The transcript's ``{sourceWord, text, start, end}`` rows.

    Returns:
        ``{clipId, wordRange, start, end}`` rows, clip by clip in script order.
    """
    return [{'clipId': row['clipId'], 'wordRange': [first, last],
             'start': _word(words, first)['start'], 'end': _word(words, last)['end']}
            for row in scripts for first, last in row['wordRanges']]


def retained_words(scripts: list[dict], words: list[dict]) -> list[dict]:
    """Every word any script keeps, once, in transcript order.

    Args:
        scripts: Checked script rows.
        words: The transcript's word rows.

    Returns:
        The retained word rows, the ones ``stereo_rows`` measures.
    """
    indexes = sorted({index for row in scripts for index in expand_words(row['wordRanges'])})
    return [_word(words, index) for index in indexes]


def _decimal(seconds: float) -> Fraction:
    """The decimal a JSON number was written as (its shortest ``repr``), not its binary float value."""
    return Fraction(repr(float(seconds)))


@dataclass(frozen=True)
class FrameClock:
    """Frame ``n``'s presentation time on the transcript's clock.

    Attributes:
        rate: The nominal frame rate.
        times: The video packets' presentation times, ascending, relative to the audio stream's start. When
            empty, the clock is the nominal ``n / rate``.
    """

    rate: Fraction
    times: tuple[Fraction, ...] = ()

    def time(self, frame: int) -> Fraction:
        """When frame ``frame`` is first shown."""
        return self.times[frame] if self.times else frame / self.rate

    def span(self, start: Fraction, end: Fraction) -> tuple[int, int]:
        """(first frame on screen at ``start``, end frame exclusive: the frames that start before ``end``)."""
        if not self.times:
            return math.floor(start * self.rate), math.ceil(end * self.rate)
        first = max(0, bisect.bisect_right(self.times, start) - 1)
        return first, min(len(self.times), max(first + 1, bisect.bisect_left(self.times, end)))

    def outside(self, start: Fraction, end: Fraction) -> bool:
        """A range that begins before the first frame or ends after the last one is shown (one nominal interval)."""
        return bool(self.times) and (start < self.times[0] or end > self.times[-1] + 1 / self.rate)


def _range_frames(start: float, end: float, clock: FrameClock) -> tuple[int, int, dict[int, bool]]:
    """(first frame, end frame exclusive, {frame: dense}) of one retained range."""
    begin, finish = _decimal(start), _decimal(end)
    first, stop = clock.span(begin, finish)
    if math.ceil((stop - first) / EVERY_NTH_FRAME) > MAX_FRAMES:
        raise ValueError(CAP_MESSAGE)
    tail, head = finish - DENSE_TAIL_SECONDS, begin + DENSE_BOUNDARY_SECONDS
    frames = {}
    for frame in range(first, stop):
        dense = clock.time(frame) >= tail or clock.time(frame) < head
        if dense or (frame - first) % EVERY_NTH_FRAME == 0:
            frames[frame] = dense
    return first, stop, frames


def frame_plan(request: ObservationRequest, words: list[dict], clock: FrameClock) -> dict:
    """Source frames to sample on one frame clock (the rule is in the module docstring).

    Args:
        request: Its ``scripts`` name the retained word ranges.
        words: The transcript's ``{sourceWord, text, start, end}`` rows.
        clock: The nominal clock (early refusal) or the packet clock (the worker).

    Returns:
        ``sampling``: the rule's constants, ``ranges``, ``frames`` rows ``{frame, t, dense}`` in frame order
        (``t`` is the frame's time on the transcript clock), and ``clipped``, the ranges outside the frames.

    Raises:
        ValueError: More than 6000 frames, or a malformed script.
    """
    ranges, chosen, clipped = [], {}, []
    for row in retained_ranges(checked_scripts(request.scripts, len(words)), words):
        first, stop, frames = _range_frames(row['start'], row['end'], clock)
        ranges.append({**row, 'firstFrame': first, 'endFrame': stop})
        if clock.outside(_decimal(row['start']), _decimal(row['end'])):
            clipped.append(row)
        for frame, dense in frames.items():
            chosen[frame] = chosen.get(frame, False) or dense
        if len(chosen) > MAX_FRAMES:
            raise ValueError(CAP_MESSAGE)
    return {'everyNthFrame': EVERY_NTH_FRAME, 'denseTailSeconds': float(DENSE_TAIL_SECONDS),
            'denseBoundarySeconds': float(DENSE_BOUNDARY_SECONDS), 'maxFrames': MAX_FRAMES, 'ranges': ranges,
            'frames': [{'frame': frame, 't': round(float(clock.time(frame)), 6), 'dense': chosen[frame]}
                       for frame in sorted(chosen)], 'clipped': clipped}


def observation_plan(request: ObservationRequest, words: list[dict], rate: Fraction) -> dict:
    """The P2-06 plan on the nominal clock ``n / rate``: the early, media-free E-S6 refusal.

    Args:
        request: Its ``scripts`` name the retained word ranges.
        words: The transcript's ``{sourceWord, text, start, end}`` rows (``source_words``).
        rate: The source frame rate in frames per second.

    Returns:
        ``frame_plan``'s result on the nominal clock.

    Raises:
        ValueError: More than 6000 frames, a malformed script, or a rate that is not a positive Fraction.
    """
    if type(rate) is not Fraction or rate <= 0:
        raise ValueError('Speaker observation sampling needs a positive rational frame rate')
    return frame_plan(request, words, FrameClock(rate))


def clipped_limits(plan: dict, clock: FrameClock) -> list[str]:
    """One limit sentence naming the retained ranges outside the video's frames, when there are any.

    Args:
        plan: ``frame_plan``'s result on the packet clock.
        clock: That packet clock.

    Returns:
        [] or one sentence.
    """
    if not plan['clipped']:
        return []
    shown = '; '.join(f"clip {row['clipId']} words {row['wordRange'][0]}-{row['wordRange'][1]} "
                      f"({row['start']:.3f}-{row['end']:.3f} s)" for row in plan['clipped'])
    return [f'Retained speech outside the video frames ({float(clock.times[0]):.3f}-'
            f'{float(clock.times[-1] + 1 / clock.rate):.3f} s on the transcript clock) is sampled only up to the '
            f'nearest frame: {shown}.']


def source_clock(source: dict) -> Fraction:
    """The source's constant frame rate; refuse what frame indices cannot address exactly.

    Args:
        source: The manifest source row (``frameRate``, ``vfr``, ``rotation``, ``resolution``).

    Returns:
        The frame rate as a Fraction.

    Raises:
        ValueError: A variable frame rate, a rotated picture, or a malformed rate or geometry.
    """
    text, size = source.get('frameRate'), source.get('resolution')
    numerator, _slash, denominator = text.partition('/') if type(text) is str else ('', '', '')
    if not (numerator.isdigit() and denominator.isdigit() and int(numerator) and int(denominator)):
        raise ValueError(f"Speaker observations need the source's rational frameRate 'n/d', not {text!r}")
    rate = Fraction(int(numerator), int(denominator))
    if source.get('vfr') is not False:
        raise ValueError('Speaker observations need a constant-frame-rate source (frame index = time x rate)')
    if source.get('rotation') != 0:
        raise ValueError(f"Speaker observations need an unrotated source; this one is rotated {source.get('rotation')!r}")
    if type(size) is not list or len(size) != 2 or not all(type(value) is int and value > 0 for value in size):
        raise ValueError('Speaker observations need the source resolution [width, height]')
    return rate
