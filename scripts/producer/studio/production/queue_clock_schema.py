"""Versioned shape of a Short's capacity clock (P1 Step B1, M-044): v1 is read, v2 is written.

A v1 clock (``short-render-capacity-v1``) is what the P0 engine wrote. It validates exactly as it did, and
``queue_clock`` never advances it. A newly authorized Short gets a v2 clock: the v1 keys plus the director's
activity declaration, the occupancy window, the named stall state, orphaned owners, trail checkpoints and the
hand-off row. Their writers land in later steps (M-045 to M-054); every validator lands here, so the schema
changes once (X7). Nothing is defaulted: every v2 key is present on every v2 clock (``new_clock``).

A v2 owner row also names its pool evidence (``ticket``, ``occupants``, ``waitClass``: ``None``, ``[]`` and
``None`` for a row without any; M-047 supplies it) and its exact owner identity (``supervisor``, ``boot``).
The stall has three states (X19, X35(g)): none, ``capacity-stalled`` and ``cancelled``. Its only recorded
decision is the operator's ``cancel``, so at most one decision row exists. Its ``occupants`` are the sorted
union of every verified waiting row's occupants, cut at ``MAX_STALL_OCCUPANTS`` with ``truncated`` true
(X95, X98); a truncated stall is never credited, and a truncated list is exactly that long. An orphan row is a
v2 owner row plus ``orphanedElapsed``.
"""
from __future__ import annotations

import math

from studio.production.host_contract import SHA256, encoded_length

POLICY_V1 = 'short-render-capacity-v1'
POLICY = 'short-render-capacity-v2'
POLICIES = (POLICY_V1, POLICY)
MAX_WORKERS = 64
MAX_OCCUPANTS = 8           # one owner row's live occupants (B3)
MAX_STALL_OCCUPANTS = 64    # the stall's union over every waiting row (X95: no pool constant bounds it)
MAX_ORPHAN_ROWS = 16
MAX_CHECKPOINTS = 32
WORKER_STATES = ('working', 'waiting', 'unverified')
V1_WORKER_STATES = ('working', 'waiting')
STALL_STATES = (None, 'capacity-stalled', 'cancelled')
WAIT_CLASSES = ('capacity', 'other', None)
V1_KEYS = frozenset({'policy', 'excludedSeconds', 'pendingSeconds', 'observedElapsed', 'uncertainSeconds',
                     'workers', 'taskCredits', 'deliveryCredits'})
V2_KEYS = V1_KEYS | {'directorWorking', 'occupancy', 'stall', 'orphans', 'checkpoint', 'handoff'}
V1_WORKER_KEYS = frozenset({'state', 'resource', 'evidence', 'seenElapsed', 'taskId', 'attemptId'})
V2_WORKER_KEYS = V1_WORKER_KEYS | {'ticket', 'occupants', 'waitClass', 'supervisor', 'boot'}
HANDOFF_NUMBERS = ('elapsed', 'countedSeconds', 'totalSeconds', 'deadlineElapsed')


def new_clock() -> dict:
    """The v2 clock of a newly authorized Short."""
    return {'policy': POLICY, 'excludedSeconds': 0.0, 'pendingSeconds': 0.0, 'observedElapsed': 0.0,
            'uncertainSeconds': 0.0, 'workers': {}, 'taskCredits': {}, 'deliveryCredits': {},
            'directorWorking': True, 'occupancy': {'fingerprint': None, 'sinceElapsed': 0.0},
            'stall': {'state': None, 'sinceElapsed': None, 'occupants': [], 'truncated': False, 'decisions': []},
            'orphans': {'count': 0, 'recent': []},
            'checkpoint': {'excludedSeconds': 0.0, 'elapsed': 0.0, 'count': 0}, 'handoff': None}


def number(value: object) -> bool:
    """Require finite nonnegative seconds."""
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def problem(clip: dict) -> str | None:
    """Validate a clip's clock under its own policy; a clip without one (historical, Long) has none to check."""
    if 'capacityClock' not in clip:
        return None
    clock = clip['capacityClock']
    policy = clock.get('policy') if type(clock) is dict else None
    if policy not in POLICIES or set(clock) != (V1_KEYS if policy == POLICY_V1 else V2_KEYS):
        return 'Short capacity clock shape/policy'
    issue = _accounting_problem(clock)
    if issue or policy == POLICY_V1:
        return issue
    return _v2_problem(clock)


def _accounting_problem(clock: dict) -> str | None:
    """The v1 keys, as the P0 engine validated them (their owner rows by the clock's own policy)."""
    numeric = ('excludedSeconds', 'pendingSeconds', 'observedElapsed', 'uncertainSeconds')
    if any(not number(clock[name]) for name in numeric) \
            or clock['excludedSeconds'] + clock['pendingSeconds'] > clock['observedElapsed'] + 1e-6:
        return 'Short capacity clock totals'
    workers, credits = clock['workers'], clock['taskCredits']
    if type(clock['deliveryCredits']) is not dict or any(not number(value) for value in clock['deliveryCredits'].values()):
        return 'Short delivery clock credits'
    if type(workers) is not dict or len(workers) > MAX_WORKERS or type(credits) is not dict:
        return 'Short capacity clock owners'
    if any(not isinstance(key, str) or not number(value) for key, value in credits.items()):
        return 'Short capacity task credits'
    return next((issue for row in workers.values() if (issue := worker_problem(row, clock['policy']))), None)


def worker_problem(row: object, policy: str) -> str | None:
    """Validate one owner row: v1 rows as the P0 engine wrote them; a v2 row also carries its pool evidence,
    its exact owner identity, and may be ``unverified``."""
    v2 = policy == POLICY
    keys, states = (V2_WORKER_KEYS, WORKER_STATES) if v2 else (V1_WORKER_KEYS, V1_WORKER_STATES)
    if type(row) is not dict or (set(row) if v2 else set(row) - {'supervisor', 'boot'}) != keys \
            or row['state'] not in states or not number(row['seenElapsed']):
        return 'Short capacity worker state'
    if ('supervisor' in row) != ('boot' in row) or 'supervisor' in row and not _owner_identity(row):
        return 'Short capacity worker process identity'
    if any(type(row[key]) is not str or len(row[key]) > 2048 for key in ('resource', 'evidence')):
        return 'Short capacity worker evidence'
    if any(row[key] is not None and (type(row[key]) is not str or len(row[key]) > 128)
           for key in ('taskId', 'attemptId')):
        return 'Short capacity worker identity'
    return _pool_evidence_problem(row) if v2 else None


def _owner_identity(row: dict) -> bool:
    """New workers retain an exact owner identity; historical rows remain readable."""
    owner = row['supervisor']
    return type(row['boot']) is str and bool(row['boot']) and type(owner) is dict \
        and set(owner) == {'pid', 'pgid', 'started'} \
        and all(type(owner[key]) is int and owner[key] > 1 for key in ('pid', 'pgid')) \
        and type(owner['started']) is str and bool(owner['started'].strip())


def _pool_evidence_problem(row: dict) -> str | None:
    """A v2 row's pool ticket, the live occupants it waited behind, and its wait class."""
    ticket = row['ticket']
    if ticket is not None and (type(ticket) is not int or ticket < 0) \
            or not _occupants_ok(row['occupants'], MAX_OCCUPANTS) \
            or row['waitClass'] not in WAIT_CLASSES:
        return 'Short capacity worker pool evidence'
    return None


def _occupants_ok(value: object, bound: int) -> bool:
    """At most ``bound`` pool member names of at most 64 characters."""
    return type(value) is list and len(value) <= bound \
        and all(type(item) is str and len(item) <= 64 for item in value)


def _v2_problem(clock: dict) -> str | None:
    """The v2 fields: director declaration, occupancy window, stall, orphans, checkpoint and hand-off."""
    if type(clock['directorWorking']) is not bool:
        return 'Short capacity clock director activity'
    occupancy = clock['occupancy']
    if type(occupancy) is not dict or set(occupancy) != {'fingerprint', 'sinceElapsed'} \
            or not (occupancy['fingerprint'] is None or _digest(occupancy['fingerprint'])) \
            or not number(occupancy['sinceElapsed']):
        return 'Short capacity clock occupancy'
    return _stall_problem(clock['stall']) or _orphans_problem(clock['orphans']) \
        or _checkpoint_problem(clock['checkpoint']) or _handoff_problem(clock['handoff'])


def _digest(value: object) -> bool:
    """A lowercase SHA-256 hex digest."""
    return type(value) is str and SHA256.fullmatch(value) is not None


def _stall_problem(stall: object) -> str | None:
    """The named stall state, the occupants it stalled behind (cut at 64, and then marked truncated), and at
    most one recorded cancellation."""
    if type(stall) is not dict or set(stall) != {'state', 'sinceElapsed', 'occupants', 'truncated', 'decisions'} \
            or stall['state'] not in STALL_STATES \
            or not (stall['sinceElapsed'] is None or number(stall['sinceElapsed'])) \
            or not _occupants_ok(stall['occupants'], MAX_STALL_OCCUPANTS) or type(stall['truncated']) is not bool \
            or stall['truncated'] and len(stall['occupants']) != MAX_STALL_OCCUPANTS:
        return 'Short capacity clock stall'
    decisions = stall['decisions']
    if type(decisions) is not list or len(decisions) > 1 or not all(map(_decision_ok, decisions)):
        return 'Short capacity clock stall decisions: at most one, the operator\'s recorded cancel'
    return None if _stall_consistent(stall) else 'Short capacity clock stall: its state, time, occupants and ' \
        'decision disagree'


def _stall_consistent(stall: dict) -> bool:
    """X180 m7: ``cancelled`` iff one cancel row; a time iff a state; no state keeps no occupants or truncation
    (cleared together, X102); occupants sorted and distinct (the union ``queue_stall.track`` writes)."""
    state, occupants = stall['state'], stall['occupants']
    if (state == 'cancelled') != (len(stall['decisions']) == 1) or (state is None) != (stall['sinceElapsed'] is None):
        return False
    if state is None and (occupants or stall['truncated']):
        return False
    return occupants == sorted(set(occupants))


def _decision_ok(row: object) -> bool:
    """One recorded operator decision: ``cancel``, its reason (at most 512 encoded bytes) and when."""
    return type(row) is dict and set(row) == {'kind', 'reason', 'elapsed'} and row['kind'] == 'cancel' \
        and type(row['reason']) is str and encoded_length(row['reason']) <= 512 and number(row['elapsed'])


def _orphans_problem(orphans: object) -> str | None:
    """The count of orphaned owners and the most recent ones, each a v2 owner row plus when it was orphaned."""
    if type(orphans) is not dict or set(orphans) != {'count', 'recent'} or type(orphans['count']) is not int \
            or type(orphans['recent']) is not list or len(orphans['recent']) > MAX_ORPHAN_ROWS \
            or orphans['count'] < len(orphans['recent']):
        return 'Short capacity clock orphans'
    if not all(type(row) is dict and number(row.get('orphanedElapsed'))
               and worker_problem({k: v for k, v in row.items() if k != 'orphanedElapsed'}, POLICY) is None
               for row in orphans['recent']):
        return 'Short capacity clock orphan rows'
    return None


def _checkpoint_problem(checkpoint: object) -> str | None:
    """The last trail checkpoint: credited seconds, when, and how many were written (at most 32)."""
    if type(checkpoint) is not dict or set(checkpoint) != {'excludedSeconds', 'elapsed', 'count'} \
            or not number(checkpoint['excludedSeconds']) or not number(checkpoint['elapsed']) \
            or type(checkpoint['count']) is not int or not 0 <= checkpoint['count'] <= MAX_CHECKPOINTS:
        return 'Short capacity clock checkpoint'
    return None


def _handoff_problem(handoff: object) -> str | None:
    """None before the visible hand-off; then its times against the counted clock and whether it was on time."""
    if handoff is None:
        return None
    if type(handoff) is not dict or set(handoff) != {*HANDOFF_NUMBERS, 'onTime'} \
            or not all(number(handoff[key]) for key in HANDOFF_NUMBERS) or type(handoff['onTime']) is not bool:
        return 'Short capacity clock hand-off'
    return None
