"""Exact observation of pool state inside one ledger transaction.

Members are classified by their kernel liveness lock (held = live, otherwise
quarantined); tickets nobody holds are pruned with the waiter's recorded identity as
evidence; a session counts only while the harness holds its lock; an old-code
exclusive holder of heavy.lock and an old heavy.active.json are reported as legacy
fences. Every transaction also refreshes live files against macOS tmp_cleaner.
"""
from __future__ import annotations

import fcntl
import os

import native_work_lease as lease_module
from headless.durable_files import DurableFileError, bounded_directory_entries, open_private_file
from native_work_pool_state import (
    ENTRY_LIMIT, LEGACY_LOCK, LEGACY_MARKER, MEMBER, SESSION, SESSION_LOCK, TICKET, Namespace, PoolView,
    _exists, probe, read_json, refresh,
)


def _members(namespace: Namespace, names: tuple[str, ...]) -> list:
    """Classify every member record by its kernel liveness lock."""
    members = []
    for name in names:
        match = MEMBER.fullmatch(name)
        if match is None:
            continue
        lock = probe(namespace.pool_fd, f'm-{match[1]}.lock')
        members.append({'name': name, 'nonce': match[1], 'state': 'live' if lock == 'held' else 'quarantined',
                        'lock': lock, 'record': _member_record(namespace.pool_fd, name)})
    return members


def _member_record(directory: int, name: str) -> dict | None:
    """Return a readable record; malformed records stay charged as unknown."""
    try:
        value = read_json(directory, name)
    except (DurableFileError, OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _tickets(namespace: Namespace, names: tuple[str, ...], view: PoolView) -> None:
    """Keep waiters holding their ticket locks; prune tickets nobody holds."""
    for name in names:
        match = TICKET.fullmatch(name)
        if match is None:
            continue
        if probe(namespace.pool_fd, name) == 'held':
            view.tickets.append({'name': name, 'sequence': int(match[1]), 'nonce': match[2],
                                 'record': _member_record(namespace.pool_fd, name)})
            continue
        record = _member_record(namespace.pool_fd, name)
        view.pruned.append({'ticket': name, 'record': record, 'waiterIdentityLive': _identity_live(record),
                            'reason': 'ticket lock released: its waiter exited or withdrew'})
        os.unlink(name, dir_fd=namespace.pool_fd)


def _identity_live(record: dict | None) -> bool | None:
    """Report whether the recorded waiter identity still exists (evidence only)."""
    supervisor = (record or {}).get('supervisor')
    if not isinstance(supervisor, dict) or set(supervisor) != {'pid', 'started', 'pgid'}:
        return None
    return bool(lease_module._live_identities([supervisor]))


def _orphan_locks(namespace: Namespace, names: tuple[str, ...]) -> None:
    """Remove member locks whose record was never published (crash during admission)."""
    for name in names:
        if name.startswith('m-') and name.endswith('.lock') and name[:-5] + '.json' not in names \
                and probe(namespace.pool_fd, name) == 'free':
            os.unlink(name, dir_fd=namespace.pool_fd)


def _legacy(namespace: Namespace, view: PoolView) -> None:
    """Treat an old-code exclusive holder as occupying all pool capacity."""
    lock = open_private_file(namespace.root_fd, LEGACY_LOCK, os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except BlockingIOError:
        view.legacy_active = True
    finally:
        os.close(lock)
    if _exists(namespace.root_fd, LEGACY_MARKER):
        view.legacy_marker = _legacy_marker(namespace.root_fd)


def _legacy_marker(directory: int) -> dict:
    """Summarize an old-code cleanup obligation; a malformed one is still a fence."""
    try:
        value = read_json(directory, LEGACY_MARKER)
    except (DurableFileError, OSError, ValueError):
        return {'malformed': True}
    if not isinstance(value, dict):
        return {'malformed': True}
    return {'malformed': False, 'nonce': value.get('nonce'), 'supervisorPid': value.get('supervisorPid'),
            'project': value.get('project'), 'processCount': len(value.get('processes') or [])}


def _session(namespace: Namespace, view: PoolView) -> None:
    """Expose a session only while its harness holds the session lock."""
    if not _exists(namespace.pool_fd, SESSION):
        return
    if probe(namespace.pool_fd, SESSION_LOCK) == 'held':
        view.session = _member_record(namespace.pool_fd, SESSION) or {'malformed': True}
        return
    view.pruned.append({'session': _member_record(namespace.pool_fd, SESSION),
                        'reason': 'session lock released: harness exited'})
    os.unlink(SESSION, dir_fd=namespace.pool_fd)


def observe(namespace: Namespace) -> PoolView:
    """Read members, live tickets, legacy fences and the session under the ledger lock."""
    view = PoolView()
    names = bounded_directory_entries(namespace.pool_fd, ENTRY_LIMIT)
    view.members = _members(namespace, names)
    _tickets(namespace, names, view)
    _orphan_locks(namespace, names)
    _session(namespace, view)
    _legacy(namespace, view)
    live = [name for name in bounded_directory_entries(namespace.pool_fd, ENTRY_LIMIT)
            if not name.endswith('.pending.json') and not name.startswith(('recovery-', 'last-'))]
    refresh(namespace.pool_fd, live)
    refresh(namespace.root_fd, [LEGACY_LOCK, LEGACY_MARKER])
    return view
