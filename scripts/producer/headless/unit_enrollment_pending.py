"""Writer-only recovery of uncommitted unit-enrollment directories."""

from __future__ import annotations

import os
import re

from .durable_files import (
    bounded_directory_entries,
    DurableFileError,
    open_private_child_dir,
)
from .pending_cleanup_fs import (
    PendingCleanupFileError,
    remove_empty_private_pending_dir,
    remove_private_pending_file,
)
from .unit_enrollment_lock import (
    UnitEnrollmentWriterLockV1,
    validate_unit_enrollment_writer_lock_v1,
)
from .unit_enrollment_record import unit_enrollment_record_name_v1
from .unit_enrollment_schema import (
    UnitEnrollmentSchemaError,
    parse_prospective_unit_enrollment_v1,
)

_ENROLLMENT_NAME = "enrollment.json"
_PENDING = re.compile(r"\.pending-([0-9a-f]{64})-([0-9a-f]{32})")
_MAX_ENTRIES = 8192
_MAX_ENROLLMENT_BYTES = 16_384


class UnitEnrollmentPendingError(RuntimeError):
    """Abandoned enrollment scratch is unsafe or ambiguous."""


def _pending_targets(names: tuple[str, ...]) -> dict[str, str]:
    pending = {}
    for name in names:
        if not name.startswith(".pending-"):
            continue
        match = _PENDING.fullmatch(name)
        if match is None or match.group(1) in pending:
            raise UnitEnrollmentPendingError(
                "unit-enrollment pending identity is ambiguous"
            )
        pending[match.group(1)] = name
    if any(target in names for target in pending):
        raise UnitEnrollmentPendingError(
            "unit-enrollment pending and final records coexist"
        )
    return pending


def _validate_target(raw: bytes, target: str) -> None:
    try:
        enrollment = parse_prospective_unit_enrollment_v1(raw)
    except UnitEnrollmentSchemaError:
        return
    expected = unit_enrollment_record_name_v1(enrollment.enrollment_key)
    if expected != target:
        raise UnitEnrollmentPendingError(
            "unit-enrollment pending identity disagrees with its target"
        )


def _discard(store_fd: int, name: str, target: str) -> None:
    record_fd = open_private_child_dir(store_fd, name)
    try:
        entries = bounded_directory_entries(record_fd, 2)
        if entries not in {(), (_ENROLLMENT_NAME,)}:
            raise UnitEnrollmentPendingError(
                "unit-enrollment pending closure is unsafe"
            )
        if entries:
            remove_private_pending_file(
                record_fd,
                _ENROLLMENT_NAME,
                _MAX_ENROLLMENT_BYTES,
                lambda raw: _validate_target(raw, target),
            )
    finally:
        os.close(record_fd)
    remove_empty_private_pending_dir(store_fd, name)


def cleanup_abandoned_unit_enrollment_pending_v1(value: object) -> None:
    """Discard only pre-rename enrollment records under its writer lock."""
    try:
        validate_unit_enrollment_writer_lock_v1(value)
        writer = value
        if type(writer) is not UnitEnrollmentWriterLockV1:
            raise UnitEnrollmentPendingError(
                "unit-enrollment writer witness is invalid"
            )
        before = bounded_directory_entries(writer.store_fd, _MAX_ENTRIES)
        pending = _pending_targets(before)
        retained = frozenset(set(before) - set(pending.values()))
        for target, name in pending.items():
            _discard(writer.store_fd, name, target)
        after = frozenset(
            bounded_directory_entries(writer.store_fd, _MAX_ENTRIES)
        )
        if after != retained:
            raise UnitEnrollmentPendingError(
                "unit-enrollment store changed during pending cleanup"
            )
    except UnitEnrollmentPendingError:
        raise
    except (DurableFileError, PendingCleanupFileError, RuntimeError) as exc:
        raise UnitEnrollmentPendingError(
            "unit-enrollment pending cleanup failed"
        ) from exc
