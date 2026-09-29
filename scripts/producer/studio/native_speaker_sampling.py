"""What speaker observations sample, and the 8 kHz audio they are measured on (P2-06).

Each approved script names inclusive transcript word ranges. A range is retained source time from its
first word's start to its last word's end. Its source frames are the frames on screen during that time,
from ``floor(start * rate)`` to ``ceil(end * rate)`` exclusive. Inside a range every 6th frame is sampled,
counted from the range's first frame. Every frame is sampled where a picture can change: the last 1.0 s
of the range (exits) and the first 0.5 s after its start (cut joins). The last 0.5 s before its end lies
inside the 1.0 s tail. Frames shared by two clips are sampled once, and dense wins.

The plan is a pure function of the scripts, the transcript words and the source frame rate. So a caller
can refuse an oversized batch before any media is opened (E-S6: more than 6000 frames is refused).

Audio is decoded at the speech-band filter's own rate. ``audit.dialogue_consistency._window_rms`` designs
its 120-3400 Hz band-pass at ``SAMPLE_RATE`` (8000 Hz), so any other rate would silently move the band.
"""
from __future__ import annotations

import math
from fractions import Fraction
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from audit.dialogue_consistency import SAMPLE_RATE
from cut_preview_io import MAX_JSON, run_bounded
from studio.native_budget_schema import SHA256
from studio.native_budget_selection import expand_words
from studio.native_budget_store import require_clip_id
from studio.native_budget_transcript import index_space_problem, read_transcript
from studio.native_selected_frames import SelectedFrames

if TYPE_CHECKING:
    from studio.native_speaker_observations import ObservationRequest

EVERY_NTH_FRAME = 6
DENSE_TAIL_SECONDS = Fraction(1)
DENSE_BOUNDARY_SECONDS = Fraction(1, 2)
MAX_FRAMES = 6000
CAP_MESSAGE = 'Speaker observation sampling exceeds 6000 frames'
SCRIPT_KEYS = frozenset({'clipId', 'scriptIdentity', 'wordRanges'})
AUDIO_TIMEOUT_SECONDS = 900


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
    """Each approved word range as retained source seconds: ``{clipId, wordRange, start, end}``."""
    return [{'clipId': row['clipId'], 'wordRange': [first, last],
             'start': _word(words, first)['start'], 'end': _word(words, last)['end']}
            for row in scripts for first, last in row['wordRanges']]


def retained_words(scripts: list[dict], words: list[dict]) -> list[dict]:
    """Every word any script keeps, once, in transcript order."""
    indexes = sorted({index for row in scripts for index in expand_words(row['wordRanges'])})
    return [_word(words, index) for index in indexes]


def _range_frames(start: float, end: float, rate: Fraction) -> tuple[int, int, dict[int, bool]]:
    """(first frame, end frame exclusive, {frame: dense}) of one retained range."""
    first, stop = math.floor(Fraction(start) * rate), math.ceil(Fraction(end) * rate)
    if math.ceil((stop - first) / EVERY_NTH_FRAME) > MAX_FRAMES:
        raise ValueError(CAP_MESSAGE)
    tail, head = Fraction(end) - DENSE_TAIL_SECONDS, Fraction(start) + DENSE_BOUNDARY_SECONDS
    frames = {}
    for frame in range(first, stop):
        dense = frame / rate >= tail or frame / rate < head
        if dense or (frame - first) % EVERY_NTH_FRAME == 0:
            frames[frame] = dense
    return first, stop, frames


def observation_plan(request: ObservationRequest, words: list[dict], rate: Fraction) -> dict:
    """Source frames to sample: sparse inside every retained range, dense at its end and after its start.

    Args:
        request: Its ``scripts`` name the retained word ranges.
        words: The transcript's ``{sourceWord, text, start, end}`` rows (``source_words``).
        rate: The source frame rate in frames per second.

    Returns:
        The record's ``sampling``: the rule's constants, ``ranges`` (each with ``firstFrame`` and
        ``endFrame``) and ``frames`` rows ``{frame, t, dense}`` in frame order.

    Raises:
        ValueError: More than 6000 frames, a malformed script, or a rate that is not a positive Fraction.
    """
    if type(rate) is not Fraction or rate <= 0:
        raise ValueError('Speaker observation sampling needs a positive rational frame rate')
    ranges, chosen = [], {}
    for row in retained_ranges(checked_scripts(request.scripts, len(words)), words):
        first, stop, frames = _range_frames(row['start'], row['end'], rate)
        ranges.append({**row, 'firstFrame': first, 'endFrame': stop})
        for frame, dense in frames.items():
            chosen[frame] = chosen.get(frame, False) or dense
        if len(chosen) > MAX_FRAMES:
            raise ValueError(CAP_MESSAGE)
    return {'everyNthFrame': EVERY_NTH_FRAME, 'denseTailSeconds': float(DENSE_TAIL_SECONDS),
            'denseBoundarySeconds': float(DENSE_BOUNDARY_SECONDS), 'maxFrames': MAX_FRAMES, 'ranges': ranges,
            'frames': [{'frame': frame, 't': round(float(frame / rate), 6), 'dense': chosen[frame]}
                       for frame in sorted(chosen)]}


def source_clock(source: dict) -> Fraction:
    """The source's constant frame rate; refuse what frame indices cannot address exactly.

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


def frame_selection(source: dict, sampling: dict) -> SelectedFrames:
    """The sampled frames as one exact selection over the source's frame clock."""
    rate = source_clock(source)
    total = math.ceil(Fraction(source['duration']) * rate)
    width, height = source['resolution']
    return SelectedFrames(tuple(row['frame'] for row in sampling['frames']), width, height, total)


def decode_audio(source: dict, ffmpeg: str) -> np.ndarray:
    """Decode the source's first audio stream once, at 8000 Hz, in its own channel count (1 or 2).

    Args:
        source: The manifest source row (``path``, ``duration``, ``audio.channels``).
        ffmpeg: The resolved ffmpeg the inspection owner pinned.

    Returns:
        Float64 samples shaped (count, channels).

    Raises:
        ValueError: The source has no audio or more than two channels.
        RuntimeError: The decode failed or returned a partial sample frame.
    """
    audio = source.get('audio') or {}
    channels = audio.get('channels')
    if audio.get('present') is not True or type(channels) is not int or channels not in (1, 2):
        raise ValueError(f'Speaker observations measure mono or stereo audio; the source has {channels!r} channel(s)')
    command = [ffmpeg, '-nostdin', '-v', 'error', '-xerror', '-i', source['path'], '-map', '0:a:0', '-vn',
               '-ac', str(channels), '-ar', str(SAMPLE_RATE), '-f', 'f32le', 'pipe:1']
    maximum = (math.ceil(source['duration']) + 2) * SAMPLE_RATE * channels * 4 + MAX_JSON
    result = run_bounded(command, maximum=maximum, timeout=AUDIO_TIMEOUT_SECONDS)
    if result.returncode or result.stderr.strip() or not result.stdout:
        raise RuntimeError('Speaker observation audio decode failed: ' + result.stderr[-3000:].decode(errors='replace'))
    raw = np.frombuffer(result.stdout, dtype='<f4')
    if raw.size % channels:
        raise RuntimeError('Speaker observation audio decode returned a partial sample frame')
    return raw.reshape(-1, channels).astype(np.float64)
