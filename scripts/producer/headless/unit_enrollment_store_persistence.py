"""Atomic pending-directory writer for unit-enrollment records."""

from __future__ import annotations

import os
import uuid

from .durable_files import (
    open_private_child_dir,
    open_private_file,
    write_all,
)
from .unit_enrollment_schema import ProspectiveUnitEnrollmentV1
from .unit_enrollment_store_errors import UnitEnrollmentStoreError

_ENROLLMENT_NAME = "enrollment.json"


def _write_file(dir_fd: int, raw: bytes) -> None:
    fd = open_private_file(
        dir_fd, _ENROLLMENT_NAME, os.O_WRONLY | os.O_CREAT | os.O_EXCL
    )
    try:
        write_all(fd, raw)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.fsync(dir_fd)


def persist_unit_enrollment_record_v1(
    store_fd: int, name: str, enrollment: ProspectiveUnitEnrollmentV1
) -> None:
    """Install one immutable enrollment with a durable final rename."""
    pending = f".pending-{name}-{uuid.uuid4().hex}"
    try:
        os.mkdir(pending, 0o700, dir_fd=store_fd)
        os.chmod(pending, 0o700, dir_fd=store_fd, follow_symlinks=False)
        os.fsync(store_fd)
        pending_fd = open_private_child_dir(store_fd, pending)
        try:
            _write_file(pending_fd, enrollment.document_json)
        finally:
            os.close(pending_fd)
        os.rename(pending, name, src_dir_fd=store_fd, dst_dir_fd=store_fd)
        os.fsync(store_fd)
    except OSError as exc:
        raise UnitEnrollmentStoreError(
            "cannot persist unit enrollment"
        ) from exc
