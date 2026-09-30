"""Status audit of each Short's settled render-queue credit against the committed trail (P1 Step B4, C11).

Every change of a v2 clock's credit reaches the trail as a capacity event (``capacity-observed``,
``capacity-checkpoint`` or ``capacity-settled``, each carrying the clip's ``excludedSeconds``) or through a
heartbeat of a waiting owner, which writes none. Credit can never grow faster than time passes, so the recorded
total must lie between the last such event's total and that total plus the observed seconds since that event, and
must equal it when the trail leaves no owner of the clip waiting (``_waiting_after``, X183 m2). A clip is:
- ``consistent`` inside that bound (or with no credit and no event);
- ``exceeds-trail`` above it (a hand-edited or forged total);
- ``below-trail`` under the last event (an event the record never took, or a lowered total);
- ``no-trail`` with credit but no capacity event.
Only events at or before the clip's ``observedElapsed`` count: a later event (committed after this record was
read, or after the clip stopped counting, when it carries 0) says nothing about this record. The threat model is
``approvals``' unkeyed one: a writer who rewrites the record and the trail together is not detected. v1 clocks,
Longs and historical clips are not audited. Status reads it; ``wait`` does not.
"""
from __future__ import annotations

from pathlib import Path

from studio.production.approvals import trail_events
from studio.production.queue_clock import writable
from studio.production.queue_clock_schema import number

CAPACITY_EVENTS = ('capacity-observed', 'capacity-checkpoint', 'capacity-settled')
TOLERANCE = 1e-6


def capacity_audit(root: Path, batch_id: str, record: dict) -> dict:
    """``audit_record`` over the batch's committed trail, read under its lock."""
    return audit_record(record, _committed_trail(root, batch_id))


def audit_record(record: dict, events: list[dict]) -> dict:
    """``{clipId: {status, recordedSeconds, trailSeconds, trailElapsed}}`` for each v2 Short of ``record``, from
    its committed trail events (``status`` passes those it already read, X183 n3)."""
    return {clip_id: _audit_clip(clip, [row for row in events if row.get('clipId') == clip_id])
            for clip_id, clip in record['clips'].items() if writable(clip)}


def _committed_trail(root: Path, batch_id: str) -> list[dict]:
    """The batch's committed trail events, read under its lock (an event followed by its own failure is dropped)."""
    from headless.durable_files import DurableFileError, read_private_file
    from studio.native_budget_store import EVENTS, MAX_EVENT_BYTES, BudgetAuthorityError, locked_batch
    try:
        with locked_batch(root, batch_id) as session:
            return trail_events(read_private_file(session.dir_fd, EVENTS, MAX_EVENT_BYTES))
    except (OSError, DurableFileError, UnicodeError, ValueError) as error:
        raise BudgetAuthorityError(f'Budget event trail for {batch_id} is unreadable: {error}') from error


def _waiting_after(trail: list[dict]) -> bool:
    """Whether the trail leaves an owner of the clip waiting (X183 m2): credit grows between events only through a
    waiting row's heartbeats, and every transition into ``waiting`` writes an event. Recovered and orphaned owners
    no longer wait."""
    waiting: set = set()
    for row in trail:
        waiting -= {*row.get('recoveredWorkers', ()), *row.get('orphanedWorkers', ())}
        (waiting.add if row.get('state') == 'waiting' else waiting.discard)(row.get('worker'))
    return bool(waiting)


def _audit_clip(clip: dict, events: list[dict]) -> dict:
    """One Short's verdict: its recorded credit against its last capacity event at or before its observed time."""
    clock = clip['capacityClock']
    recorded, observed = clock['excludedSeconds'], clock['observedElapsed']
    trail = [row for row in events if row.get('event') in CAPACITY_EVENTS and number(row.get('elapsed'))
             and number(row.get('excludedSeconds')) and row['elapsed'] <= observed + TOLERANCE]
    if not trail:
        status = 'consistent' if recorded == 0.0 else 'no-trail'
        return {'status': status, 'recordedSeconds': recorded, 'trailSeconds': None, 'trailElapsed': None}
    last = trail[-1]
    window = max(0.0, observed - last['elapsed']) if _waiting_after(trail) else 0.0
    ceiling = last['excludedSeconds'] + window + TOLERANCE
    status = 'below-trail' if recorded < last['excludedSeconds'] else 'exceeds-trail' if recorded > ceiling \
        else 'consistent'
    return {'status': status, 'recordedSeconds': recorded, 'trailSeconds': last['excludedSeconds'],
            'trailElapsed': last['elapsed']}
