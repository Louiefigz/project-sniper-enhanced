"""Closed schema of the production-budget record, checked on every authority read.

A malformed record or altered policy refuses new work. Copied policy constants
record what governed each batch; changing those copies cannot raise its limits.

``SCHEMA_VERSION`` names shape and policy. Unknown versions refuse authority;
closed records may be archived. Pre-release schema 4 is refused by name.

Version 8 is the release's one schema step (X7, M-044). Reading 5, 6 or 7 lifts it to 8, adding nothing but the
older schemas' implicit fields (``native_budget_lift``); a schema-5 record written by an A5-forecast build, or a 5-7
record carrying content only version 8 writes, is refused by name first. Release field ledger: a step that lands a
later row adds its validator under this version and ticks ``landed`` (``val``: validator here, writer at the later
step). ``opt`` rows may be absent and are never defaulted; every other row is required, once landed, on records this
engine writes. ``lifted`` is how a lifted 5-7 record meets the row; M-171 checks each rule against a lifted 7
fixture and the ledger against the landed fields.

    field                                                  validator / writer   landed opt  lifted 5-7 record
    clip capacityClock v2 (production.queue_clock_schema)  M-044                yes         v1 clock, read-only
    capacityClock.stall: None, capacity-stalled or         M-044 / M-050        val         v1 clocks have none
      cancelled; <= 64 occupants (else truncated); <= 1 cancel row
    task completed with an unresolved resource             M-042                yes         holds no such row
    production.closure {closedElapsed, unresolvedAtClose}  M-043                yes    opt  absent
    host unresolved-executions.jsonl (its own schema 1)    M-043                yes         not a record field
    task assignmentBinding (refused until validated)       M-080, M-082         no     opt  absent
    declared handle types, hostProcess in DECLARED_KEYS    M-088 / M-099 (O3)   no          none are declared
    declared director host, hostVersion (on its handle)    M-099                no          declared ones only
    attempt admittedForecastSeconds (finite, >= 0)         M-044 / M-125        val    opt  absent
    attempt late, delivery late (only True)                M-044 / M-144        val    opt  absent
    Long output policy v2                                  M-122                no          M-122 states it
    output revision                                        M-162                no          M-162 states it
    production.storage {ceilingBytes, minimumFreeBytes,    M-044 / M-147        val    opt  absent
      basis} (production.production_optional)
    source-store extractionRaster, if held in the record   M-150                no          M-150 states it
    launchError travels in events only and adds no record field (M-042).

Version 7 adds bounded logical section families within existing counted attempts.
Version 6 adds closed section-owner history; lifting schema 5/6 preserves clocks and counters.
Version 5 adds the ``production`` block (task rows, run-scoped AI reservations, host
governance, drain record and start authorization; ``production.task_schema``), the
``draining`` status, and each clip's chained ``approvals`` (approval-v2,
``native_budget_selection.CANONICAL_FORM``). The clock starts at ``start``, where the approvals
are handed over; a later change is a new chained approval, never a clock reset, extension or refund.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable

from studio.native_budget_schema_data import (  # re-exported by name: importers keep importing from here
    AI_POLICY, ATTEMPT_STATES, BATCH_STATES, BOUNDS, CLIP_KEYS, CLIP_ROWS, CLIP_STATES, COUNTERS, DEADLINES,
    DISPATCH_KINDS, LIMITS, NESTED, PRE_RELEASE, PROVISIONAL_RATES, RECORD_KEYS, ROUTES,
)

SCHEMA_VERSION = 8
LIFTED_VERSIONS = (5, 6, 7)   # the versions this engine lifts (X7: the one place that set is written)
SHA256 = re.compile(r'[0-9a-f]{64}')
HEX32 = re.compile(r'[0-9a-f]{32}')
Check = Callable[[object], bool]


def _text(value: object) -> bool:
    """A bounded string."""
    return type(value) is str and len(value) <= 4096


def _number(value: object) -> bool:
    """A finite real number (booleans excluded)."""
    return type(value) in (int, float) and math.isfinite(value)


def _nonnegative(value: object) -> bool:
    """A finite number at or above zero."""
    return _number(value) and value >= 0


def _count(value: object) -> bool:
    """A nonnegative integer."""
    return type(value) is int and value >= 0


def _digest(value: object) -> bool:
    """A lowercase SHA-256 hex digest."""
    return type(value) is str and SHA256.fullmatch(value) is not None


def _attempt_id(value: object) -> bool:
    """A launch attempt id (128-bit lowercase hex)."""
    return type(value) is str and HEX32.fullmatch(value) is not None

def _optional(check: Check) -> Check:
    """None, or a value passing the check."""
    return lambda value: value is None or check(value)


def _member(values: tuple) -> Check:
    """One of a closed set of strings."""
    return lambda value: type(value) is str and value in values


def _range(value: object) -> bool:
    """One [start, end) interval in source seconds."""
    return type(value) is list and len(value) == 2 and all(_nonnegative(item) for item in value) \
        and value[0] < value[1]


def valid_title(value: object) -> bool:
    """An approved title: non-empty exact text of at most 300 characters."""
    return type(value) is str and 0 < len(value.strip()) and len(value) <= 300 and '\0' not in value


def valid_selection(value: object) -> bool:
    """The canvas source digest and its non-empty, bounded cut ranges."""
    return type(value) is dict and set(value) == {'source', 'ranges'} and _digest(value['source']) \
        and type(value['ranges']) is list and 0 < len(value['ranges']) <= BOUNDS['ranges'] \
        and all(_range(item) for item in value['ranges'])


ROWS: dict[str, dict[str, Check]] = {
    'project': {'key': _digest, 'path': _text, 'projectHash': _optional(_digest), 'selection': _optional(valid_selection)},
    'hold': {'startElapsed': _nonnegative, 'endElapsed': _optional(_nonnegative), 'reason': _text},
    'approval': {'title': lambda value: type(value) is str, 'titleSha256': _digest,
                 'source': _digest, 'transcript': _digest, 'transcriptWords': _count,
                 'wordRanges': lambda value: type(value) is list, 'wordTexts': lambda value: type(value) is list,
                 'ranges': lambda value: type(value) is list, 'script': _digest, 'identity': _digest,
                 'wordCount': _count, 'sourceSeconds': _nonnegative, 'elapsed': _nonnegative, 'epoch': _nonnegative,
                 'previous': _optional(_digest),
                 'recordedBy': lambda value: valid_title(value) and len(value) <= 128 and '\n' not in value,
                 'reason': _text},
    'dispatch': {'kind': _member(DISPATCH_KINDS), 'label': _text, 'elapsed': _nonnegative},
    'delivery': {'kind': _member(('final', 'draft')), 'output': _optional(_text), 'sha256': _optional(_digest),
                 'attemptId': _attempt_id, 'elapsed': _nonnegative},
    'supervisor': {'pid': _count, 'pgid': _count, 'started': _text},
    'failure': {'category': _text, 'phase': _optional(_text), 'errorType': _optional(_text), 'signature': _text},
    'stage': {'phase': _optional(_text), 'status': _optional(_text), 'elapsedSeconds': _optional(_number)},
    'engine': {'root': _text, 'identity': _digest, 'files': _count},
    'attempt': {'id': _attempt_id, 'route': _member(ROUTES), 'project': _text, 'output': _text,
                'identity': _digest, 'admittedElapsed': _nonnegative, 'outputSeconds': _number,
                'grantedSeconds': _number, 'supervisor': lambda value: _row_ok('supervisor', value),
                'status': _member(ATTEMPT_STATES), 'resultStatus': _optional(_text),
                'failure': _optional(lambda value: _row_ok('failure', value)),
                'completedElapsed': _optional(_nonnegative),
                'stages': lambda value: _rows_ok('stage', value, BOUNDS['stages']),
                'nested': lambda value: _counts_ok(value, NESTED, subset=True),
                'transientRetryOf': _optional(_attempt_id)},
}
# Fields a row may omit (the ledger's opt rows; never defaulted). Present, each passes its check (P4-06).
OPTIONAL_ROWS: dict[str, dict[str, Check]] = {
    'attempt': {'admittedForecastSeconds': _nonnegative, 'late': lambda value: value is True},
    'delivery': {'late': lambda value: value is True},
}


def _row_ok(kind: str, value: object) -> bool:
    """A closed mapping whose every field passes its check; the kind's optional fields may be absent."""
    spec = {**ROWS[kind], **OPTIONAL_ROWS.get(kind, {})}
    return type(value) is dict and set(ROWS[kind]) <= set(value) <= set(spec) \
        and all(check(value[key]) for key, check in spec.items() if key in value)


def _rows_ok(kind: str, value: object, bound: int) -> bool:
    """A bounded list of closed rows."""
    return type(value) is list and len(value) <= bound and all(_row_ok(kind, row) for row in value)


def _counts_ok(value: object, keys: tuple, subset: bool = False) -> bool:
    """Nonnegative integer counters over exactly (or at most, for subset) these keys."""
    if type(value) is not dict or not (set(value) <= set(keys) if subset else set(value) == set(keys)):
        return False
    return all(_count(item) for item in value.values())


def validate_record(record: object) -> None:
    """Raise ValueError unless the record matches the closed schema and this engine's policy."""
    try:
        problem = _record_problem(record)
    except (KeyError, TypeError, AttributeError, OverflowError) as error:   # OverflowError: a huge integer
        problem = f'unreadable structure ({type(error).__name__})'
    if problem:
        raise ValueError(f'budget record is invalid: {problem}')


def _record_problem(record: object) -> str | None:
    """The first schema or policy violation, or None."""
    from studio.native_budget_clock import ClockAnchor
    version = record.get('schemaVersion') if type(record) is dict else None
    if version in PRE_RELEASE:
        return (f'pre-release schema {version} (a development build that was never released; this engine reads '
                f'schema {SCHEMA_VERSION}); archive it once it is closed or its delivery deadline has passed')
    # The readable set is formed at each call, never frozen at import: a test standing in for the next engine
    # (``SCHEMA_VERSION`` patched to 9) must read this engine's 8 as foreign (test_production_room StagedStarts).
    if version not in (*LIFTED_VERSIONS, SCHEMA_VERSION):
        return (f'written by another engine version (schemaVersion {version!r}, this engine '
                f'{SCHEMA_VERSION}); finish it with that engine, or archive it once it is closed or '
                'its delivery deadline has passed')
    if set(record) != RECORD_KEYS:
        return 'unexpected fields'
    if record['status'] not in BATCH_STATES or not _nonnegative(record['startEpoch']) \
            or (record['status'] == 'closed') != (record['closedAtElapsed'] is not None) \
            or not _optional(_nonnegative)(record['closedAtElapsed']):
        return 'status, start or close time'
    ClockAnchor.from_record(record['clock'])
    if (record['limits'], record['deadlines'], record['rates']) != (LIMITS, DEADLINES, PROVISIONAL_RATES):
        return 'limits, deadlines or rates differ from this engine\'s policy'
    if type(record['poolSlots']) is not int or not 1 <= record['poolSlots'] <= 16:
        return 'pool slots'
    if not _optional(lambda value: _row_ok('engine', value))(record['engine']):
        return 'engine identity'
    claims = record['claims']
    if type(claims) is not list or len(claims) > BOUNDS['claims'] or not all(map(_digest, claims)) \
            or claims != sorted(set(claims)):
        return 'declared sources must be at most 64 sorted unique SHA-256 digests'
    if not _rows_ok('hold', record['holds'], BOUNDS['holds']):
        return 'holds'
    if type(record['clips']) is not dict or not 0 < len(record['clips']) <= BOUNDS['clips']:
        return 'clips'
    from studio.native_budget_section_schema import section_problem
    from studio.native_budget_family_schema import family_problem
    problem = next(filter(None, (_clip_problem(clip) for clip in record['clips'].values())), None) \
        or section_problem(record) or family_problem(record)
    if problem:
        return problem
    from studio.production import formats, task_schema
    return formats.outputs_problem(record) or task_schema.production_problem(record)


def _clip_problem(clip: object) -> str | None:
    """The first violation in one logical clip, or None."""
    if type(clip) is not dict or set(clip) - {'output', 'sectionOwners', 'sectionFamilies', 'capacityClock'} != CLIP_KEYS \
            or clip['state'] not in CLIP_STATES \
            or type(clip['addedAfterStart']) is not bool or not _text(clip['reason']):
        return 'clip fields or state'
    if not _optional(_number)(clip['outputSeconds']) or not _counts_ok(clip['counters'], COUNTERS):
        return 'clip duration or counters'
    audio = clip['aacByAudio']
    if type(audio) is not dict or not all(map(_digest, audio)) or not all(map(_count, audio.values())):
        return 'AAC counters'
    for name, kind in CLIP_ROWS.items():
        if not _rows_ok(kind, clip[name], BOUNDS[name]):
            return f'clip {name}'
    approvals = clip['approvals']
    if any(row['previous'] != (approvals[index - 1]['identity'] if index else None)
           for index, row in enumerate(approvals)):
        return 'approval chain: each approval names its predecessor'
    from studio.production.queue_clock import problem as capacity_problem
    return capacity_problem(clip) or next(filter(None, map(_approval_problem, approvals)), None)


def _approval_problem(row: dict) -> str | None:
    """An approval's stored title, words, seconds and identities must agree (a hand-edited row is refused)."""
    from studio.native_budget_selection import (
        approval_identity, expand_words, script_identity, script_problem, title_identity, title_problem,
    )
    script = approval_script(row)
    problem = title_problem(row['title']) or script_problem(script)
    if problem:
        return f'approval: {problem}'
    derived = (title_identity(row['title']), script_identity(script), len(expand_words(row['wordRanges'])))
    if derived != (row['titleSha256'], row['script'], row['wordCount']) \
            or approval_identity(row['title'], row['script']) != row['identity']:
        return 'approval identities do not match its title, words and seconds'
    return None


def approval_script(row: dict) -> dict:
    """The script fields of an approval row, keyed as the canonical script identity names them."""
    return {'sourceSha256': row['source'], 'transcriptSha256': row['transcript'],
            'transcriptWords': row['transcriptWords'], 'wordRanges': row['wordRanges'],
            'wordTexts': row['wordTexts'], 'ranges': row['ranges']}


def a5_shape(record: dict) -> bool:
    """True when any attempt row carries ``forecast``: a schema-5 record written by an A5-forecast build (P4-06).

    The store asks before lifting a schema-5 record, so it reads raw JSON; any other shape is left to validation.
    """
    clips = record.get('clips')
    rows = [row for clip in (clips.values() if type(clips) is dict else ()) if type(clip) is dict
            for row in (clip.get('attempts') if type(clip.get('attempts')) is list else ())]
    return any(type(row) is dict and 'forecast' in row for row in rows)

def policy_digest() -> str:
    """Digest of the limits, deadlines, rates, AI policy and Long policy this schema version governs with."""
    from studio.production.formats import LONG_POLICY as LONG
    policy = json.dumps([LIMITS, DEADLINES, PROVISIONAL_RATES, AI_POLICY, LONG], sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(policy.encode()).hexdigest()
