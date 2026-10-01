"""Which capacity rule one pool request gets, and whether it may join the work present.

native_work_pool.decide asks here for the request's mode (its covering qualification
profile, native_work_qualification.mode_for) and for what the members and queued requests
already present allow. Mixes are decided before capacity:
- A request no profile covers (exclusive, with 'unmatched' reasons) is admitted only onto
  an idle pool; with any live member or other queued request it is refused at once with
  NativeWorkUnsupportedMix, never queued, so it cannot hold up other classes while it waits.
- A profile-admitted request is refused at once beside a live exclusive member or a live
  member its profile does not cover, and terminally (recover first) beside such a member
  whose cleanup is unverified: uncertain owners keep their charge and their exclusivity.
- Without any record the pool is the pre-pool exclusive pool: requests queue as before.
Waiting stays reserved for capacity (slots, memory, disk, FIFO order). Studio startup members
(native_work_pool_studio) take part in no profile or mix decision, and a Studio request queues
only behind Studio tickets.
"""
from __future__ import annotations

import dataclasses
import time

import native_work_pool_fence as fence
import native_work_qualification as qualification
import native_work_pool_state as state
import native_work_workload as workloads
from native_work_pool_policy import LEDGER_CLASSES, STUDIO_CLASS, PoolMode, queue_key


def describe(request: object, needs_engine: bool) -> None:
    """Describe the workload once per request, outside the ledger lock (engine only if needed).

    A Studio request is never described: its workload is the unrecorded 'studio' row.
    """
    if request.lane == STUDIO_CLASS:
        request.workload = workloads.unrecorded(STUDIO_CLASS)
        return
    if request.workload is None:
        request.workload = workloads.describe(request.project, request.receipt, request.lane)
    if needs_engine and request.workload['engine'] is None:
        request.workload = {**request.workload, 'engine': workloads.current_engine()}


def readable(view: state.PoolView, unknown: set[str]) -> state.PoolView:
    """The view without members whose records admission cannot read.

    Their workload and mode are unknown, so they take part in no profile or mix decision;
    capacity still charges them maximally (waitable while live, terminal once quarantined).
    """
    return dataclasses.replace(view, members=[member for member in view.members if member['nonce'] not in unknown])


def members(view: state.PoolView) -> list[tuple[str, dict, str]]:
    """(nonce, workload, state) of every member but Studio's; an older client's member is 'unrecorded'."""
    rows = []
    for member in view.members:
        record = member['record'] if isinstance(member['record'], dict) else {}
        if record.get('class') == STUDIO_CLASS:
            continue
        mode_record = record.get('modeRecord') if isinstance(record.get('modeRecord'), dict) else {}
        workload = mode_record.get('workload')
        workload = workload if isinstance(workload, dict) else workloads.unrecorded(record.get('class'))
        rows.append((member['nonce'], workload, member['state']))
    return rows


def request_mode(session: dict | None, committed: qualification.Committed, row: dict,
                 present: list[tuple] = ()) -> tuple[PoolMode, list[tuple]]:
    """Declared harness jobs use the candidate size; everything else its covering profile."""
    if session and qualification.session_member(session['value'], row['project'], row.get('root')):
        return qualification.session_mode(session['value'], session['slots']), []
    workload = row.get('workload') if isinstance(row.get('workload'), dict) else workloads.unrecorded(row['class'])
    return qualification.mode_for(committed, workload, present)


def _exclusive(view: state.PoolView) -> list[tuple[str, str]]:
    """(nonce, state) of every member admitted in exclusive mode (never a Studio member)."""
    return [(member['nonce'], member['state']) for member in view.members
            if isinstance(member['record'], dict) and member['record'].get('mode') == 'exclusive'
            and member['record'].get('class') != STUDIO_CLASS]


def _unmatched(mode: PoolMode, view: state.PoolView, own: object) -> list[str]:
    """An uncovered request may start only on an idle pool."""
    live = [member['nonce'] for member in view.members if member['state'] == 'live']
    queued = [ticket['name'] for ticket in fence.request_tickets(view) if own is None or ticket['name'] != own.name]
    if not live and not queued:
        return []
    return [f"no qualification profile covers this workload ({' | '.join(mode.record['unmatched'])}) and pool "
            f"work is present (members: {', '.join(live) or 'none'}; queued: {len(queued)})"]


def problems(mode: PoolMode, view: state.PoolView, outside: list[tuple], own: object) -> tuple[list[str], list[str]]:
    """(unsupported, terminal) reasons this request cannot join the pool work present."""
    if mode.exclusive:
        return (_unmatched(mode, view, own) if (mode.record or {}).get('unmatched') else []), []
    if mode.name != 'qualified':
        return [], []
    rows = _exclusive(view) + [(nonce, status) for nonce, status in outside]
    live = sorted({nonce for nonce, status in rows if status == 'live'})
    held = sorted({nonce for nonce, status in rows if status != 'live'})
    profile = mode.record['profile']
    unsupported = [f'live member(s) {", ".join(live)} run exclusive or outside qualification profile {profile}'] \
        if live else []
    terminal = [f'member(s) {", ".join(held)} outside qualification profile {profile} or exclusive have '
                'unverified cleanup'] if held else []
    return unsupported, terminal


def queue_conflict(first: tuple, second: tuple) -> bool:
    """Tickets (mode, lane) compete for the same capacity; exclusive competes with every ticket."""
    return first[0].exclusive or second[0].exclusive or queue_key(*first) == queue_key(*second)


def session_of(view: state.PoolView, host: dict) -> dict | None:
    """Return a valid live qualification session with its candidate slots, else None."""
    if view.session is None or view.session.get('malformed'):
        return None
    try:
        slots = qualification.validate_session(view.session, host, time.time())
    except qualification.PoolRecordError:
        return None
    return {'value': view.session, 'slots': slots}


def competing(view: state.PoolView, fenced: bool) -> list[dict]:
    """Request tickets that can hold this client's request back in queue order.

    While any fence ticket is held (or this request takes one in this transaction), older
    clients' requests cannot be admitted: every fence sorts ahead of them
    (native_work_pool_fence). No request of this client counts them then, fenced or not;
    counting them would deadlock (this request waiting for an older one that waits for a
    fence held by this request or by one queued behind it).
    """
    tickets = fence.request_tickets(view)
    if not fenced and not any(fence.is_fence(ticket['record']) for ticket in view.tickets):
        return tickets
    return [ticket for ticket in tickets if fence.is_current(ticket['record'])]


def fifo_reasons(view: state.PoolView, request: object, mode: PoolMode, context: tuple) -> list[str]:
    """Only the earliest live request ticket competing for the same capacity may be admitted.

    `context` is (session, committed profiles, whether this request holds or now takes a fence). A
    Studio request competes only with Studio tickets, and a Studio ticket is never ahead of a render.
    """
    session, committed, fenced = context
    ahead = 0
    for ticket in competing(view, fenced):
        record = ticket['record'] or {}
        if ticket['sequence'] >= request.ticket.sequence or record.get('class') not in LEDGER_CLASSES:
            continue
        if STUDIO_CLASS in (record['class'], request.lane):
            ahead += record['class'] == request.lane
            continue
        other, _outside = request_mode(session, committed, record)
        ahead += queue_conflict((mode, request.lane), (other, record['class']))
    return [f'queued behind {ahead} earlier request(s)'] if ahead else []
