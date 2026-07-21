"""PID-bound writer witness for the prospective unit-enrollment store."""

from __future__ import annotations

import contextlib
import fcntl
import os
import secrets
import stat
from collections.abc import Iterator
from dataclasses import dataclass

from .authority_record import AuthorityRecordError, ensure_authority_record
from .durable_files import (
    assert_private_lock_identity,
    DurableFileError,
    open_private_dir,
    open_private_file,
    private_child_dir,
)

UNIT_ENROLLMENT_LOCK_NAME = ".unit-enrollment-v1.lock"
UNIT_ENROLLMENT_STORE_NAME = "unit-enrollments-v1"
_ACTIVE_WRITERS: dict[bytes, object] = {}


class UnitEnrollmentWriterLockError(RuntimeError):
    """The unit-enrollment writer witness is stale, forged, or unsafe."""


@dataclass(frozen=True)
class UnitEnrollmentWriterLockV1:
    """Opaque live enrollment lock plus exact root and store descriptors."""

    authority_root: str
    authority_id: str
    root_fd: int
    lock_fd: int
    store_fd: int
    root_identity: tuple[int, int]
    lock_identity: tuple[int, int]
    store_identity: tuple[int, int]
    creator_pid: int
    context_token: bytes


def _identity(fd: int) -> tuple[int, int]:
    info = os.fstat(fd)
    return info.st_dev, info.st_ino


def _exclusive_lock_is_held(value: UnitEnrollmentWriterLockV1) -> bool:
    probe_fd = open_private_file(
        value.root_fd, UNIT_ENROLLMENT_LOCK_NAME, os.O_RDWR
    )
    try:
        if _identity(probe_fd) != value.lock_identity:
            return False
        try:
            fcntl.flock(probe_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(probe_fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(probe_fd)


def _private_directory(info: os.stat_result) -> bool:
    return (
        stat.S_ISDIR(info.st_mode)
        and info.st_uid == os.geteuid()
        and stat.S_IMODE(info.st_mode) == 0o700
    )


def validate_unit_enrollment_writer_lock_v1(value: object) -> None:
    """Require the registered lock and named root/store identities."""
    if type(value) is not UnitEnrollmentWriterLockV1:
        raise UnitEnrollmentWriterLockError(
            "unit-enrollment writer witness is invalid"
        )
    registered = _ACTIVE_WRITERS.get(value.context_token)
    live = (
        type(value.context_token) is bytes
        and len(value.context_token) == 32
        and value.creator_pid == os.getpid()
        and registered is value
    )
    if not live:
        raise UnitEnrollmentWriterLockError(
            "unit-enrollment writer witness is stale or unregistered"
        )
    try:
        assert_private_lock_identity(
            value.root_fd, UNIT_ENROLLMENT_LOCK_NAME, value.lock_fd
        )
        named_root = os.stat(value.authority_root, follow_symlinks=False)
        named_store = os.stat(
            UNIT_ENROLLMENT_STORE_NAME,
            dir_fd=value.root_fd,
            follow_symlinks=False,
        )
        valid = (
            _identity(value.root_fd)
            == value.root_identity
            == (named_root.st_dev, named_root.st_ino)
            and _identity(value.lock_fd) == value.lock_identity
            and _identity(value.store_fd)
            == value.store_identity
            == (named_store.st_dev, named_store.st_ino)
            and _private_directory(os.fstat(value.root_fd))
            and _private_directory(named_root)
            and _private_directory(os.fstat(value.store_fd))
            and _private_directory(named_store)
            and _exclusive_lock_is_held(value)
        )
    except (DurableFileError, OSError) as exc:
        raise UnitEnrollmentWriterLockError(
            "unit-enrollment writer identity cannot be reobserved"
        ) from exc
    if not valid:
        raise UnitEnrollmentWriterLockError(
            "unit-enrollment writer lock or store was replaced"
        )


@contextlib.contextmanager
def locked_unit_enrollment_writer_v1(
    authority_root: str, authority_id: str
) -> Iterator[UnitEnrollmentWriterLockV1]:
    """Acquire the enrollment writer lock and exact authority-owned store."""
    root_fd = open_private_dir(authority_root)
    lock_fd = store_fd = witness = None
    try:
        lock_fd = open_private_file(
            root_fd, UNIT_ENROLLMENT_LOCK_NAME, os.O_CREAT | os.O_RDWR
        )
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        os.fsync(root_fd)
        ensure_authority_record(root_fd, authority_id)
        store_fd = private_child_dir(root_fd, UNIT_ENROLLMENT_STORE_NAME)
        witness = UnitEnrollmentWriterLockV1(
            authority_root,
            authority_id,
            root_fd,
            lock_fd,
            store_fd,
            _identity(root_fd),
            _identity(lock_fd),
            _identity(store_fd),
            os.getpid(),
            secrets.token_bytes(32),
        )
        _ACTIVE_WRITERS[witness.context_token] = witness
        validate_unit_enrollment_writer_lock_v1(witness)
        yield witness
        validate_unit_enrollment_writer_lock_v1(witness)
    except UnitEnrollmentWriterLockError:
        raise
    except (AuthorityRecordError, DurableFileError, OSError) as exc:
        raise UnitEnrollmentWriterLockError(
            "unit-enrollment authority or lock cannot be acquired"
        ) from exc
    finally:
        if witness is not None:
            _ACTIVE_WRITERS.pop(witness.context_token, None)
        if store_fd is not None:
            os.close(store_fd)
        if lock_fd is not None:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
        os.close(root_fd)
