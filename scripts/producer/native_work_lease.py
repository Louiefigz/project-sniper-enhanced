"""Host-wide native job exclusion with durable unverified-cleanup fencing.

The supervisor owns lifecycle actions. Closing a lease does not assert cleanup;
only complete() clears its active marker after recorded identities are absent.
All checkouts use the same private per-user namespace, not a per-project lock.
"""
from __future__ import annotations

import fcntl
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

from headless.durable_files import (
    _assert_root_identity, assert_private_lock_identity, open_private_dir, open_private_file,
    read_private_file, write_pending_replace,
)
from native_render_processes import ProcessIdentity, identity_matches, process_table


class NativeWorkBusy(RuntimeError):
    """Another job is active or a previous job has unverified cleanup."""


def state_root() -> Path:
    """Return one host-local namespace shared by every checkout for this user."""
    parent = Path('/private/tmp') if Path('/private/tmp').is_dir() else Path('/tmp')
    return parent / f'sniper-native-work-{os.geteuid()}'


def _open_root() -> tuple[Path, int]:
    """Create a private directory without adopting unsafe pre-existing entries."""
    root = state_root()
    root.mkdir(mode=0o700, exist_ok=True)
    return root, open_private_dir(str(root))


def _live_identities(identities: list[dict]) -> list[int]:
    """Recheck registered identities; a recycled PID is not the old process."""
    if not identities:
        return []
    output = subprocess.run(['/bin/ps', '-axo', 'pid=,ppid=,pgid=,lstart='],
                            check=True, capture_output=True, text=True, timeout=3)
    table = process_table(output.stdout)
    return [row['pid'] for row in identities
            if identity_matches(table, ProcessIdentity(**row))]


class NativeWorkLease:
    """One never-unlinked kernel lock plus a durable cleanup obligation."""

    def __init__(self, descriptors: tuple[int, int], lane: str, record: dict) -> None:
        """Bind descriptors already exclusively acquired by acquire()."""
        self.dir_fd, self.lock_fd = descriptors
        self.lane, self.record = lane, record
        self.closed = False
        self.completed = False
        self.root = state_root()

    @classmethod
    def acquire(cls, lane: str, project: str) -> NativeWorkLease:
        """Refuse concurrent work immediately; never reclaim an active marker."""
        if lane not in {'heavy', 'preview-control'}:
            raise ValueError('Unknown native work lane')
        _root, directory = _open_root()
        lock = None
        try:
            lock = open_private_file(directory, lane + '.lock', os.O_CREAT | os.O_RDWR)
            cls._lock(directory, lock, lane)
            _assert_root_identity(str(_root), directory)
            record = {'schemaVersion': 1, 'nonce': uuid.uuid4().hex,
                      'supervisorPid': os.getpid(), 'project': str(Path(project).resolve()),
                      'startedAt': time.time(), 'processes': []}
            lease = cls((directory, lock), lane, record)
            lease._write(record)
            return lease
        except BaseException:
            if lock is not None:
                os.close(lock)
            os.close(directory)
            raise

    @staticmethod
    def _lock(directory: int, lock: int, lane: str) -> None:
        """Check marker existence only after acquiring the original lock inode."""
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise NativeWorkBusy(f'Native {lane} work is already active') from error
        assert_private_lock_identity(directory, lane + '.lock', lock)
        try:
            os.stat(lane + '.active.json', dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            return
        raise NativeWorkBusy(f'Native {lane} cleanup is unverified; inspect its active record')

    def _assert_owner(self) -> None:
        """Recheck the exact held inode and active nonce before state changes."""
        if self.closed or self.completed:
            raise RuntimeError('Native work lease is no longer active')
        if os.getpid() != self.record['supervisorPid']:
            raise RuntimeError('Native work lease belongs to another supervisor')
        _assert_root_identity(str(self.root), self.dir_fd)
        assert_private_lock_identity(self.dir_fd, self.lane + '.lock', self.lock_fd)
        active = json.loads(read_private_file(self.dir_fd, self.lane + '.active.json'))
        if active != self.record:
            raise RuntimeError('Native work ownership record changed')

    def _write(self, record: dict) -> None:
        """Publish through the existing durable private-file primitive."""
        names = (self.lane + '.pending.json', self.lane + '.active.json')
        data = (json.dumps(record, sort_keys=True) + '\n').encode()
        write_pending_replace(self.dir_fd, names, data)

    def record_processes(self, identities: list[dict]) -> None:
        """Retain all identities ever observed, including reparented children."""
        self._assert_owner()
        if not isinstance(identities, list) or len(identities) > 4096:
            raise ValueError('Native process registry must be a bounded list')
        rows = dict((json.dumps(row, sort_keys=True), row) for row in self.record['processes'])
        for row in identities:
            self._validate_identity(row)
            rows[json.dumps(row, sort_keys=True)] = dict(row)
        if len(rows) > 4096:
            raise ValueError('Native process registry exceeds its bound')
        updated = dict(self.record, processes=list(rows.values()))
        self._write(updated)
        self.record = updated

    @staticmethod
    def _validate_identity(row: dict) -> None:
        """Require exact PID/start/group fields before accepting cleanup pins."""
        if not isinstance(row, dict) or set(row) != {'pid', 'started', 'pgid'}:
            raise ValueError('Native identity requires pid, started and pgid')
        if any(type(row[key]) is not int or row[key] <= 1 for key in ('pid', 'pgid')):
            raise ValueError('Native process identifiers must be positive integers')
        if not isinstance(row['started'], str) or not row['started'].strip():
            raise ValueError('Native identity requires its exact process start time')

    def complete(self) -> None:
        """Clear this obligation only after every recorded identity is absent."""
        self._assert_owner()
        live = _live_identities(self.record['processes'])
        if live:
            raise RuntimeError(f'Native cleanup still has live recorded processes: {live}')
        self._assert_owner()
        archived = dict(self.record, cleanupVerified=True, completedAt=time.time())
        names = (self.lane + '.completed.pending.json', self.lane + '.completed.json')
        write_pending_replace(self.dir_fd, names, (json.dumps(archived) + '\n').encode())
        os.unlink(self.lane + '.active.json', dir_fd=self.dir_fd)
        os.fsync(self.dir_fd)
        self.completed = True

    def close(self) -> None:
        """Release descriptors; preserve an unfinished obligation after failure."""
        if self.closed:
            return
        self.closed = True
        os.close(self.lock_fd)
        os.close(self.dir_fd)
