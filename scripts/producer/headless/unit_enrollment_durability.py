"""Durability recovery for visible unit-enrollment records."""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from dataclasses import dataclass

from .durable_files import (
    DurableFileError,
    exact_directory_entries,
    open_private_child_dir,
    open_private_file,
)
from .record_durability import (
    assert_named_private_directory_identity,
    assert_named_private_file_identity,
    assert_private_file_snapshot,
    fsync_read_stable_private_fd,
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


class UnitEnrollmentDurabilityError(RuntimeError):
    """A visible enrollment could not be made durably reusable."""


@dataclass(frozen=True)
class _PinnedEnrollment:
    record_fd: int
    enrollment_fd: int


@dataclass(frozen=True)
class _DurableEnrollmentObservation:
    pinned: _PinnedEnrollment
    file_snapshot: tuple[int, ...]
    enrollment: ProspectiveUnitEnrollmentV1


def _assert_pinned(
    store_fd: int, name: str, pinned: _PinnedEnrollment
) -> None:
    assert_named_private_directory_identity(store_fd, name, pinned.record_fd)
    if not exact_directory_entries(pinned.record_fd, {_ENROLLMENT_NAME}):
        raise DurableFileError("unit enrollment record closure changed")
    assert_named_private_file_identity(
        pinned.record_fd, _ENROLLMENT_NAME, pinned.enrollment_fd
    )


def _parse_raw(raw: bytes) -> ProspectiveUnitEnrollmentV1:
    try:
        enrollment = parse_prospective_unit_enrollment_v1(raw)
        bind_prospective_unit_enrollment_v1(enrollment)
    except (RuntimeError, UnitEnrollmentBindingError) as exc:
        raise UnitEnrollmentDurabilityError(
            "durable unit enrollment bytes are invalid"
        ) from exc
    return enrollment


def _prepare_pinned(store_fd: int, name: str) -> _DurableEnrollmentObservation:
    record_fd = open_private_child_dir(store_fd, name)
    enrollment_fd = None
    try:
        enrollment_fd = open_private_file(
            record_fd, _ENROLLMENT_NAME, os.O_RDONLY
        )
        pinned = _PinnedEnrollment(record_fd, enrollment_fd)
        _assert_pinned(store_fd, name, pinned)
        raw, snapshot = fsync_read_stable_private_fd(enrollment_fd, 16_384)
        os.fsync(record_fd)
        os.fsync(store_fd)
        _assert_pinned(store_fd, name, pinned)
        assert_private_file_snapshot(enrollment_fd, snapshot)
        return _DurableEnrollmentObservation(pinned, snapshot, _parse_raw(raw))
    except (DurableFileError, OSError, RuntimeError):
        if enrollment_fd is not None:
            os.close(enrollment_fd)
        os.close(record_fd)
        raise


@contextlib.contextmanager
def pinned_durable_unit_enrollment_record_v1(
    store_fd: int, name: str
) -> Iterator[ProspectiveUnitEnrollmentV1]:
    """Hold and return the exact enrollment inode flushed for replay."""
    try:
        observed = _prepare_pinned(store_fd, name)
    except (DurableFileError, OSError, RuntimeError) as exc:
        raise UnitEnrollmentDurabilityError(
            "unit enrollment durability recovery failed"
        ) from exc
    completed = False
    try:
        yield observed.enrollment
        completed = True
    finally:
        try:
            if completed:
                _assert_pinned(store_fd, name, observed.pinned)
                assert_private_file_snapshot(
                    observed.pinned.enrollment_fd, observed.file_snapshot
                )
        except (DurableFileError, OSError) as exc:
            raise UnitEnrollmentDurabilityError(
                "unit enrollment changed after durability recovery"
            ) from exc
        finally:
            os.close(observed.pinned.enrollment_fd)
            os.close(observed.pinned.record_fd)


def ensure_unit_enrollment_record_durable_v1(store_fd: int, name: str) -> None:
    """Flush selected enrollment bytes, its record, and the store entry."""
    with pinned_durable_unit_enrollment_record_v1(store_fd, name):
        pass
