"""Which Short a native project is: its canvas source and the source seconds it cuts.

A project's identity for budgets is its selection, not its folder, name,
content hash or lineage. Two projects cut from the same source are the same
Short (one is a revision of the other) when their merged cut ranges share at
least half of their combined seconds, or at least 90% of the shorter one (a
trim or an extension). Every revision in the audited IMG_5954 jobs shared 100%;
the most-overlapping distinct Shorts (C 18.4 s and D 43.6 s, 11.8 s in common)
share 23.5% of the union and 64% of the shorter. A revision therefore
stays with its logical clip: it cannot open fresh counters under another clip
of the batch, and a closed batch keeps refusing it until a new batch binds it.
Different Shorts from one recording, the usual case, share few or no seconds
and stay independent. This is arithmetic on declared cut ranges, not a
content comparison.
"""
from __future__ import annotations

import hashlib
import json
import unicodedata
from pathlib import Path

from studio.native_budget_schema import BOUNDS, valid_selection

SAME_SHORT_SHARE = 0.5   # of the union: mostly the same seconds
SUBSET_SHARE = 0.9       # of the shorter selection: a trim or an extension of it


def project_selection(project: Path) -> dict:
    """The canvas source digest and the merged source-second ranges the plan cuts."""
    plan = json.loads((project / 'SHORT-PROJECT.json').read_text())
    canvas = plan['canvas']
    sources = [row['sha256'] for row in plan['assets'] if row.get('file') == canvas['sourceFile']]
    if len(sources) != 1:
        raise ValueError(f'{project} names no single canvas source asset')
    selection = {'source': sources[0], 'ranges': merged([[cut['start'], cut['end']] for cut in canvas['cuts']])}
    if not valid_selection(selection):
        raise ValueError(f'{project} has no valid cut selection on its canvas source')
    return selection


def merged(ranges: list[list[float]]) -> list[list[float]]:
    """Sorted, non-overlapping ranges covering exactly the same seconds."""
    result: list[list[float]] = []
    for start, end in sorted(ranges):
        if result and start <= result[-1][1]:
            result[-1][1] = max(result[-1][1], end)
        else:
            result.append([start, end])
    return result


def shared_share(first: dict, second: dict) -> float:
    """Seconds both selections cut, over the seconds either cuts (0 across sources)."""
    if first['source'] != second['source']:
        return 0.0
    shared = _shared_seconds(first, second)
    return shared / (_seconds(first) + _seconds(second) - shared)


def _shared_seconds(first: dict, second: dict) -> float:
    """Seconds both merged selections cut."""
    return sum(max(0.0, min(a_end, b_end) - max(a_start, b_start))
               for a_start, a_end in first['ranges'] for b_start, b_end in second['ranges'])


def same_short(first: dict, second: dict) -> bool:
    """True when one selection is a revision of the other: mostly the same seconds, or a trim/extension.

    A tightened cut is a subset and an extended one a superset of the original; either
    shares nearly all of the shorter selection even when the union grows or shrinks a lot.
    """
    if first['source'] != second['source']:
        return False
    shared = _shared_seconds(first, second)
    union = _seconds(first) + _seconds(second) - shared
    return shared / union >= SAME_SHORT_SHARE or shared / min(_seconds(first), _seconds(second)) >= SUBSET_SHARE


def _seconds(selection: dict) -> float:
    """Total source seconds of one merged selection."""
    return sum(end - start for start, end in selection['ranges'])




# The createUserTitleCopy contract (src/lib/server/native-hook-template.ts): nonblank, at most 120 UTF-16
# code units (JavaScript length), no C0 control, DEL, NEL or line/paragraph separator.
TITLE_UNITS = 120
TITLE_FORBIDDEN = frozenset([*map(chr, range(0x20)), '\x7f', '\x85', '\u2028', '\u2029'])
CANONICAL_FORM = ('approval-v2: script = sha256 of UTF-8 compact JSON {"sourceSha256","transcriptSha256",'
                  '"wordRanges","wordTexts","ranges"} in that key order, ensure_ascii off, ranges as [float, float] '
                  'seconds in script order; title = sha256 of the exact UTF-8 title; identity = sha256 of compact '
                  'JSON {"title","script"}')


def title_problem(title: object) -> str | None:
    """Why a title breaks the createUserTitleCopy contract; a valid title is stored as its exact bytes.

    A title is always given: the approved title is an operator input, never missing or agent-authored.
    """
    if title is None:
        return 'a title is always given with the approved script; none was supplied'
    if type(title) is not str or all(char.isspace() or char == '\ufeff' for char in title):
        return 'a title is nonblank text (or none)'
    try:
        units = len(title.encode('utf-16-le')) // 2
        title.encode('utf-8')
    except UnicodeEncodeError:
        return 'a title is valid Unicode text'
    if units > TITLE_UNITS or TITLE_FORBIDDEN.intersection(title):
        return f'a title is single-line copy of at most {TITLE_UNITS} characters (UTF-16 units), with no control or line-separator characters'
    return None


def compare_titles(approved: str | None, observed: str | None) -> str:
    """'exact', 'normalization-only' (NFC and collapsed/trimmed whitespace only; not material) or 'different'."""
    if approved == observed:
        return 'exact'
    if approved is None or observed is None:
        return 'different'
    fold = [' '.join(unicodedata.normalize('NFC', text).split()) for text in (approved, observed)]
    return 'normalization-only' if fold[0] == fold[1] else 'different'


def title_identity(title: str | None) -> str | None:
    """SHA-256 of the exact approved title bytes (UTF-8), or None when no title was approved."""
    return None if title is None else hashlib.sha256(title.encode('utf-8')).hexdigest()


def script_problem(script: dict) -> str | None:
    """Why an approved script is malformed: word ranges ordered, non-overlapping and in range, one text per word,
    one [start, end] second range per word range, and SHA-256 source and transcript identities."""
    word_ranges, texts, ranges = script['wordRanges'], script['wordTexts'], script['ranges']
    count = script['transcriptWords']
    if not all(type(script[key]) is str and len(script[key]) == 64 for key in ('sourceSha256', 'transcriptSha256')) \
            or type(count) is not int or count < 1:
        return 'an approved script names its source and transcript SHA-256 and the transcript word count'
    if type(word_ranges) is not list or not 0 < len(word_ranges) <= BOUNDS['approvalRanges'] \
            or not all(type(row) is list and len(row) == 2 and all(type(item) is int for item in row)
                       and 0 <= row[0] <= row[1] < count for row in word_ranges):
        return f'an approved script names 1-{BOUNDS["approvalRanges"]} in-range inclusive word ranges'
    indices = expand_words(word_ranges)
    if len(set(indices)) != len(indices) or len(indices) > BOUNDS['approvalWords']:
        return f'approved word ranges do not overlap and name at most {BOUNDS["approvalWords"]} words'
    if type(texts) is not list or len(texts) != len(indices) or not all(type(text) is str and 0 < len(text) <= 64
                                                                        for text in texts):
        return 'an approved script gives the text of every kept word'
    return _seconds_problem(script['sourceSha256'], ranges, len(word_ranges))


def _seconds_problem(source: str, ranges: object, expected: int) -> str | None:
    """One non-overlapping [start, end] second range per word range, in script order."""
    selection = {'source': source, 'ranges': ranges}
    if type(ranges) is not list or len(ranges) != expected or not valid_selection(selection):
        return 'an approved script derives one [start, end] second range per word range'
    if _seconds({'source': source, 'ranges': merged([list(row) for row in ranges])}) != _seconds(selection):
        return 'approved second ranges do not overlap'
    return None


def expand_words(word_ranges: list[list[int]]) -> list[int]:
    """Inclusive [first, last] word ranges as the ordered index list."""
    return [word for first, last in word_ranges for word in range(first, last + 1)]


def script_identity(script: dict) -> str:
    """The canonical approved-script identity (``CANONICAL_FORM``)."""
    body = json.dumps({'sourceSha256': script['sourceSha256'], 'transcriptSha256': script['transcriptSha256'],
                       'wordRanges': script['wordRanges'], 'wordTexts': script['wordTexts'],
                       'ranges': [[float(start), float(end)] for start, end in script['ranges']]},
                      ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(body.encode('utf-8')).hexdigest()


def approval_identity(title: str | None, script_sha256: str) -> str:
    """One identity over the exact title and the script identity."""
    body = json.dumps({'title': title, 'script': script_sha256}, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(body.encode('utf-8')).hexdigest()


def compare_approval(approval: dict, observed: dict) -> dict:
    """Exact comparison of an approval row with what a plan or project shows (None: not observed).

    ``observed`` may name ``title``; a full ``script`` (same fields as the approval); and/or
    ``sourceSha256`` with ``ranges`` (a project's cut seconds). Titles report exact, normalization-only
    (not material) or different; scripts compare by identity; seconds by source and equal merged ranges.
    """
    ranges = observed.get('ranges')
    selection = None if ranges is None else observed.get('sourceSha256') == approval['source'] and \
        merged([list(row) for row in ranges]) == merged([list(row) for row in approval['ranges']])
    script = observed.get('script')
    return {'title': compare_titles(approval['title'], observed['title']) if 'title' in observed else None,
            'script': script_identity(script) == approval['script'] if script is not None else None,
            'selection': selection}
