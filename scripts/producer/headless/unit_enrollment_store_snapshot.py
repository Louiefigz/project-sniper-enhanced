"""Pinned snapshot reads for the durable unit-enrollment store."""

from __future__ import annotations

import contextlib
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass

from .durable_files import (
    DurableFileError,
    exact_directory_entries,
    open_private_child_dir,
    open_private_file,
)
from .unit_enrollment_binding import (
    UnitEnrollmentBindingError,
    bind_prospective_unit_enrollment_v1,
)
from .unit_enrollment_schema import (
    ProspectiveUnitEnrollmentV1,
    parse_prospective_unit_enrollment_v1,
)

_ENROLLMENT_NAME = "enrollment.json"
_STORE_NAME = "unit-enrollments-v1"
_RECORD = re.compile(r"[0-9a-f]{64}")
UNIT_ENROLLMENT_SNAPSHOT_FD_BUDGET = 2


class UnitEnrollmentSnapshotError(RuntimeError):
    """A retained enrollment changed while its set was being observed."""


@dataclass(frozen=True)
class UnitEnrollmentSnapshotV1:
    """One parsed enrollment plus its initial inode and byte snapshots."""

    name: str
    enrollment: ProspectiveUnitEnrollmentV1
    raw: bytes
    record_snapshot: tuple[int, ...]
    enrollment_snapshot: tuple[int, ...]


def unit_enrollment_record_names(store_fd: int, limit: int) -> tuple[str, ...]:
    """Bound and validate the complete enrollment-record name set."""
    names = []
    try:
        with os.scandir(store_fd) as entries:
            for entry in entries:
                name = entry.name
                if name.startswith(".pending-"):
                    raise UnitEnrollmentSnapshotError(
                        "torn unit enrollment pending record exists"
                    )
                if not _RECORD.fullmatch(name):
                    raise UnitEnrollmentSnapshotError(
                        "unit enrollment store has unknown entries"
                    )
                if len(names) >= limit:
                    raise UnitEnrollmentSnapshotError(
                        "unit enrollment store exceeds its record limit"
                    )
                names.append(name)
    except OSError as exc:
        raise UnitEnrollmentSnapshotError(
            "cannot inspect unit enrollment store"
        ) from exc
    return tuple(sorted(names))


def require_unit_enrollment_store_entry(root_fd: int, store_fd: int) -> None:
    """Require the held store descriptor to remain the authority-root entry."""
    reopened = open_private_child_dir(root_fd, _STORE_NAME)
    try:
        expected = os.fstat(store_fd)
        observed = os.fstat(reopened)
        if (expected.st_dev, expected.st_ino) != (
            observed.st_dev,
            observed.st_ino,
        ):
            raise UnitEnrollmentSnapshotError(
                "unit enrollment store directory was replaced"
            )
    finally:
        os.close(reopened)


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


def _read_bounded(fd: int, limit: int) -> bytes:
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        chunks, remaining = [], limit + 1
        while remaining:
            chunk = os.read(fd, min(16_384, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
    except OSError as exc:
        raise UnitEnrollmentSnapshotError(
            "cannot read retained unit enrollment"
        ) from exc
    raw = b"".join(chunks)
    if len(raw) > limit:
        raise UnitEnrollmentSnapshotError("unit enrollment bytes exceed limit")
    return raw


def _same_entry(parent_fd: int, name: str, child_fd: int) -> bool:
    try:
        path = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        opened = os.fstat(child_fd)
    except OSError as exc:
        raise UnitEnrollmentSnapshotError(
            "unit enrollment entry cannot be reobserved"
        ) from exc
    return (path.st_dev, path.st_ino) == (opened.st_dev, opened.st_ino)


def _parse(raw: bytes) -> ProspectiveUnitEnrollmentV1:
    try:
        enrollment = parse_prospective_unit_enrollment_v1(raw)
        bind_prospective_unit_enrollment_v1(enrollment)
    except (RuntimeError, UnitEnrollmentBindingError) as exc:
        raise UnitEnrollmentSnapshotError(
            "stored unit enrollment is invalid"
        ) from exc
    return enrollment


def _open_snapshot(
    store_fd: int, name: str, limit: int
) -> UnitEnrollmentSnapshotV1:
    record_fd = open_private_child_dir(store_fd, name)
    enrollment_fd = None
    try:
        if not exact_directory_entries(record_fd, {_ENROLLMENT_NAME}):
            raise UnitEnrollmentSnapshotError(
                "unit enrollment record closure is not exact"
            )
        enrollment_fd = open_private_file(
            record_fd, _ENROLLMENT_NAME, os.O_RDONLY
        )
        record_snapshot = _snapshot(os.fstat(record_fd))
        before = _snapshot(os.fstat(enrollment_fd))
        raw = _read_bounded(enrollment_fd, limit)
        after = _snapshot(os.fstat(enrollment_fd))
        stable = before == after and _same_entry(store_fd, name, record_fd)
        stable = stable and _same_entry(
            record_fd, _ENROLLMENT_NAME, enrollment_fd
        )
        if not stable:
            raise UnitEnrollmentSnapshotError(
                "unit enrollment changed during initial read"
            )
        return UnitEnrollmentSnapshotV1(
            name,
            _parse(raw),
            raw,
            record_snapshot,
            after,
        )
    except Exception as exc:
        if isinstance(exc, UnitEnrollmentSnapshotError):
            raise
        raise UnitEnrollmentSnapshotError(
            "stored unit enrollment is invalid"
        ) from exc
    finally:
        if enrollment_fd is not None:
            os.close(enrollment_fd)
        os.close(record_fd)


def _revalidate(
    store_fd: int, item: UnitEnrollmentSnapshotV1, limit: int
) -> None:
    observed = _open_snapshot(store_fd, item.name, limit)
    stable = (
        observed.record_snapshot == item.record_snapshot
        and observed.enrollment_snapshot == item.enrollment_snapshot
        and observed.raw == item.raw
    )
    if not stable:
        raise UnitEnrollmentSnapshotError(
            "unit enrollment changed during retained-set read"
        )


@contextlib.contextmanager
def pinned_unit_enrollment_set(
    store_fd: int,
    names: tuple[str, ...],
    byte_limit: int,
) -> Iterator[tuple[UnitEnrollmentSnapshotV1, ...]]:
    """Twice reobserve every row plus the exact set using at most two FDs."""
    if (
        type(names) is not tuple
        or type(byte_limit) is not int
        or byte_limit <= 0
    ):
        raise UnitEnrollmentSnapshotError(
            "unit enrollment snapshot request is invalid"
        )
    opened: list[UnitEnrollmentSnapshotV1] = []
    expected = frozenset(names)
    try:
        for name in names:
            opened.append(_open_snapshot(store_fd, name, byte_limit))
        yield tuple(opened)
        if not exact_directory_entries(store_fd, expected):
            raise UnitEnrollmentSnapshotError(
                "unit enrollment store changed during retained-set read"
            )
        for item in opened:
            _revalidate(store_fd, item, byte_limit)
        if not exact_directory_entries(store_fd, expected):
            raise UnitEnrollmentSnapshotError(
                "unit enrollment store changed during retained-set read"
            )
    except (DurableFileError, OSError) as exc:
        raise UnitEnrollmentSnapshotError(
            "unit enrollment snapshot cannot be reobserved"
        ) from exc
