"""The admitted transcript an approval is bound over, checked in the writer's one word index space.

approval-v2 numbers the raw flattened words of the utterance transcript. The native writer numbers
the words it keeps: it drops words whose duration, clipped to the source end, is at most 1e-6 s,
words that start before zero or at/after the source end, and orders words by start. The two
numberings coincide exactly when nothing is dropped or reordered, so binding refuses any other
transcript with a specific error instead of mapping between them. The rule reproduces unit B1's
``role_packet_transcript.index_space_problem``/``utterance_words`` (commit 5798f94) exactly; the
one addition is that NaN/Infinity are refused, since they are not JSON the writer can read.
Binding also checks the file is the approval's transcript (SHA-256 of its exact bytes), that its
word count matches, that every kept word's text is the transcript's text at that index, and that
each second range lies within [0, source duration] and keeps exactly its approved words under the
writer's cut rule (guided-proposal-speech.ts ``occurrence``: a cut keeps every word whose interval
overlaps it, max(start) < min(end), with no epsilon).
"""
from __future__ import annotations

import bisect
import hashlib
import json
import math
from itertools import accumulate
from pathlib import Path

MAX_TRANSCRIPT_BYTES = 256 * 1024 ** 2
MAX_WORDS = 200_000
KEPT_EPSILON = 1e-6


def _constant(name: str) -> float:
    """Refuse NaN and Infinity: the writer's JSON reader cannot parse them."""
    raise ValueError(f'the transcript holds {name}, which is not JSON the writer reads')


def _word_row(raw: object, label: str) -> dict:
    """{text, start, end} of one word as the writer parses it (text in ``word``)."""
    times = [raw.get(key) for key in ('start', 'end')] if isinstance(raw, dict) else [None, None]
    if not isinstance(raw, dict) or not isinstance(raw.get('word'), str) or not all(
            isinstance(value, (int, float)) and not isinstance(value, bool) for value in times) or times[1] < times[0]:
        raise ValueError(f'{label} needs text in `word` and ordered numeric start/end')
    return {'text': raw['word'], 'start': times[0], 'end': times[1]}


def utterance_words(value: object) -> list[dict]:
    """Every word of the utterance array, in file order (the writer's transcript rows)."""
    rows = value.get('transcript') if isinstance(value, dict) else None
    if not isinstance(rows, list) or not all(isinstance(row, dict) and isinstance(row.get('words'), list) for row in rows):
        raise ValueError('the transcript is not an utterance transcript ({transcript: [{words: [...]}]}) the writer reads')
    return [_word_row(word, f'transcript word {row_index}.{word_index}') for row_index, row in enumerate(rows)
            for word_index, word in enumerate(row['words'])]


def index_space_problem(words: list[dict], duration: float) -> str | None:
    """Why the writer's kept-word numbering would differ from the raw flattened numbering, if it would."""
    dropped = [index for index, word in enumerate(words)
               if not 0 <= word['start'] or min(word['end'], duration) <= word['start'] + KEPT_EPSILON]
    reordered = [index for index, (earlier, later) in enumerate(zip(words, words[1:]), start=1)
                 if later['start'] < earlier['start']]
    if not dropped and not reordered:
        return None
    return (f'the writer drops words {dropped[:8]} (zero duration or at/after the source end) and reorders words '
            f'{reordered[:8]}, so its word indices differ from approval-v2\'s')


def read_transcript(path: str | Path, expected_sha256: str) -> list[dict]:
    """The words of the transcript file with exactly this SHA-256 (ValueError otherwise)."""
    file = Path(path)
    if not file.is_file() or file.stat().st_size > MAX_TRANSCRIPT_BYTES:
        raise ValueError(f'the transcript {file} is not a readable file within {MAX_TRANSCRIPT_BYTES} bytes')
    raw = file.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError(f'the transcript {file} is not the approval\'s transcript (SHA-256 differs)')
    return utterance_words(json.loads(raw.decode('utf-8'), parse_constant=_constant))


def transcript_problem(path: str | Path, script: dict, source_seconds: float) -> str | None:
    """Why an approved script cannot be bound over this transcript, or None."""
    from studio.native_budget_selection import expand_words
    if type(source_seconds) not in (int, float) or not math.isfinite(source_seconds) or source_seconds <= 0:
        return 'the source duration is a positive number of seconds'
    try:
        words = read_transcript(path, script['transcriptSha256'])
    except (OSError, UnicodeError, ValueError) as error:
        return str(error)
    problem = 'it has no words' if not words or len(words) > MAX_WORDS else index_space_problem(words, source_seconds)
    if problem:
        return f'the transcript is refused because {problem}'
    if len(words) != script['transcriptWords']:
        return f'the transcript has {len(words)} words, not the approval\'s {script["transcriptWords"]}'
    texts = [words[index]['text'] for index in expand_words(script['wordRanges'])]
    if texts != script['wordTexts']:
        return 'the approval\'s word texts are not the transcript\'s words at those indices'
    return seconds_problem(words, script, source_seconds)


def seconds_problem(words: list[dict], script: dict, source_seconds: float) -> str | None:
    """Each second range lies in the source and keeps exactly its approved words (the writer's cut rule)."""
    starts = [word['start'] for word in words]
    reach = list(accumulate((word['end'] for word in words), max))
    for (first, last), (start, end) in zip(script['wordRanges'], script['ranges']):
        if not 0 <= start < end <= source_seconds:
            return f'second range [{start}, {end}] lies outside the source [0, {source_seconds}]'
        low, high = bisect.bisect_right(reach, start), bisect.bisect_left(starts, end)
        kept = [index for index in range(low, high) if max(words[index]['start'], start) < min(words[index]['end'], end)]
        if kept != list(range(first, last + 1)):
            shown = f'{kept[0]}-{kept[-1]}' if kept else 'none'
            return (f'second range [{start}, {end}] keeps words {shown}, not the approved words {first}-{last} '
                    '(a cut keeps every word it overlaps)')
    return None
