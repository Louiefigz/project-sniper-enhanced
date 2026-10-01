"""Status audit of each Short's settled render-queue credit against the committed trail (P1 Step B4, C11).

Every change of a v2 clock's credit reaches the trail as a capacity event (``capacity-observed``,
``capacity-checkpoint`` or ``capacity-settled``, each carrying the clip's ``excludedSeconds``), as a settlement
entry on a task's settling event (``capacitySettled``: the credit and the owners the watchdog or reconcile removed,
X189 F2), or through a heartbeat of a waiting owner, which writes none. Credit can never grow faster than time
passes, and only while an owner waits, so:
- the recorded total must lie between the last row's total and that total plus the observed seconds since it,
  and must equal it when the trail leaves no owner of the clip waiting (``_waiting_after``, X183 m2);
- each row's total may exceed its predecessor's only by the seconds between them while the trail up to the
  predecessor leaves an owner waiting (``_chain_break``, X190 m2), so a hand edit stays visible after the engine's
  next event carries it.
Both bounds allow ``SETTLE_TOLERANCE``: pending credit (at most ``POLL_BOUND_SECONDS``) accrued before one owner's
event can settle at another's heartbeat after it (X190 n1). A clip is:
- ``consistent`` inside those bounds (or with no credit and no row);
- ``exceeds-trail`` above them (a hand-edited or forged total);
- ``below-trail`` under the last row (an event the record never took, or a lowered total);
- ``no-trail`` with credit but no capacity row;
- ``unexplained-removal`` when the record no longer holds an owner the trail leaves waiting and no row explains it
  (X192): every legitimate removal writes one (a ``finished`` observation, a recovery of ended or orphaned owners, a
  watchdog or reconcile settlement), and a hand-off removes no owner row;
- ``malformed-trail`` when one of its capacity rows is not the shape the engine writes (X190 n2), named, never a
  crash.
Only rows at or before the clip's ``observedElapsed`` count: a later event (committed after this record was
read, or after the clip stopped counting, when it carries 0) says nothing about this record. The threat model is
``approvals``' unkeyed one: a writer who rewrites the record and the trail together is not detected. v1 clocks,
Longs and historical clips are not audited. Status reads it; ``wait`` does not.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from studio.production.approvals import trail_events
from studio.production.queue_clock import POLL_BOUND_SECONDS, SETTLED, writable
from studio.production.queue_clock_schema import number

CAPACITY_EVENTS = ('capacity-observed', 'capacity-checkpoint', 'capacity-settled')
SETTLEMENT = 'capacity-settlement'   # one settlement entry, read as a row of its Short (X189 F2)
TOLERANCE = 1e-6
SETTLE_TOLERANCE = POLL_BOUND_SECONDS + TOLERANCE


def owner_digest(worker: str) -> str:
    """How a settlement entry names a removed owner: the first 16 hex of its key's sha256 (bounded, X189 F2)."""
    return hashlib.sha256(worker.encode('utf-8')).hexdigest()[:16]


def settlement_entry(clip: dict, removed: list[str]) -> dict:
    """One Short's entry on a settling event: when, its settled credit, and the owners removed (``owner_digest``)."""
    clock = clip['capacityClock']
    return {'elapsed': clock['observedElapsed'], 'excludedSeconds': clock['excludedSeconds'],
            'removedWorkers': sorted(owner_digest(key) for key in removed)}


def capacity_audit(root: Path, batch_id: str, record: dict) -> dict:
    """``audit_record`` over the batch's committed trail, read under its lock."""
    return audit_record(record, _committed_trail(root, batch_id))


def audit_record(record: dict, events: list[dict]) -> dict:
    """``{clipId: {status, recordedSeconds, trailSeconds, trailElapsed}}`` for each v2 Short of ``record``, from
    its committed trail events (``status`` passes those it already read, X183 n3)."""
    rows = _capacity_rows(events)
    return {clip_id: _audit_clip(clip, [row for row in rows if row.get('clipId') == clip_id])
            for clip_id, clip in record['clips'].items() if writable(clip)}


def _capacity_rows(events: list[dict]) -> list[dict]:
    """The capacity events, and each settlement entry as a ``capacity-settlement`` row of its Short, in order."""
    rows = []
    for event in events:
        holders = [event, *(item for value in event.values() if type(value) is list for item in value
                            if type(item) is dict)]
        rows += [event] if event.get('event') in CAPACITY_EVENTS else []
        rows += [{**entry, 'event': SETTLEMENT, 'clipId': clip_id} for holder in holders
                 if type(holder.get(SETTLED)) is dict for clip_id, entry in holder[SETTLED].items()
                 if type(entry) is dict]
    return rows


def _committed_trail(root: Path, batch_id: str) -> list[dict]:
    """The batch's committed trail events, read under its lock (an event followed by its own failure is dropped)."""
    from headless.durable_files import DurableFileError, read_private_file
    from studio.native_budget_store import EVENTS, MAX_EVENT_BYTES, BudgetAuthorityError, locked_batch
    try:
        with locked_batch(root, batch_id) as session:
            return trail_events(read_private_file(session.dir_fd, EVENTS, MAX_EVENT_BYTES))
    except (OSError, DurableFileError, UnicodeError, ValueError) as error:
        raise BudgetAuthorityError(f'Budget event trail for {batch_id} is unreadable: {error}') from error


def _well_formed(row: dict) -> bool:
    """A row the engine writes: numeric time and total, and (an event) a str owner and state and lists of str
    owners, or (a settlement) a list of str digests."""
    if not (number(row.get('elapsed')) and number(row.get('excludedSeconds'))):
        return False
    names = [row.get('removedWorkers')] if row['event'] == SETTLEMENT else \
        [row.get('recoveredWorkers', []), row.get('orphanedWorkers', [])]
    worker_ok = row['event'] == SETTLEMENT or (type(row.get('worker')) is str and type(row.get('state')) is str)
    return worker_ok and all(type(value) is list and all(type(name) is str for name in value) for value in names)


def _step(waiting: set, row: dict) -> None:
    """Apply one row to the owners the trail leaves waiting."""
    if row['event'] == SETTLEMENT:
        waiting -= {key for key in waiting if owner_digest(key) in row['removedWorkers']}
        return
    waiting -= {*row.get('recoveredWorkers', ()), *row.get('orphanedWorkers', ())}
    (waiting.add if row['state'] == 'waiting' else waiting.discard)(row['worker'])


def _waiting_set(trail: list[dict]) -> set:
    """The owners the trail leaves waiting (X183 m2): every transition into ``waiting`` writes an event, and
    recovered, orphaned and settled owners no longer wait."""
    waiting: set = set()
    for row in trail:
        _step(waiting, row)
    return waiting


def _waiting_after(trail: list[dict]) -> bool:
    """Whether the trail leaves an owner waiting: credit grows between rows only through a waiting row's heartbeats."""
    return bool(_waiting_set(trail))


def _chain_break(trail: list[dict]) -> bool:
    """Whether some row carries more credit than its predecessor's could have grown to (X190 m2)."""
    waiting: set = set()
    for prior, row in zip(trail, trail[1:]):
        _step(waiting, prior)
        window = row['elapsed'] - prior['elapsed'] if waiting else 0.0
        if row['excludedSeconds'] > prior['excludedSeconds'] + max(0.0, window) + SETTLE_TOLERANCE:
            return True
    return False


def _audit_clip(clip: dict, events: list[dict]) -> dict:
    """One Short's verdict: its recorded credit against its capacity rows at or before its observed time."""
    clock = clip['capacityClock']
    recorded, observed = clock['excludedSeconds'], clock['observedElapsed']
    rows = [row for row in events if row.get('event') in (*CAPACITY_EVENTS, SETTLEMENT)]
    if not all(_well_formed(row) for row in rows):
        return {'status': 'malformed-trail', 'recordedSeconds': recorded, 'trailSeconds': None, 'trailElapsed': None}
    trail = [row for row in rows if row['elapsed'] <= observed + TOLERANCE]
    if not trail:
        status = 'consistent' if recorded == 0.0 else 'no-trail'
        return {'status': status, 'recordedSeconds': recorded, 'trailSeconds': None, 'trailElapsed': None}
    last, waiting = trail[-1], _waiting_set(trail)
    window = max(0.0, observed - last['elapsed']) if waiting else 0.0
    ceiling = last['excludedSeconds'] + window + SETTLE_TOLERANCE
    status = 'unexplained-removal' if waiting - set(clock['workers']) else 'below-trail' \
        if recorded < last['excludedSeconds'] else 'exceeds-trail' \
        if recorded > ceiling or _chain_break(trail) else 'consistent'
    return {'status': status, 'recordedSeconds': recorded, 'trailSeconds': last['excludedSeconds'],
            'trailElapsed': last['elapsed']}
