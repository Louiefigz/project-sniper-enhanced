"""The host-wide native pool as batch status reads it: members, waiting tickets and reservations by class.

Liveness is the admission's own evidence, read the same way without its ledger lock: a member is
``live`` while its supervisor holds ``m-<nonce>.lock`` and ``quarantined`` otherwise (a member closed
without completing keeps its slot until ``native_work_recovery.py <nonce>`` verifies its exit), and a
ticket is waiting while its waiter holds the ticket file. Each lock is tested with one non-blocking
shared probe that is released at once; nothing is created, written, pruned or locked for longer. The
recorded supervisor identity in the process table is secondary evidence reported beside it (a start
time recorded under another time zone does not match, so it never decides liveness).

A ticket is probed only after its record reads as JSON: the waiter takes its lock before writing the
record, so a probe never meets a ticket still being enqueued. Members are published after their lock
is taken. What remains: while a probe holds a free lock (microseconds), admission sees that quarantined
member as live and a concurrent recovery of it is refused (it can be retried). A host with no pool
state reports ``no-pool-state``. The pool is shared with other work.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

RECOVER = 'native_work_recovery.py {nonce}'


def _entry(reader: object, fd: int, name: str) -> dict | None:
    """One pool record, or None when it cannot be read (charged maximally, as admission does)."""
    try:
        value = json.loads(reader(fd, name))
    except (OSError, RuntimeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _lock(fd: int, name: str) -> str:
    """'held', 'free' or 'missing' from one non-blocking shared probe; 'unreadable' when it cannot be opened."""
    from native_work_pool_state import probe
    try:
        return probe(fd, name, shared=True)
    except (OSError, RuntimeError) as error:
        return 'missing' if isinstance(error.__cause__ or error, FileNotFoundError) else 'unreadable'


def _in_table(table: dict, record: dict | None) -> bool | None:
    """Whether the recorded supervisor identity is in the process table (None when none is recorded)."""
    from native_render_processes import ProcessIdentity, identity_matches
    supervisor = (record or {}).get('supervisor')
    if not isinstance(supervisor, dict) or set(supervisor) != {'pid', 'pgid', 'started'}:
        return None
    return identity_matches(table, ProcessIdentity(**supervisor))


def _entries(fd: int, table: dict) -> tuple[list[dict], list[dict]]:
    """Members classified by their liveness lock and tickets with their waiter's lock, from one listing."""
    from headless.durable_files import bounded_directory_entries, read_private_file
    from native_work_pool_state import ENTRY_LIMIT, MEMBER, TICKET
    members, tickets = [], []
    for name in bounded_directory_entries(fd, ENTRY_LIMIT):
        member, ticket = MEMBER.fullmatch(name), TICKET.fullmatch(name)
        if not (member or ticket):
            continue
        record = _entry(read_private_file, fd, name)
        if member:
            lock = _lock(fd, f'm-{member[1]}.lock')
            members.append({'name': name, 'nonce': member[1], 'record': record, 'lock': lock,
                            'state': 'live' if lock == 'held' else 'quarantined',
                            'supervisorInProcessTable': _in_table(table, record)})
            continue
        lock = _lock(fd, name) if record is not None else 'not-probed (record unreadable)'
        tickets.append({'name': name, 'record': record, 'lock': lock})
    return members, tickets


def _by_class(charges: list[dict], tickets: list[dict]) -> dict:
    """Live, quarantined and waiting counts per pool class."""
    waiting = [(row['record'] or {}).get('class') or '*' for row in tickets if row['lock'] == 'held']
    return {lane: {'live': sum(row['class'] == lane and not row['quarantined'] for row in charges),
                   'quarantined': sum(row['class'] == lane and row['quarantined'] for row in charges),
                   'waiting': waiting.count(lane)}
            for lane in sorted({row['class'] for row in charges} | set(waiting))}


def _quarantined(members: list[dict], charges: list[dict]) -> list[dict]:
    """Every quarantined member with its lock, the secondary process-table evidence and its recovery command."""
    by_nonce = {row['nonce']: row for row in members}
    return [{'nonce': row['nonce'], 'class': row['class'], 'lock': by_nonce[row['nonce']]['lock'],
             'supervisorInProcessTable': by_nonce[row['nonce']]['supervisorInProcessTable'],
             'recover': RECOVER.format(nonce=row['nonce'])} for row in charges if row['quarantined']]


def _read(pool: Path) -> tuple[list[dict], list[dict]]:
    """Members and tickets of the pool directory, then close it."""
    from headless.durable_files import open_private_dir
    from native_work_pool_recovery import process_snapshot
    table = process_snapshot()
    fd = open_private_dir(str(pool))
    try:
        return _entries(fd, table)
    finally:
        os.close(fd)


def pool_snapshot() -> dict:
    """Host-wide pool members, waiting tickets and reservations by class, read only (no writes, no ledger lock)."""
    import native_work_lease as lease
    from native_work_pool import _member_charges
    from native_work_pool_policy import aggregate_bytes, host_identity
    from native_work_pool_state import LEGACY_MARKER, POOL_DIR, PoolView
    pool = lease.state_root() / POOL_DIR
    if not pool.is_dir():
        return {'status': 'no-pool-state', 'reason': f'{pool} does not exist: no native pool work has run here'}
    members, tickets = _read(pool.resolve())
    physical = host_identity()['memsizeBytes']
    charges = _member_charges(PoolView(members=members), physical)
    disks: dict[str, int] = {}  # keys: src's disk spaces (native_work_pool_disk; '*' = every space)
    for row in charges:
        for space, size in (row['spaces'] if row['spaces'] is not None else {'unknown': 0}).items():
            disks[space] = disks.get(space, 0) + size
    budget, charged = aggregate_bytes(physical), sum(row['memory'] for row in charges)
    return {'status': 'observed', 'consistency': 'read-only, unlocked snapshot; liveness from shared lock probes',
            'byClass': _by_class(charges, tickets), 'legacyMarker': (pool.parent / LEGACY_MARKER).exists(),
            'staleTickets': sum(row['lock'] != 'held' for row in tickets),
            'liveWithoutProcessTableMatch': sum(row['state'] == 'live' and row['supervisorInProcessTable'] is not True
                                                for row in members),
            'memory': {'aggregateBudgetBytes': budget, 'reservedBytes': charged, 'headroomBytes': budget - charged},
            'diskReservedBytesByDevice': disks, 'quarantinedMembers': _quarantined(members, charges)}
