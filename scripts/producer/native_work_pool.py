"""Fair, reservation-accounted host pool for native 'heavy' and 'audio' work and Studio startup.

Every admission is one short transaction under the pool ledger lock: observe members,
tickets and legacy fences, enqueue the caller once (FIFO by ticket sequence within its
capacity class), then admit only the queue head when a slot, the aggregate memory
budget and the shared disk reservation all fit. Each request's capacity rule comes from
the qualification profile covering its workload, and whether it may join the work present
is decided first (native_work_pool_mix.py). A member whose guarantee older pool clients
cannot see holds a compatibility fence (native_work_pool_fence.py). Refusals say whether
waiting can help (NativeWorkQueued, message contains 'already active') or not
(NativeWorkQuarantined, 'cleanup is unverified'; NativeWorkUnsupportedMix, no profile
covers the mix). Nothing here sleeps except acquire_until, which is bounded by the
caller's monotonic deadline. Budget derivation: native_work_pool_policy.py.
Disk is charged per shared space, an APFS container or one filesystem (native_work_pool_disk.py);
a running member grows its reservation with native_work_pool_expand.expand_disk. Whether a wait
earns Short credit is native_work_pool_credit.py: it only annotates the decision's context.
A Studio view's startup has its own small class and slots (native_work_pool_studio.py).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import native_work_lease as lease_module
import native_work_pool_credit as credit
import native_work_pool_disk as disk
import native_work_pool_fence as fence
import native_work_pool_mix as mix
import native_work_pool_policy as policy
import native_work_pool_roots as pool_roots
import native_work_qualification as qualification
import native_work_pool_state as state
from native_work_pool_observe import observe
from native_work_pool_lease import Ticket, enqueue, install
from native_work_pool_policy import DISK_RESERVATION_BYTES, LEDGER_CLASSES, STUDIO_CLASS, PoolMode
from native_work_pool_state import NativeWorkQuarantined, NativeWorkQueued  # noqa: F401  (public API)


@dataclass
class PoolRequest:
    """One owner's request; pass the same object on every retry to keep its FIFO ticket.

    Attributes:
        lane: 'heavy' (browser/video), 'audio' (ffmpeg-only, small) or 'studio' (Studio startup).
        project: Project path recorded as metadata and for session matching.
        root: Owner output directory (session matching and disk device).
        receipt: Owner receipt path, recorded for evidence and qualification summaries.
        fixed_owned_gib: Explicit caller ResourcePolicy owned-tree limit, if any.
        disk_bytes: Planned disk bytes; defaults to the class reservation.
        declares_launch: The owner calls mark_launching() before spawning anything.
        fence_reasons: State this member will hold that older pool clients cannot see (for
            example disk on another filesystem); it is admitted only behind a fence.
        workload: What it runs (native_work_workload.describe), set before its first ticket.
        until: The caller's monotonic deadline (owner admission, acquire_until); bounds the
            classification of earlier engines' roots before each transaction.
    """

    lane: str
    project: str
    root: str | None = None
    receipt: str | None = None
    fixed_owned_gib: float | None = None
    disk_bytes: int | None = None
    declares_launch: bool = False
    fence_reasons: tuple[str, ...] = ()
    until: float | None = None
    workload: dict | None = field(default=None, init=False)
    fence_tickets: list = field(default_factory=list, init=False)
    ticket: Ticket | None = field(default=None, init=False)
    sequence: int | None = field(default=None, init=False)
    attempts: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        """Validate the class and canonicalize paths before any transaction."""
        if self.lane not in LEDGER_CLASSES:
            raise ValueError('Unknown native pool class')
        self.project = str(Path(self.project).resolve())
        self.root = str(Path(self.root).resolve()) if self.root else None
        if self.disk_bytes is not None and (type(self.disk_bytes) is not int or self.disk_bytes < 0):
            raise ValueError('Planned disk bytes must be a nonnegative integer')

    def withdraw(self) -> None:
        """Release a still-pending ticket and fence; the next transaction prunes their files."""
        if self.ticket is not None:
            self.ticket.withdraw()
            self.ticket = None
        for ticket in self.fence_tickets:
            ticket.withdraw()
        self.fence_tickets = []


@dataclass
class Decision:
    """Admission outcome with the exact figures used, retained in owner receipts."""

    mode: PoolMode
    reservation: int  # the member's own memory: its guard bound, and what this client charges it
    disk: int
    device: int
    space: str = ''
    charge: int = 0  # reservationBytes older clients read: the whole budget for an exclusive or fenced member
    reasons: list = field(default_factory=list)
    terminal: list = field(default_factory=list)
    unsupported: list = field(default_factory=list)
    fence: list = field(default_factory=list)
    context: dict = field(default_factory=dict)
    lane: str = ''  # the request's class; native_work_pool_credit credits only 'heavy'


def _member_charges(view: state.PoolView, physical: int) -> list[dict]:
    """Charge every member; an unreadable record is charged maximally in every class.

    A record of this client is charged its own size (guardReservationBytes); its
    reservationBytes may be the whole budget, which is only for older clients. An
    unreadable record whose supervisor still holds its lock is live (waitable); once the
    lock is free it is quarantined like any other member until recovery.
    """
    rows = []
    for member in view.members:
        record = member['record']
        spaces = disk.charged_spaces(record, view.roots)  # space -> reserved bytes, including any expansion
        known = spaces is not None
        rows.append({'class': record['class'] if known else '*',
                     'memory': record.get('guardReservationBytes', record['reservationBytes']) if known
                     else policy.single_job_bytes(physical),
                     'spaces': spaces,  # None: unknown, which refuses (live: waits for) every disk admission
                     'quarantined': member['state'] != 'live', 'nonce': member['nonce']})
    if view.legacy_marker is not None:
        # While an old-code job holds heavy.lock exclusively the marker is its live record;
        # only a marker nobody holds is an unverified-cleanup quarantine.
        rows.append({'class': 'heavy', 'memory': policy.single_job_bytes(physical), 'spaces': {},
                     'quarantined': not view.legacy_active, 'nonce': 'legacy-heavy.active.json'})
    return rows


def _occupancy(rows: list[dict], mode: PoolMode, lane: str) -> list[dict]:
    """Rows that consume the capacity this request needs."""
    if mode.exclusive:
        return rows
    return [row for row in rows if row['class'] in (lane, '*')]


def _memory_reasons(decision: Decision, rows: list[dict], physical: int) -> None:
    """Sum live, quarantined and legacy reservations against the aggregate budget."""
    total = policy.aggregate_bytes(physical)
    charged = sum(row['memory'] for row in rows)
    quarantined = sum(row['memory'] for row in rows if row['quarantined'])
    decision.context.update(aggregateBudgetBytes=total, chargedBytes=charged,
                            quarantinedChargedBytes=quarantined)
    if quarantined + decision.reservation > total:
        decision.terminal.append('quarantined and legacy reservations leave no room in the host memory budget')
    elif charged + decision.reservation > total:
        decision.reasons.append('host memory budget is fully reserved by running members')


def _slot_reasons(decision: Decision, rows: list[dict], lane: str) -> None:
    """A quarantined slot stays occupied; live slots free when their owners finish."""
    capacity = policy.class_capacity(decision.mode, lane)
    occupied = _occupancy(rows, decision.mode, lane)
    quarantined = [row['nonce'] for row in occupied if row['quarantined']]
    decision.context.update(capacity=capacity, occupied=len(occupied), quarantinedMembers=quarantined)
    if len(quarantined) >= capacity:
        decision.terminal.append(f'all {capacity} {lane} slot(s) are quarantined: {", ".join(quarantined)}')
    elif len(occupied) >= capacity:
        decision.reasons.append(f'all {capacity} {lane} slot(s) are occupied')


def _reason_groups(view: state.PoolView, request: PoolRequest, decision: Decision, context: tuple) -> dict:
    """Append the session, legacy, slot, memory and disk reasons in that order; return them by source.

    `context` is (the valid qualification session or None, the charged member rows, physical RAM).
    Disk and session reasons are never credited, so they share the 'other' group
    (native_work_pool_credit.ReasonGroups). Others' disk bytes in the same space are spent.
    """
    session, rows, physical = context
    groups = {'other': ['a pool qualification session is running its declared jobs']
              if session and decision.mode.name != 'qualification-session' else [],
              'legacy': ['legacy exclusive heavy work is running'] if view.legacy_active else []}
    decision.reasons += groups['other'] + groups['legacy']
    steps = (('slot', lambda: _slot_reasons(decision, rows, request.lane)),
             ('memory', lambda: _memory_reasons(decision, rows, physical)),
             ('other', lambda: disk.admission(decision, rows, request.root or request.project)))
    for name, step in steps:
        prior = len(decision.reasons)
        step()
        groups[name] = [*groups.get(name, []), *decision.reasons[prior:]]
    return {name: tuple(reasons) for name, reasons in groups.items()}


def decide(view: state.PoolView, request: PoolRequest, host: dict,
           committed: qualification.Committed) -> Decision:
    """Apply profile, queue order, slots, aggregate memory and shared disk to one request.

    native_work_pool_credit.classify then records whether the wait is credited; it changes no reason.
    """
    if request.lane == STUDIO_CLASS:  # its own slots; no profile, mix, fence or credit
        from native_work_pool_studio import decide as studio_decide  # it builds on this module
        return studio_decide(view, request, host)
    physical = host['memsizeBytes']
    session = mix.session_of(view, host)
    rows = _member_charges(view, physical)
    readable = mix.readable(view, {row['nonce'] for row in rows if row['spaces'] is None})
    row = {'project': request.project, 'root': request.root, 'class': request.lane, 'workload': request.workload}
    mode, outside = mix.request_mode(session, committed, row, mix.members(readable))
    decision = Decision(mode, policy.reservation_bytes(mode, request.lane, physical, request.fixed_owned_gib),
                        request.disk_bytes if request.disk_bytes is not None
                        else DISK_RESERVATION_BYTES[request.lane], 0, lane=request.lane)
    decision.unsupported, terminal = mix.problems(mode, readable, outside, request.ticket)
    decision.terminal += terminal
    groups = _reason_groups(view, request, decision, (session, rows, physical))
    requested = (*request.fence_reasons, *disk.fence_reasons(decision.space))
    decision.fence = fence.reasons_for(mode, requested) if committed.legacy_qualified else []
    # Older clients read reservationBytes: an exclusive or fenced member fills their budget, so none
    # starts beside it, and none after its supervisor dies (the fence tickets lapse, the record stays).
    fills = mode.exclusive or decision.fence
    decision.charge = policy.aggregate_bytes(physical) if fills else decision.reservation
    fenced = bool(decision.fence or request.fence_tickets)
    fifo = mix.fifo_reasons(view, request, mode, (session, committed, fenced))
    decision.reasons += fifo
    credit.classify(decision, _occupancy(rows, mode, request.lane), credit.ReasonGroups(fifo=tuple(fifo), **groups))
    decision.context['ticket'] = request.sequence
    return decision


def _pruned_summary(row: dict) -> dict:
    """Keep exact pruning evidence (which ticket/session, whose identity) for receipts."""
    record = row.get('ticket') and (row.get('record') or {})
    return {'ticket': row.get('ticket'), 'session': bool(row.get('session')), 'reason': row['reason'],
            'waiterIdentityLive': row.get('waiterIdentityLive'),
            'waiter': record.get('supervisor') if isinstance(record, dict) else None}


def _transact(lane: str, request: PoolRequest, host: dict, committed: qualification.Committed) -> object:
    """One ledger transaction: observe, enqueue once, decide, then admit or refuse."""
    roots = pool_roots.prescan(request.until)  # earlier engines' roots: before, never inside, the lock
    with state.ledger(time.monotonic() + state.LEDGER_WAIT_SECONDS) as namespace:
        view = observe(namespace)
        view.roots = roots
        request.attempts += 1
        if request.ticket is None:
            request.ticket = enqueue(namespace, view, request)
            request.sequence = request.ticket.sequence
        fence.refresh_ticket(namespace, request.ticket, request.workload)
        decision = decide(view, request, host, committed)
        decision.context.update(pruned=[_pruned_summary(row) for row in view.pruned], fence=decision.fence,
                                diskChargedInEverySpace=roots.notes)
        if decision.unsupported or decision.terminal:
            raise fence.refusal(lane, decision)
        if decision.fence and not request.fence_tickets:
            owner = {'project': request.project, 'root': request.root, 'receipt': request.receipt,
                     'nonce': request.ticket.nonce}
            request.fence_tickets = fence.take(namespace, view, owner, decision.fence)
        if decision.reasons:
            raise fence.refusal(lane, decision)
        return install(namespace, request, decision)


def admit(lane: str, project: str, request: PoolRequest | None = None) -> object:
    """Admit one member now or raise; a supplied request keeps its ticket on refusal."""
    transient = request is None
    request = request or PoolRequest(lane, project)
    if request.lane != lane or request.project != str(Path(project).resolve()):
        raise ValueError('Pool request does not match the requested class and project')
    host = policy.host_identity()
    try:
        committed = qualification.committed(host)
        mix.describe(request, committed.needs_engine)  # a Studio request is never described (no profile or mix)
        return _transact(lane, request, host, committed)
    finally:
        if transient:
            request.withdraw()


def _attempt(lane: str, project: str, request: PoolRequest, until: float) -> object | None:
    """One attempt; None means wait and retry, which is only allowed before the deadline."""
    try:
        return lease_module.NativeWorkLease.acquire(lane, project, request=request)
    except NativeWorkQueued:
        if time.monotonic() >= until:
            raise
    return None


def acquire_until(lane: str, project: str, until: float, request: PoolRequest | None = None) -> object:
    """Wait in FIFO order until admitted or the caller's monotonic deadline passes."""
    request = request or PoolRequest(lane, project)
    request.until = until if request.until is None else min(request.until, until)
    try:
        lease = _attempt(lane, project, request, until)
        while lease is None:
            time.sleep(min(1.0, max(0.0, until - time.monotonic())))
            lease = _attempt(lane, project, request, until)
        return lease
    finally:
        request.withdraw()
