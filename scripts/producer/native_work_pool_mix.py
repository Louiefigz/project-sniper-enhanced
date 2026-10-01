"""Which capacity rule one pool request gets, and whether it may join the work present.

native_work_pool.decide asks here for the request's mode (its covering qualification
profile, native_work_qualification.mode_for) and for what the members and queued requests
already present allow. Mixes are decided before capacity. An uncovered request (exclusive, no
profile covers it) takes a ticket and waits for an idle pool; a profile-admitted request waits
beside a live exclusive or outside-profile member; both are waitable ('already active'). An
uncovered request beside a live member of its own project, or a covered one beside its own
project's live exclusive member (X107 m1), is refused at once and never queued: it may be that
member's nested work, which could never be admitted while it waits; an independent sibling stage
is admitted once the member ends (X123 d3), so the refusal names the member to wait for.
Quarantined exclusive or outside-profile members stay terminal (recover first). A waiting
uncovered ticket holds back later render (heavy) requests, so the pool drains for it in FIFO
order, but never a request for the project of a live member (possible nested work of that
member: the ticket may be waiting on it), which also passes the tickets the uncovered one holds
back (X107 B1); audio passes it only until it has been passed PASS_LIMIT times (X107 m2). Without
any record the pool is the pre-pool exclusive pool: requests queue as before. Studio startup
members (native_work_pool_studio) take part in no profile or mix decision, and a Studio request
queues only behind Studio tickets.
"""
from __future__ import annotations

import dataclasses
import time
from types import SimpleNamespace

import native_work_pool_fence as fence
import native_work_qualification as qualification
import native_work_pool_state as state
import native_work_workload as workloads
from native_work_pool_policy import LEDGER_CLASSES, STUDIO_CLASS, PoolMode, queue_key

PASS_LIMIT = 4  # X107: younger requests pass one waiting uncovered ticket at most this often, nested work aside


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


def _live(view: state.PoolView) -> list[dict]:
    """Live members that take part in mix decisions: every readable record but a Studio member's."""
    return [member for member in view.members if member['state'] == 'live' and isinstance(member['record'], dict)
            and member['record'].get('class') != STUDIO_CLASS]


def blockers(mode: PoolMode, view: state.PoolView, outside: list[tuple]) -> list[str]:
    """Sorted nonces of the live members a mix wait waits for (credited occupants, native_work_pool_credit)."""
    if mode.exclusive:
        return sorted(member['nonce'] for member in _live(view))
    return sorted({nonce for nonce, status in _exclusive(view) + list(outside) if status == 'live'})


def _unmatched(mode: PoolMode, view: state.PoolView, request: object) -> tuple[list[str], list[str]]:
    """(waits, unsupported) of an uncovered request: it waits for an idle pool, except beside its own project or
    beside an older pool client's live member (X242: refused by name, never queued or credited).

    Only live members make it wait here. Queue order is fifo_ahead's (an exclusive request competes with
    every older ticket); counting younger tickets here would deadlock, since they queue behind this one.
    """
    live = _live(view)
    if not live:
        return [], []
    covered = ' | '.join(mode.record['unmatched'])
    older = sorted(member['nonce'] for member in live if not fence.is_current(member['record']))
    if older:   # X242: an older pool client predates the mix wait, so no wait beside it is bounded: fail closed
        return [], [f"no qualification profile covers this workload ({covered}) and an older pool client's "
                    f"member(s) {', '.join(older)} are live: it cannot wait beside them"]
    own = [member['nonce'] for member in live if member['record'].get('project') == request.project]
    if own:
        return [], [f"no qualification profile covers this workload ({covered}) and its own project's member "
                    f'{own[0]} is live: it can never be admitted beside it']
    _tally_passes(view, request, live)
    queued = [ticket for ticket in fence.request_tickets(view) if ticket['nonce'] != request.ticket.nonce]
    return [f'an uncovered workload waits for an idle pool: no qualification profile covers it ({covered}); '
            f"live members: {', '.join(sorted(member['nonce'] for member in live))}; queued: {len(queued)}"], []


def _tally_passes(view: state.PoolView, request: object, live: list[dict]) -> None:
    """Record on this waiting uncovered request's own ticket the younger members admitted meanwhile (m2).

    Each passed it; the tally stops at PASS_LIMIT. Only this waiter writes its ticket, in place, inside
    the ledger transaction (native_work_pool_fence.rewrite_ticket). The view was read before
    refresh_ticket ran in this transaction, so the rewrite carries the request's own workload (X123 d1).
    """
    row = next((ticket for ticket in view.tickets if ticket['name'] == request.ticket.name), None)
    record = row['record'] if row else None
    if not isinstance(record, dict) or len(record.get('passedBy') or ()) >= PASS_LIMIT:
        return
    younger = {member['nonce'] for member in live if type(member['record'].get('ticket')) is int
               and member['record']['ticket'] > request.ticket.sequence}
    tally = sorted({*(record.get('passedBy') or ()), *younger})[:PASS_LIMIT]
    if tally != (record.get('passedBy') or []):
        row['record'] = dict(record, workload=request.workload, passedBy=tally)
        fence.rewrite_ticket(request.ticket, row['record'])


def problems(mode: PoolMode, view: state.PoolView, outside: list[tuple],
             request: object) -> tuple[list[str], list[str], list[str]]:
    """(waits, unsupported, terminal) reasons this request cannot join the pool work present now."""
    if mode.exclusive:
        return (*_unmatched(mode, view, request), []) if (mode.record or {}).get('unmatched') else ([], [], [])
    if mode.name != 'qualified':
        return [], [], []
    live, profile = blockers(mode, view, outside), mode.record['profile']
    held = sorted({nonce for nonce, status in _exclusive(view) + list(outside) if status != 'live'})
    own = [member['nonce'] for member in _live(view) if member['record'].get('mode') == 'exclusive'
           and member['record'].get('project') == request.project]  # a self-conflict never resolves by waiting
    unsupported = [f"its own project's member(s) {', '.join(own)} run exclusive: it can be admitted once they end "
                   '(refused now, never queued: nested work under them would never be admitted)'] if own else []
    waits = [f'waiting for member(s) {", ".join(live)} (exclusive or outside qualification profile {profile}) '
             'to finish: no profile covers running beside them'] if live and not own else []
    terminal = [f'member(s) {", ".join(held)} outside qualification profile {profile} or exclusive have '
                'unverified cleanup'] if held else []
    return waits, unsupported, terminal


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


def may_pass(view: state.PoolView, request: object, record: dict) -> bool:
    """Whether this request may pass an older uncovered request's ticket (`record`) instead of queueing.

    A live member's possible nested work (its project) always may: the ticket waits for that member.
    Audio may while the ticket was passed fewer than PASS_LIMIT times; another render never may.
    """
    if request.project in {member['record'].get('project') for member in _live(view)}:
        return True
    return request.lane != 'heavy' and len(record.get('passedBy') or ()) < PASS_LIMIT


def _held(view: state.PoolView, ticket: dict, passed: list[dict]) -> bool:
    """A younger ticket that a passed uncovered ticket holds back: whoever passes that one passes it too (B1)."""
    record = ticket['record'] or {}
    held = SimpleNamespace(lane=record.get('class'), project=record.get('project'))
    return any(ticket['sequence'] > row['sequence'] and not may_pass(view, held, row['record'] or {})
               for row in passed)


def fifo_ahead(view: state.PoolView, request: object, mode: PoolMode, context: tuple) -> list[dict]:
    """The older live request tickets competing for this request's capacity; only the first may be admitted.

    `context` is (session, committed profiles, whether this request holds or now takes a fence). A
    Studio request competes only with Studio tickets, and a Studio ticket is never ahead of a render.
    """
    session, committed, fenced = context
    rows = []  # (older competing ticket, whether it is an uncovered request this request may pass)
    for ticket in competing(view, fenced):
        record = ticket['record'] or {}
        if ticket['sequence'] >= request.ticket.sequence or record.get('class') not in LEDGER_CLASSES:
            continue
        if STUDIO_CLASS in (record['class'], request.lane):
            rows += [(ticket, False)] if record['class'] == request.lane else []
            continue
        other, _outside = request_mode(session, committed, record)
        uncovered = other.exclusive and bool((other.record or {}).get('unmatched'))
        if queue_conflict((mode, request.lane), (other, record['class'])):
            rows.append((ticket, uncovered and may_pass(view, request, record)))
    passed = [ticket for ticket, passes in rows if passes]
    return [ticket for ticket, passes in rows if not passes and not _held(view, ticket, passed)]


def fifo_reasons(view: state.PoolView, request: object, mode: PoolMode, context: tuple) -> list[str]:
    """'queued behind N earlier request(s)' while fifo_ahead finds any; nothing when this request is first."""
    ahead = len(fifo_ahead(view, request, mode, context))
    return [f'queued behind {ahead} earlier request(s)'] if ahead else []
