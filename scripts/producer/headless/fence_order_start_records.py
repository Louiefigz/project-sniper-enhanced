"""Pinned record snapshots for durable fence-order start intents."""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass

from . import quality_receipt_json as wire
from .cross_ledger_order_lock import (
    validate_publish_cross_ledger_lock_pair_v1,
)
from .durable_files import (
    bounded_directory_entries,
    exact_directory_entries,
    open_private_child_dir,
    open_private_file,
    private_child_dir,
)
from .fence_order_start_schema import (
    FenceOrderStartIntentV1,
    parse_fence_order_start_intent_v1,
)
from .fence_order_start_types import (
    FENCE_ORDER_START_STORE_NAME,
    MAX_FENCE_ORDER_START_BYTES,
    MAX_FENCE_ORDER_START_RECORDS,
    FenceOrderStartError,
    PublishCrossLedgerLockPairV1,
)
from .record_durability import (
    assert_named_private_directory_identity,
    assert_named_private_file_identity,
    assert_private_file_snapshot,
    fsync_read_stable_private_fd,
    read_stable_private_fd,
)
from .wire_identity import same_wire_value

STORE_NAME = FENCE_ORDER_START_STORE_NAME
MAX_START_RECORDS = MAX_FENCE_ORDER_START_RECORDS
MAX_START_BYTES = MAX_FENCE_ORDER_START_BYTES
_RECORD_DOMAIN = b"sniper-fence-order-start-record-v1\0"
_RECORD_NAME = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class ObservedFenceOrderStartV1:
    """One parsed start intent with its pinned metadata snapshot."""

    name: str
    intent: FenceOrderStartIntentV1
    raw: bytes
    snapshot: tuple[int, ...]


def fence_order_start_record_name_v1(attempt_id: str) -> str:
    """Derive an opaque filename from one canonical attempt UUID."""
    attempt = wire.canonical_uuid(attempt_id, "start attempt ID")
    return hashlib.sha256(_RECORD_DOMAIN + attempt.encode("ascii")).hexdigest()


def _validate_pair(locks: PublishCrossLedgerLockPairV1) -> None:
    if type(locks) is not PublishCrossLedgerLockPairV1:
        raise FenceOrderStartError("publish-cross lock pair is invalid")
    validate_publish_cross_ledger_lock_pair_v1(
        locks.publish_lock, locks.cross_lock
    )


def _open_store(locks: PublishCrossLedgerLockPairV1, create: bool) -> int:
    _validate_pair(locks)
    root_fd = locks.publish_lock.root_fd
    store_fd = (
        private_child_dir(root_fd, STORE_NAME)
        if create
        else open_private_child_dir(root_fd, STORE_NAME)
    )
    try:
        os.fsync(root_fd)
        assert_named_private_directory_identity(root_fd, STORE_NAME, store_fd)
        _validate_pair(locks)
        return store_fd
    except BaseException:
        os.close(store_fd)
        raise


def open_fence_order_start_store_v1(
    locks: PublishCrossLedgerLockPairV1,
) -> int:
    """Create or reopen the store only under both exact live locks."""
    return _open_store(locks, True)


def open_existing_fence_order_start_store_v1(
    locks: PublishCrossLedgerLockPairV1,
) -> int:
    """Open and refsync the existing store without creating it."""
    return _open_store(locks, False)


def _snapshot(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_uid,
        info.st_gid,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


@contextlib.contextmanager
def _observed(
    store_fd: int, name: str, durable: bool
) -> Iterator[ObservedFenceOrderStartV1]:
    fd = open_private_file(store_fd, name, os.O_RDONLY)
    try:
        assert_named_private_file_identity(store_fd, name, fd)
        if durable:
            raw, snapshot = fsync_read_stable_private_fd(fd, MAX_START_BYTES)
        else:
            raw = read_stable_private_fd(fd, MAX_START_BYTES)
            snapshot = _snapshot(os.fstat(fd))
        intent = parse_fence_order_start_intent_v1(raw)
        yield ObservedFenceOrderStartV1(name, intent, raw, snapshot)
        assert_private_file_snapshot(fd, snapshot)
        assert_named_private_file_identity(store_fd, name, fd)
    finally:
        os.close(fd)


@contextlib.contextmanager
def pinned_fence_order_start_record_v1(
    store_fd: int, name: str
) -> Iterator[ObservedFenceOrderStartV1]:
    """Fsync and reobserve the same named start-intent inode."""
    with _observed(store_fd, name, True) as record:
        yield record


def _scan(store_fd: int) -> tuple[ObservedFenceOrderStartV1, ...]:
    names = bounded_directory_entries(store_fd, MAX_START_RECORDS)
    if any(not _RECORD_NAME.fullmatch(name) for name in names):
        raise FenceOrderStartError("start store has unknown entries")
    records = []
    for name in names:
        with _observed(store_fd, name, False) as record:
            records.append(record)
    if not exact_directory_entries(store_fd, frozenset(names)):
        raise FenceOrderStartError("start store changed during scan")
    return tuple(records)


def stable_fence_order_start_scan_v1(
    store_fd: int,
) -> tuple[ObservedFenceOrderStartV1, ...]:
    """Twice read the bounded exact set around its directory fsync."""
    first = _scan(store_fd)
    os.fsync(store_fd)
    second = _scan(store_fd)
    if not same_wire_value(first, second):
        raise FenceOrderStartError(
            "start store changed across durability barrier"
        )
    return second
