"""FIFO tickets and admitted pool members with durable cleanup obligations.

A member holds its own kernel lock (m-<nonce>.lock) and a shared lock on the legacy
heavy.lock for its whole lifetime. complete() clears the record only after every
recorded identity is absent; close() without it leaves the record, which then counts
as a quarantined slot with its memory and disk reservations until explicit recovery.
Phases: 'admitted' (declared owner, nothing launched yet), 'launching' (a child may
exist) and 'launch-state-unknown' (caller never declared its launches).
"""
from __future__ import annotations

import fcntl
import json
import os
import subprocess
import time
import uuid
from dataclasses import dataclass

import native_work_lease as lease_module
import native_work_pool_state as state
from headless.durable_files import assert_private_lock_identity, open_private_file, write_all
from native_render_processes import process_table
from native_work_pool_policy import LAYOUT

_IDENTITY: dict[int, dict] = {}


def own_identity() -> dict:
    """Return this supervisor's exact pid/start/group identity (cached per process)."""
    pid = os.getpid()
    if pid not in _IDENTITY:
        output = subprocess.run(['/bin/ps', '-p', str(pid), '-o', 'pid=,ppid=,pgid=,lstart='],
                                check=True, capture_output=True, text=True, timeout=3)
        _parent, group, started = process_table(output.stdout)[pid]
        _IDENTITY[pid] = {'pid': pid, 'pgid': group, 'started': started}
    return dict(_IDENTITY[pid])


@dataclass
class Ticket:
    """A queued request; holding its flock is what keeps its FIFO position."""

    name: str
    sequence: int
    nonce: str
    fd: int

    def withdraw(self) -> None:
        """Release the ticket lock; the next transaction prunes the unheld file."""
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1


def enqueue(namespace: state.Namespace, view: state.PoolView, request: object) -> Ticket:
    """Publish and lock one ticket inside the current ledger transaction."""
    sequence, nonce = state.next_ticket(namespace, view), uuid.uuid4().hex
    name = f't-{sequence:012d}-{nonce}.json'
    record = {'schemaVersion': 1, 'layout': LAYOUT, 'nonce': nonce, 'sequence': sequence,
              'class': request.lane, 'project': request.project, 'root': request.root,
              'receipt': request.receipt, 'supervisor': own_identity(), 'enqueuedAt': time.time()}
    fd = open_private_file(namespace.pool_fd, name, os.O_CREAT | os.O_EXCL | os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        write_all(fd, (json.dumps(record, sort_keys=True) + '\n').encode())
        os.fsync(fd)
        os.fsync(namespace.pool_fd)
    except BaseException:
        os.close(fd)
        os.unlink(name, dir_fd=namespace.pool_fd)
        raise
    view.tickets.append({'name': name, 'sequence': sequence, 'nonce': nonce, 'record': record})
    return Ticket(name, sequence, nonce, fd)


def _legacy_shared(namespace: state.Namespace) -> int:
    """Hold the legacy heavy.lock shared so old-code exclusive work cannot start."""
    fd = open_private_file(namespace.root_fd, state.LEGACY_LOCK, os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        assert_private_lock_identity(namespace.root_fd, state.LEGACY_LOCK, fd)
        os.utime(fd)
    except BlockingIOError:
        os.close(fd)
        raise state.NativeWorkQueued('Native heavy work is already active: legacy exclusive work started') from None
    except BaseException:
        os.close(fd)
        raise
    return fd


def _record(request: object, decision: object, nonce: str) -> dict:
    """Describe one member exactly as recovery and later admissions will read it."""
    now = time.time()
    return {'schemaVersion': 1, 'layout': LAYOUT, 'nonce': nonce, 'class': request.lane,
            'mode': decision.mode.name, 'modeRecord': decision.mode.record,
            'supervisor': own_identity(), 'supervisorPid': os.getpid(),
            'project': request.project, 'root': request.root, 'receipt': request.receipt,
            'reservationBytes': decision.reservation, 'diskReservationBytes': decision.disk,
            'diskDevice': decision.device, 'ticket': request.ticket.sequence,
            'admittedAt': now, 'startedAt': now,
            'phase': 'admitted' if request.declares_launch else 'launch-state-unknown',
            'processes': []}


def install(namespace: state.Namespace, request: object, decision: object) -> PoolLease:
    """Take the legacy fence and member lock, publish the record, consume the ticket."""
    member = state.reopen_pool(namespace)
    held: list[int] = []
    nonce = uuid.uuid4().hex
    try:
        held.append(_legacy_shared(member))
        lock = open_private_file(member.pool_fd, f'm-{nonce}.lock', os.O_CREAT | os.O_EXCL | os.O_RDWR)
        held.append(lock)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        record = _record(request, decision, nonce)
        state.publish(member.pool_fd, f'm-{nonce}.json', record)
        os.unlink(request.ticket.name, dir_fd=namespace.pool_fd)
    except BaseException:
        _abandon(member, held, nonce)
        raise
    request.ticket.withdraw()
    request.ticket = None
    return PoolLease(member, (held[1], held[0]), record, decision.context)


def _abandon(member: state.Namespace, held: list[int], nonce: str) -> None:
    """Undo a partial admission; no child can exist before the record is returned."""
    for name in (f'm-{nonce}.json', f'm-{nonce}.lock'):
        try:
            os.unlink(name, dir_fd=member.pool_fd)
        except FileNotFoundError:
            pass
    for fd in held:
        os.close(fd)
    member.close()


class PoolLease:
    """One admitted member; API-compatible with the legacy NativeWorkLease."""

    def __init__(self, namespace: state.Namespace, descriptors: tuple[int, int], record: dict,
                 context: dict) -> None:
        """Bind descriptors acquired by install(); never constructed elsewhere."""
        self.namespace = namespace
        self.lock_fd, self.legacy_fd = descriptors
        self.record, self.lane = record, record['class']
        self.nonce = record['nonce']
        self.closed = self.completed = False
        self.reservation_bytes = record['reservationBytes']
        self.disk_reservation_bytes = record['diskReservationBytes']
        self.admission = {'layout': LAYOUT, 'member': self.nonce, 'class': self.lane,
                          'mode': record['mode'], 'modeRecord': record['modeRecord'],
                          'reservationBytes': self.reservation_bytes,
                          'diskReservationBytes': self.disk_reservation_bytes,
                          'ticket': record['ticket'], 'admittedAtEpoch': record['admittedAt'],
                          'loadAverage': list(os.getloadavg()), **context}

    @property
    def marker(self) -> str:
        """Name of this member's durable record."""
        return f'm-{self.nonce}.json'

    def _assert_owner(self) -> None:
        """Recheck namespace, lock inode and exact record before state changes."""
        if self.closed or self.completed:
            raise RuntimeError('Native work lease is no longer active')
        if os.getpid() != self.record['supervisorPid']:
            raise RuntimeError('Native work lease belongs to another supervisor')
        state.assert_namespace(self.namespace)
        assert_private_lock_identity(self.namespace.pool_fd, f'm-{self.nonce}.lock', self.lock_fd)
        if json.loads(state.read_private_file(self.namespace.pool_fd, self.marker)) != self.record:
            raise RuntimeError('Native work ownership record changed')

    def _write(self, record: dict) -> None:
        """Publish an updated record and adopt it only after it is durable."""
        state.publish(self.namespace.pool_fd, self.marker, record)
        self.record = record

    def record_processes(self, identities: list[dict]) -> None:
        """Retain all identities ever observed, including reparented children."""
        self._assert_owner()
        if not isinstance(identities, list) or len(identities) > 4096:
            raise ValueError('Native process registry must be a bounded list')
        rows = dict((json.dumps(row, sort_keys=True), row) for row in self.record['processes'])
        for row in identities:
            lease_module.NativeWorkLease._validate_identity(row)
            rows[json.dumps(row, sort_keys=True)] = dict(row)
        if len(rows) > 4096:
            raise ValueError('Native process registry exceeds its bound')
        self._write(dict(self.record, processes=list(rows.values())))

    def mark_launching(self) -> None:
        """Declare durably that a child may exist from now on (before spawning it)."""
        self._assert_owner()
        if self.record['phase'] == 'admitted':
            self._write(dict(self.record, phase='launching'))

    def legacy_fence_intact(self) -> bool:
        """Whether the shared legacy lock is still the named heavy.lock inode."""
        try:
            assert_private_lock_identity(self.namespace.root_fd, state.LEGACY_LOCK, self.legacy_fd)
        except state.DurableFileError:
            return False
        return True

    def complete(self) -> None:
        """Release the slot and reservations only after recorded identities are absent."""
        self._assert_owner()
        live = lease_module._live_identities(self.record['processes'])
        if live:
            raise RuntimeError(f'Native cleanup still has live recorded processes: {live}')
        with state.ledger(time.monotonic() + state.LEDGER_WAIT_SECONDS) as namespace:
            self._assert_owner()
            archived = dict(self.record, cleanupVerified=True, completedAt=time.time(),
                            legacyFenceIntact=self.legacy_fence_intact())
            state.publish(namespace.pool_fd, f'last-{self.lane}.json', archived)
            os.unlink(self.marker, dir_fd=namespace.pool_fd)
            os.unlink(f'm-{self.nonce}.lock', dir_fd=namespace.pool_fd)
            os.fsync(namespace.pool_fd)
        self.completed = True

    def close(self) -> None:
        """Release descriptors; an uncompleted record stays as a quarantined slot."""
        if self.closed:
            return
        self.closed = True
        os.close(self.lock_fd)
        os.close(self.legacy_fd)
        self.namespace.close()
