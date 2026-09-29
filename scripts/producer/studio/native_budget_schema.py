"""Closed schema of the production-budget record, checked on every authority read.

A malformed record or altered policy refuses new work. Copied policy constants
record what governed each batch; changing those copies cannot raise its limits.

``SCHEMA_VERSION`` names shape and policy. Unknown versions refuse authority;
closed records may be archived. Pre-release schema 4 is refused by name.

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

SCHEMA_VERSION = 7
PRE_RELEASE = (4,)          # development-only shapes: refused by name, never read (5 adds production.formats)

LIMITS = {
    'repairCycle': 2,        # consolidated correction sets, across all stages
    'author': 3,             # initial candidate + at most 2 focused repair assignments
    'review': 8,             # independent reviewer assignments incl. rechecks
    'planReview': 2,         # initial consolidated round + 1 corrected round
    'previewLaunch': 2,      # moving-preview launches, failed ones included
    'exportAttempt': 2,      # full-program launches: drafts, finals, verify/resume/promote, failures
    'pictureGeneration': 2,  # expensive full-picture renders, distinct from AAC/mux candidates
    'aacCandidate': 6,       # final-delivery AAC/master candidates per clip
    'aacPerAudio': 3,        # ... and per exact audio-input revision (includes the first)
    'transientRetry': 1,     # demonstrably transient failure retries across the whole clip
}
DEADLINES = {
    'preparationSeconds': 1500,   # minute 25: no creative polish admitted afterwards
    'draftDecisionSeconds': 1200,  # minute 20: at-risk clips must choose the review draft
    'deliverySeconds': 2400,      # minute 40: visible complete MP4 handoff
    'handoffReserveSeconds': 120,  # playback check + opening MP4/Studio before minute 40
    'cleanupReserveSeconds': 45,   # owned cleanup inside every granted allocation
}
# Seconds of wall time per second of authored output plus a fixed part (native_budget_forecast).
# Measured one at a time on the integrated engine (dense 45.6 s TEST clip: preview 370 s, draft 317 s,
# promotion 52 s, final reusing the preview's capture 361 s), times 1.21 for the qualified three-way
# pool (each concurrent final ran 1.21x its serial time). Verify/resume keep the earlier receipts.
PROVISIONAL_RATES = {
    'source': 'integrated engine 3b367f6, serial calibration outputs/shorts-sla-qualification/calibration/'
              'cal-3b367f6 x1.21 for 3 heavy slots (pool-qualification run-n3); verify/resume from the '
              'IMG_5954 receipts (outputs/shorts-delay-audit-2026-09-26)',
    'safetyFactor': 1.25,
    'routes': {
        'preview': {'perOutputSecond': 6.1, 'fixedSeconds': 170.0},
        'final': {'perOutputSecond': 8.9, 'fixedSeconds': 30.0},
        'draft': {'perOutputSecond': 8.0, 'fixedSeconds': 20.0},
        'promote': {'perOutputSecond': 1.1, 'fixedSeconds': 15.0},
        'verify': {'perOutputSecond': 5.3, 'fixedSeconds': 15.0},
    },
}
COUNTERS = ('author', 'review', 'planReview', 'repairCycle', 'previewLaunch', 'exportAttempt',
            'pictureGeneration', 'previewPackage', 'aacCandidate', 'transientRetry')
CLIP_STATES = ('active', 'handed-off')
ATTEMPT_STATES = ('running', 'succeeded', 'failed', 'abandoned')
ROUTES = ('preview', 'final', 'draft', 'verify', 'resume', 'promote')
NESTED = ('pictureGeneration', 'aacCandidate', 'previewPackage')
DISPATCH_KINDS = ('author', 'review', 'planReview', 'repairCycle')
BOUNDS = {'clips': 32, 'projects': 64, 'attempts': 64, 'dispatches': 256, 'deliveries': 64,
          'holds': 64, 'claims': 64, 'ranges': 512, 'stages': 64, 'tasks': 256, 'prerequisites': 16,
          'approvals': 4, 'approvalWords': 1024, 'approvalRanges': 128}
# Run-scoped AI work (director, shared planning/review, specialists and every descendant). The run
# declares its host slots and total reservations at start (``production.ai``); these are ceilings.
# Default slots: the audited host exposes four collaboration slots including its coordinator
# (ORCHESTRATION-DESIGN-REVIEW §9); a qualified host record replaces that default when it exists.
AI_POLICY = {
    'slotsCeiling': 16,         # concurrent AI reservations a run may declare
    'reservationsCeiling': 256,  # AI tasks a run may ever charge (one per task, never refunded)
    'runScopedAllowance': 8,    # default run-scoped reservations beside the per-clip dispatch ceilings
    'defaultSlots': 4,
    'depth': 3,                 # director -> task -> child -> grandchild
}
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
RECORD_KEYS = {'schemaVersion', 'batchId', 'status', 'startEpoch', 'clock', 'limits', 'deadlines',
               'rates', 'poolSlots', 'engine', 'holds', 'claims', 'clips', 'closedAtElapsed', 'production'}
BATCH_STATES = ('active', 'draining', 'closed')
CLIP_ROWS = {'projects': 'project', 'attempts': 'attempt', 'dispatches': 'dispatch', 'deliveries': 'delivery',
             'approvals': 'approval'}
CLIP_KEYS = {'addedAfterStart', 'reason', 'state', 'outputSeconds', 'counters', 'aacByAudio', *CLIP_ROWS}


def _row_ok(kind: str, value: object) -> bool:
    """A closed mapping whose every field passes its check."""
    spec = ROWS[kind]
    return type(value) is dict and set(value) == set(spec) and all(check(value[key]) for key, check in spec.items())


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
    except (KeyError, TypeError, AttributeError) as error:
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
    if version not in (5, 6, SCHEMA_VERSION):
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

def policy_digest() -> str:
    """Digest of the limits, deadlines, rates, AI policy and Long policy this schema version governs with."""
    from studio.production.formats import LONG_POLICY as LONG
    policy = json.dumps([LIMITS, DEADLINES, PROVISIONAL_RATES, AI_POLICY, LONG], sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(policy.encode()).hexdigest()
