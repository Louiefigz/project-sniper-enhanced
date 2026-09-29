"""Qualification sessions: the harness runs its declared jobs under a candidate size.

A session exists only while the harness process holds session.lock; the pool prunes a
session record whose lock is free, so a crashed harness can never leave a larger pool
behind. The harness opens a session only on an idle pool (no members, live tickets,
legacy work or legacy marker) so measurements are not shared with unrelated work, and
while it is open every undeclared request waits.
"""
from __future__ import annotations

import fcntl
import os
import time
import uuid
from dataclasses import dataclass

import native_work_pool_policy as policy
import native_work_pool_state as state
from headless.durable_files import open_private_file
from native_work_pool_lease import own_identity
from native_work_pool_observe import observe
from native_work_qualification import SESSION_KIND, validate_session


@dataclass
class Session:
    """A live session; closing it removes the record and releases the lock."""

    fd: int
    value: dict

    def close(self) -> None:
        """Remove this session's record (if still ours) and release its lock."""
        if self.fd < 0:
            return
        try:
            _remove_record(self.value['nonce'])
        finally:
            os.close(self.fd)
            self.fd = -1


def _remove_record(nonce: str) -> None:
    """Delete the session record only when it is still this session's."""
    with state.ledger(time.monotonic() + state.LEDGER_WAIT_SECONDS) as namespace:
        path = os.path.join(namespace.pool, state.SESSION)
        current = state.read_json(namespace.pool_fd, state.SESSION) if os.path.lexists(path) else None
        if isinstance(current, dict) and current.get('nonce') == nonce:
            os.unlink(state.SESSION, dir_fd=namespace.pool_fd)


def _idle_reasons(view: state.PoolView) -> list[str]:
    """Anything that would share or distort the qualification measurement."""
    reasons = [f'{len(view.members)} pool member(s) present'] if view.members else []
    reasons += [f'{len(view.tickets)} queued request(s)'] if view.tickets else []
    reasons += ['another qualification session is live'] if view.session is not None else []
    reasons += ['legacy exclusive heavy work is running'] if view.legacy_active else []
    reasons += ['a legacy heavy.active.json obligation exists'] if view.legacy_marker else []
    return reasons


def open_session(configuration: dict, jobs: list[dict], expires_in: float) -> Session:
    """Publish and lock one validated session on an idle pool.

    Args:
        configuration: {'heavySlots': N, 'audioSlots': M} candidate being qualified.
        jobs: Declared {'project', 'attempt'} canonical path pairs.
        expires_in: Seconds until the session is void even if its lock were still held.

    Returns:
        The live session, to be closed by the harness.
    """
    host = policy.host_identity()
    now = time.time()
    value = {'schemaVersion': 1, 'kind': SESSION_KIND, 'nonce': uuid.uuid4().hex, 'host': host,
             'configuration': configuration, 'jobs': jobs, 'harness': own_identity(),
             'createdAt': now, 'expiresAtEpoch': now + expires_in}
    validate_session(value, host, now)
    with state.ledger(time.monotonic() + state.LEDGER_WAIT_SECONDS) as namespace:
        reasons = _idle_reasons(observe(namespace))
        if reasons:
            raise RuntimeError('Pool qualification requires an idle pool: ' + '; '.join(reasons))
        fd = open_private_file(namespace.pool_fd, state.SESSION_LOCK, os.O_CREAT | os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            state.publish(namespace.pool_fd, state.SESSION, value)
        except BaseException:
            os.close(fd)
            raise
    return Session(fd, value)
