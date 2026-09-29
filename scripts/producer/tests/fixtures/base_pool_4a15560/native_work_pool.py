"""Fair, reservation-accounted host pool for native 'heavy' and 'audio' work.

Every admission is one short transaction under the pool ledger lock: observe members,
tickets and legacy fences, enqueue the caller once (FIFO by ticket sequence within its
capacity class), then admit only the queue head when a slot, the aggregate memory
budget and the shared disk reservation all fit. Refusals say whether waiting can help
(NativeWorkQueued, message contains 'already active') or not (NativeWorkQuarantined,
'cleanup is unverified'). Nothing here sleeps except acquire_until, which is bounded by
the caller's monotonic deadline. Budget derivation: native_work_pool_policy.py.
"""
from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

import native_work_lease as lease_module
import native_work_pool_policy as policy
import native_work_qualification as qualification
import native_work_pool_state as state
from native_work_pool_observe import observe
from native_work_pool_lease import Ticket, enqueue, install
from native_work_pool_policy import DISK_RESERVATION_BYTES, DISK_RESERVE_BYTES, POOL_CLASSES, PoolMode
from native_work_pool_state import NativeWorkQuarantined, NativeWorkQueued


@dataclass
class PoolRequest:
    """One owner's request; pass the same object on every retry to keep its FIFO ticket.

    Attributes:
        lane: 'heavy' (browser/video) or 'audio' (ffmpeg-only, small).
        project: Project path recorded as metadata and for session matching.
        root: Owner output directory (session matching and disk device).
        receipt: Owner receipt path, recorded for evidence and qualification summaries.
        fixed_owned_gib: Explicit caller ResourcePolicy owned-tree limit, if any.
        disk_bytes: Planned disk bytes; defaults to the class reservation.
        declares_launch: The owner calls mark_launching() before spawning anything.
    """

    lane: str
    project: str
    root: str | None = None
    receipt: str | None = None
    fixed_owned_gib: float | None = None
    disk_bytes: int | None = None
    declares_launch: bool = False
    ticket: Ticket | None = field(default=None, init=False)
    sequence: int | None = field(default=None, init=False)
    attempts: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        """Validate the class and canonicalize paths before any transaction."""
        if self.lane not in POOL_CLASSES:
            raise ValueError('Unknown native pool class')
        self.project = str(Path(self.project).resolve())
        self.root = str(Path(self.root).resolve()) if self.root else None
        if self.disk_bytes is not None and (type(self.disk_bytes) is not int or self.disk_bytes < 0):
            raise ValueError('Planned disk bytes must be a nonnegative integer')

    def withdraw(self) -> None:
        """Release a still-pending ticket; the next transaction prunes its file."""
        if self.ticket is not None:
            self.ticket.withdraw()
            self.ticket = None


@dataclass
class Decision:
    """Admission outcome with the exact figures used, retained in owner receipts."""

    mode: PoolMode
    reservation: int
    disk: int
    device: int
    reasons: list = field(default_factory=list)
    terminal: list = field(default_factory=list)
    context: dict = field(default_factory=dict)


def _session(view: state.PoolView, host: dict) -> dict | None:
    """Return a valid live session with its candidate slots, else None."""
    if view.session is None or view.session.get('malformed'):
        return None
    try:
        slots = qualification.validate_session(view.session, host, time.time())
    except qualification.PoolRecordError:
        return None
    return {'value': view.session, 'slots': slots}


def request_mode(session: dict | None, committed: PoolMode, row: dict) -> PoolMode:
    """Declared harness jobs use the candidate size; everything else the record."""
    if session and qualification.session_member(session['value'], row['project'], row.get('root')):
        return qualification.session_mode(session['value'], session['slots'])
    return committed


def _member_charges(view: state.PoolView, physical: int) -> list[dict]:
    """Charge every member; an unreadable record is charged maximally in every class."""
    rows = []
    for member in view.members:
        record = member['record'] or {}
        known = record.get('class') in POOL_CLASSES and type(record.get('reservationBytes')) is int
        rows.append({'class': record.get('class') if known else '*',
                     'memory': record['reservationBytes'] if known else policy.single_job_bytes(physical),
                     'disk': record.get('diskReservationBytes') if known else 0,
                     'device': record.get('diskDevice'),
                     'quarantined': member['state'] != 'live' or not known, 'nonce': member['nonce']})
    if view.legacy_marker is not None:
        # While an old-code job holds heavy.lock exclusively the marker is its live record;
        # only a marker nobody holds is an unverified-cleanup quarantine.
        rows.append({'class': 'heavy', 'memory': policy.single_job_bytes(physical), 'disk': 0,
                     'device': None, 'quarantined': not view.legacy_active, 'nonce': 'legacy-heavy.active.json'})
    return rows


def _occupancy(rows: list[dict], mode: PoolMode, lane: str) -> list[dict]:
    """Rows that consume the capacity this request needs."""
    if mode.exclusive:
        return rows
    return [row for row in rows if row['class'] in (lane, '*')]


def _disk_free(path: str) -> tuple[int, int]:
    """Return the filesystem device and live free bytes for a real directory."""
    return os.stat(path).st_dev, shutil.disk_usage(path).free


def _fifo_reasons(view: state.PoolView, request: PoolRequest, key: str, modes: tuple) -> list[str]:
    """Only the earliest live ticket competing for the same capacity may be admitted."""
    session, committed = modes
    ahead = 0
    for ticket in view.tickets:
        record = ticket['record'] or {}
        if ticket['sequence'] >= request.ticket.sequence or record.get('class') not in POOL_CLASSES:
            continue
        mode = request_mode(session, committed, record)
        ahead += policy.queue_key(mode, record['class']) == key
    return [f'queued behind {ahead} earlier request(s)'] if ahead else []


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


def _disk_reasons(decision: Decision, rows: list[dict], request: PoolRequest) -> None:
    """Other members' disk reservations on the same filesystem are already spent."""
    decision.device, free = _disk_free(request.root or request.project)
    same = [row for row in rows if row['device'] == decision.device]
    others = sum(row['disk'] for row in same)
    quarantined = sum(row['disk'] for row in same if row['quarantined'])
    decision.context.update(diskFreeBytes=free, diskReservedByOthersBytes=others)
    if free - quarantined < decision.disk + DISK_RESERVE_BYTES:
        decision.terminal.append('disk headroom for output and OS swap is below policy after reservations')
    elif free - others < decision.disk + DISK_RESERVE_BYTES:
        decision.reasons.append('disk headroom is reserved by running members')


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


def decide(view: state.PoolView, request: PoolRequest, host: dict, committed: PoolMode) -> Decision:
    """Apply queue order, slots, aggregate memory and shared disk to one request."""
    physical = host['memsizeBytes']
    session = _session(view, host)
    row = {'project': request.project, 'root': request.root}
    mode = request_mode(session, committed, row)
    decision = Decision(mode, policy.reservation_bytes(mode, request.lane, physical, request.fixed_owned_gib),
                        request.disk_bytes if request.disk_bytes is not None
                        else DISK_RESERVATION_BYTES[request.lane], 0)
    rows = _member_charges(view, physical)
    if session and mode is committed:
        decision.reasons.append('a pool qualification session is running its declared jobs')
    if view.legacy_active:
        decision.reasons.append('legacy exclusive heavy work is running')
    _slot_reasons(decision, rows, request.lane)
    _memory_reasons(decision, rows, physical)
    _disk_reasons(decision, rows, request)
    decision.reasons += _fifo_reasons(view, request, policy.queue_key(mode, request.lane),
                                      (session, committed))
    return decision


def _pruned_summary(row: dict) -> dict:
    """Keep exact pruning evidence (which ticket/session, whose identity) for receipts."""
    record = row.get('ticket') and (row.get('record') or {})
    return {'ticket': row.get('ticket'), 'session': bool(row.get('session')), 'reason': row['reason'],
            'waiterIdentityLive': row.get('waiterIdentityLive'),
            'waiter': record.get('supervisor') if isinstance(record, dict) else None}


def _refusal(lane: str, decision: Decision) -> NativeWorkQueued | NativeWorkQuarantined:
    """Keep legacy wording: only 'already active' refusals are worth waiting for."""
    if decision.terminal:
        return NativeWorkQuarantined(f'Native {lane} cleanup is unverified or capacity is quarantined: '
                                     + '; '.join(decision.terminal)
                                     + '; inspect and recover with native_work_recovery.py <nonce>')
    return NativeWorkQueued(f'Native {lane} work is already active: ' + '; '.join(decision.reasons))


def _transact(lane: str, request: PoolRequest, host: dict, committed: PoolMode) -> object:
    """One ledger transaction: observe, enqueue once, decide, then admit or refuse."""
    with state.ledger(time.monotonic() + state.LEDGER_WAIT_SECONDS) as namespace:
        view = observe(namespace)
        request.attempts += 1
        if request.ticket is None:
            request.ticket = enqueue(namespace, view, request)
            request.sequence = request.ticket.sequence
        decision = decide(view, request, host, committed)
        decision.context['pruned'] = [_pruned_summary(row) for row in view.pruned]
        if decision.terminal or decision.reasons:
            raise _refusal(lane, decision)
        return install(namespace, request, decision)


def admit(lane: str, project: str, request: PoolRequest | None = None) -> object:
    """Admit one member now or raise; a supplied request keeps its ticket on refusal."""
    transient = request is None
    request = request or PoolRequest(lane, project)
    if request.lane != lane or request.project != str(Path(project).resolve()):
        raise ValueError('Pool request does not match the requested class and project')
    host = policy.host_identity()
    try:
        return _transact(lane, request, host, qualification.committed_mode(host))
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
    try:
        lease = _attempt(lane, project, request, until)
        while lease is None:
            time.sleep(min(1.0, max(0.0, until - time.monotonic())))
            lease = _attempt(lane, project, request, until)
        return lease
    finally:
        request.withdraw()
