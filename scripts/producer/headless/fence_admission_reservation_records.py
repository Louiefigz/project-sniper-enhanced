"""Pinned snapshots and immutable writes for fence reservation records."""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass

from . import quality_receipt_json as wire
from .active_fence_lock import ActiveFenceLockV1, validate_active_fence_lock_v1
from .durable_files import (
    bounded_directory_entries,
    exact_directory_entries,
    open_private_child_dir,
    open_private_file,
    private_child_dir,
)
from .fence_admission_reservation_schema import (
    FenceAdmissionReservationV1,
    parse_fence_admission_reservation_v1,
)
from .fence_admission_reservation_types import (
    FENCE_ADMISSION_RESERVATION_STORE_NAME,
    MAX_FENCE_ADMISSION_RESERVATION_BYTES,
    MAX_FENCE_ADMISSION_RESERVATION_RECORDS,
    FenceAdmissionReservationError,
)
from .record_durability import (
    assert_named_private_directory_identity,
    assert_named_private_file_identity,
    assert_private_file_snapshot,
    fsync_read_stable_private_fd,
    read_stable_private_fd,
)
from .wire_identity import same_wire_value

STORE_NAME = FENCE_ADMISSION_RESERVATION_STORE_NAME
MAX_RESERVATION_RECORDS = MAX_FENCE_ADMISSION_RESERVATION_RECORDS
MAX_RESERVATION_BYTES = MAX_FENCE_ADMISSION_RESERVATION_BYTES
_RECORD_DOMAIN = b"sniper-fence-admission-reservation-record-v1\0"
_RECORD_NAME = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class ObservedFenceAdmissionReservationV1:
    """One pinned read projected into a bounded in-memory snapshot."""

    name: str
    reservation: FenceAdmissionReservationV1
    raw: bytes
    snapshot: tuple[int, ...]


def fence_admission_reservation_record_name_v1(attempt_id: str) -> str:
    """Derive the opaque immutable filename from one canonical attempt ID."""
    canonical_attempt = wire.canonical_uuid(
        attempt_id, "reservation attempt ID"
    )
    return hashlib.sha256(
        _RECORD_DOMAIN + canonical_attempt.encode("ascii")
    ).hexdigest()


def open_fence_admission_reservation_store_v1(
    lock: ActiveFenceLockV1,
) -> int:
    """Create/reopen and refsync the store through its pinned root."""
    validate_active_fence_lock_v1(lock)
    store_fd = private_child_dir(lock.root_fd, STORE_NAME)
    try:
        os.fsync(lock.root_fd)
        assert_named_private_directory_identity(
            lock.root_fd, STORE_NAME, store_fd
        )
        validate_active_fence_lock_v1(lock)
        return store_fd
    except BaseException:
        os.close(store_fd)
        raise


def open_existing_fence_admission_reservation_store_v1(
    lock: ActiveFenceLockV1,
) -> int:
    """Open and refsync an existing store without creating any path."""
    validate_active_fence_lock_v1(lock)
    store_fd = open_private_child_dir(lock.root_fd, STORE_NAME)
    try:
        os.fsync(lock.root_fd)
        assert_named_private_directory_identity(
            lock.root_fd, STORE_NAME, store_fd
        )
        validate_active_fence_lock_v1(lock)
        return store_fd
    except BaseException:
        os.close(store_fd)
        raise


@contextlib.contextmanager
def _observed_record(
    store_fd: int, name: str, durable: bool
) -> Iterator[ObservedFenceAdmissionReservationV1]:
    fd = open_private_file(store_fd, name, os.O_RDONLY)
    try:
        assert_named_private_file_identity(store_fd, name, fd)
        if durable:
            raw, snapshot = fsync_read_stable_private_fd(
                fd, MAX_RESERVATION_BYTES
            )
        else:
            raw = read_stable_private_fd(fd, MAX_RESERVATION_BYTES)
            snapshot = _snapshot(os.fstat(fd))
        reservation = parse_fence_admission_reservation_v1(raw)
        yield ObservedFenceAdmissionReservationV1(
            name, reservation, raw, snapshot
        )
        assert_private_file_snapshot(fd, snapshot)
        assert_named_private_file_identity(store_fd, name, fd)
    finally:
        os.close(fd)


@contextlib.contextmanager
def pinned_fence_admission_reservation_v1(
    store_fd: int, name: str
) -> Iterator[ObservedFenceAdmissionReservationV1]:
    """Fsync and reobserve the same named private reservation inode."""
    with _observed_record(store_fd, name, True) as record:
        yield record


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


def _names(store_fd: int) -> tuple[str, ...]:
    names = bounded_directory_entries(store_fd, MAX_RESERVATION_RECORDS)
    if any(not _RECORD_NAME.fullmatch(name) for name in names):
        raise FenceAdmissionReservationError(
            "fence reservation store has unknown entries"
        )
    return names


def _scan(
    store_fd: int,
) -> tuple[ObservedFenceAdmissionReservationV1, ...]:
    names = _names(store_fd)
    records = []
    for name in names:
        with _observed_record(store_fd, name, False) as record:
            records.append(record)
    if not exact_directory_entries(store_fd, frozenset(names)):
        raise FenceAdmissionReservationError(
            "fence reservation store changed during scan"
        )
    return tuple(records)


def stable_fence_admission_reservation_scan_v1(
    store_fd: int,
) -> tuple[ObservedFenceAdmissionReservationV1, ...]:
    """Twice read the exact bounded set around a store fsync barrier."""
    first = _scan(store_fd)
    os.fsync(store_fd)
    second = _scan(store_fd)
    if not same_wire_value(first, second):
        raise FenceAdmissionReservationError(
            "fence reservation set changed across durability barrier"
        )
    return second
