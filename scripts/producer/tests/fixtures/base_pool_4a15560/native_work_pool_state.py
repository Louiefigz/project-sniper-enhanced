"""Private pool namespace, bounded ledger lock and exact observation of pool state.

Layout, versioned and never read by the legacy lease code: <state_root>/pool-v1/
  ledger.lock           host-wide mutex held only during short transactions
  counter.json          monotonic FIFO ticket sequence
  m-<nonce>.json        member record: live while m-<nonce>.lock is held, else quarantined
  m-<nonce>.lock        member liveness lock held by its supervisor (released by the kernel)
  t-<seq>-<nonce>.json  FIFO ticket; the waiter's own flock on it proves it still waits
  session.json/.lock    qualification session, valid only while the harness holds the lock
The legacy <state_root>/heavy.lock is held shared by every member, so an old-code job
(exclusive flock) and pool members exclude each other; a legacy heavy.active.json is
a quarantined heavy slot. macOS tmp_cleaner deletes /tmp files whose access, change
and modification times are all older than three days, so every transaction refreshes
the live pool files, the legacy lock and a legacy marker; unused state can still age out.
Observation lives in native_work_pool_observe.py.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Iterator

import native_work_lease as lease_module
from headless.durable_files import (  # noqa: F401  DurableFileError/read_private_file are re-exported
    DurableFileError, _assert_root_identity, assert_private_lock_identity, open_private_child_dir,
    open_private_dir, open_private_file, private_child_dir, read_private_file, write_pending_replace,
)
from native_work_lease import NativeWorkBusy

POOL_DIR = 'pool-v1'
LEDGER_LOCK = 'ledger.lock'
COUNTER = 'counter.json'
SESSION, SESSION_LOCK = 'session.json', 'session.lock'
LEGACY_LOCK, LEGACY_MARKER = 'heavy.lock', 'heavy.active.json'
LEDGER_WAIT_SECONDS = 10.0
ENTRY_LIMIT = 4096
MEMBER = re.compile(r'm-([0-9a-f]{32})\.json')
TICKET = re.compile(r't-([0-9]{12})-([0-9a-f]{32})\.json')


class NativeWorkQueued(NativeWorkBusy):
    """Waiting can help: live work, earlier tickets or live reservations block admission."""


class NativeWorkQuarantined(NativeWorkBusy):
    """Waiting cannot help: quarantined or legacy obligations exhaust the capacity."""


@dataclass
class Namespace:
    """Open descriptors for the canonical state root and its pool directory."""

    root_fd: int
    pool_fd: int
    root: str
    pool: str

    def close(self) -> None:
        """Release both directory descriptors."""
        os.close(self.pool_fd)
        os.close(self.root_fd)


@dataclass
class PoolView:
    """One consistent snapshot taken while the ledger lock is held."""

    members: list = field(default_factory=list)
    tickets: list = field(default_factory=list)
    pruned: list = field(default_factory=list)
    legacy_active: bool = False
    legacy_marker: dict | None = None
    session: dict | None = None


def open_namespace() -> Namespace:
    """Create or reopen the private root and pool directories without adopting links."""
    root = lease_module.state_root()
    root.mkdir(mode=0o700, exist_ok=True)
    root_fd = open_private_dir(str(root))
    try:
        pool_fd = private_child_dir(root_fd, POOL_DIR)
    except BaseException:
        os.close(root_fd)
        raise
    return Namespace(root_fd, pool_fd, str(root), str(root / POOL_DIR))


def assert_namespace(namespace: Namespace) -> None:
    """Refuse a replaced root or pool directory before trusting any state."""
    _assert_root_identity(namespace.root, namespace.root_fd)
    _assert_root_identity(namespace.pool, namespace.pool_fd)


def reopen_pool(namespace: Namespace) -> Namespace:
    """Duplicate the verified directories for a long-lived member handle."""
    root_fd = open_private_dir(namespace.root)
    try:
        pool_fd = open_private_child_dir(root_fd, POOL_DIR)
    except BaseException:
        os.close(root_fd)
        raise
    return Namespace(root_fd, pool_fd, namespace.root, namespace.pool)


def _try_lock(fd: int) -> bool:
    """Take an exclusive lock without blocking."""
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def _lock_bounded(fd: int, until: float) -> None:
    """Poll a nonblocking exclusive lock so a stopped holder cannot hang admission."""
    stop = min(until, time.monotonic() + LEDGER_WAIT_SECONDS)
    while not _try_lock(fd):
        if time.monotonic() >= stop:
            raise NativeWorkQueued('Native pool ledger is busy; work is already active')
        time.sleep(.02)


@contextlib.contextmanager
def ledger(until: float) -> Iterator[Namespace]:
    """Hold the pool mutex for one short transaction, bounded by the caller's deadline."""
    namespace = open_namespace()
    lock = None
    try:
        lock = open_private_file(namespace.pool_fd, LEDGER_LOCK, os.O_CREAT | os.O_RDWR)
        _lock_bounded(lock, until)
        assert_private_lock_identity(namespace.pool_fd, LEDGER_LOCK, lock)
        assert_namespace(namespace)
        yield namespace
    finally:
        if lock is not None:
            os.close(lock)
        namespace.close()


def probe(directory: int, name: str, shared: bool = False) -> str:
    """Return 'held', 'free' or 'missing' for a lock without keeping it.

    Callers hold the ledger lock, so pool entries cannot appear or vanish meanwhile.
    """
    if not _exists(directory, name):
        return 'missing'
    fd = open_private_file(directory, name, os.O_RDONLY)
    try:
        fcntl.flock(fd, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
    except BlockingIOError:
        return 'held'
    finally:
        os.close(fd)
    return 'free'


def _exists(directory: int, name: str) -> bool:
    """Observe an entry without following links."""
    try:
        os.stat(name, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def read_json(directory: int, name: str) -> object:
    """Read one bounded private JSON record."""
    return json.loads(read_private_file(directory, name))


def refresh(directory: int, names: list[str]) -> None:
    """Keep state in use younger than tmp_cleaner's three-day threshold."""
    for name in names:
        try:
            os.utime(name, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            continue


def next_ticket(namespace: Namespace, view: PoolView) -> int:
    """Allocate a sequence above the counter and every live ticket."""
    current = 1
    if _exists(namespace.pool_fd, COUNTER):
        value = read_json(namespace.pool_fd, COUNTER)
        current = value.get('nextTicket', 1) if isinstance(value, dict) else 1
    if type(current) is not int or current < 1:
        raise RuntimeError('Native pool ticket counter is malformed')
    sequence = max([current] + [row['sequence'] + 1 for row in view.tickets])
    publish(namespace.pool_fd, COUNTER, {'schemaVersion': 1, 'nextTicket': sequence + 1})
    return sequence


def publish(directory: int, name: str, value: dict) -> None:
    """Durably replace one pool record through the shared private-file primitive."""
    data = (json.dumps(value, sort_keys=True) + '\n').encode()
    write_pending_replace(directory, (name[:-5] + '.pending.json', name), data)
