"""Lease epochs and guarded teardown for never-unlinked flock files."""

from __future__ import annotations

import fcntl
import os
import secrets

from .durable_files import (
    DurableFileError,
    assert_private_lock_identity,
    open_private_file,
    write_all,
)

LOCK_LEASE_SIZE_V1 = 32


class ExclusiveLockLeaseError(RuntimeError):
    """A lock lease, owner, descriptor, or named inode is unsafe."""


def descriptor_identity_v1(fd: int) -> tuple[int, int]:
    """Return one descriptor's device and inode identity."""
    info = os.fstat(fd)
    return info.st_dev, info.st_ino


def valid_descriptor_identity_v1(value: object) -> bool:
    """Return whether a hostile value is an exact device/inode pair."""
    return (
        type(value) is tuple
        and len(value) == 2
        and all(type(item) is int and item >= 0 for item in value)
    )


def install_exclusive_lock_lease_v1(
    root_fd: int, lock_fd: int, lock_name: str
) -> bytes:
    """Replace, flush, and exactly reread one epoch while flock is held."""
    token = secrets.token_bytes(LOCK_LEASE_SIZE_V1)
    if type(token) is not bytes or len(token) != LOCK_LEASE_SIZE_V1:
        raise ExclusiveLockLeaseError("lock lease epoch generation failed")
    try:
        assert_private_lock_identity(root_fd, lock_name, lock_fd)
        previous = os.pread(lock_fd, LOCK_LEASE_SIZE_V1 + 1, 0)
        if previous == token:
            raise ExclusiveLockLeaseError("lock lease epoch was reused")
        os.ftruncate(lock_fd, 0)
        os.lseek(lock_fd, 0, os.SEEK_SET)
        write_all(lock_fd, token)
        os.fsync(lock_fd)
        os.fsync(root_fd)
        observed = os.pread(lock_fd, LOCK_LEASE_SIZE_V1 + 1, 0)
        assert_private_lock_identity(root_fd, lock_name, lock_fd)
    except ExclusiveLockLeaseError:
        raise
    except (DurableFileError, OSError) as exc:
        raise ExclusiveLockLeaseError(
            "lock lease cannot be installed"
        ) from exc
    if observed != token:
        raise ExclusiveLockLeaseError("lock lease bytes changed after flush")
    return token


def _require_witness_owns_flock(
    root_fd: int, lock_fd: int, lock_name: str
) -> None:
    probe_fd = open_private_file(root_fd, lock_name, os.O_RDWR)
    try:
        if descriptor_identity_v1(probe_fd) != descriptor_identity_v1(lock_fd):
            raise ExclusiveLockLeaseError("lock probe inode changed")
        try:
            fcntl.flock(probe_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pass
        else:
            fcntl.flock(probe_fd, fcntl.LOCK_UN)
            raise ExclusiveLockLeaseError("lock witness is not held")
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ExclusiveLockLeaseError(
                "lock witness does not own the held flock"
            ) from exc
    finally:
        os.close(probe_fd)


def validate_exclusive_lock_lease_v1(
    root_fd: int, lock_fd: int, lock_name: str, expected_lease: bytes
) -> None:
    """Require exact lease bytes and ownership by the witness descriptor."""
    valid = (
        type(expected_lease) is bytes
        and len(expected_lease) == LOCK_LEASE_SIZE_V1
    )
    if not valid:
        raise ExclusiveLockLeaseError("expected lock lease is invalid")
    try:
        assert_private_lock_identity(root_fd, lock_name, lock_fd)
        before = os.pread(lock_fd, LOCK_LEASE_SIZE_V1 + 1, 0)
        _require_witness_owns_flock(root_fd, lock_fd, lock_name)
        after = os.pread(lock_fd, LOCK_LEASE_SIZE_V1 + 1, 0)
        assert_private_lock_identity(root_fd, lock_name, lock_fd)
    except ExclusiveLockLeaseError:
        raise
    except (DurableFileError, OSError) as exc:
        raise ExclusiveLockLeaseError(
            "lock lease cannot be validated"
        ) from exc
    if before != expected_lease or after != expected_lease:
        raise ExclusiveLockLeaseError("lock lease epoch changed")


def duplicate_lock_witness_fds_v1(
    root_fd: int, lock_fd: int
) -> tuple[int, int]:
    """Duplicate retained descriptors for the public witness capability."""
    root_copy = os.dup(root_fd)
    try:
        lock_copy = os.dup(lock_fd)
    except BaseException:
        os.close(root_copy)
        raise
    return root_copy, lock_copy


def same_open_description_v1(
    witness_fd: int, guard_fd: int, expected_identity: tuple[int, int]
) -> bool:
    """Distinguish a dup from a same-inode reopen by flag challenge."""
    if not valid_descriptor_identity_v1(expected_identity):
        return False
    changed = False
    original = None
    try:
        identities = (
            descriptor_identity_v1(witness_fd),
            descriptor_identity_v1(guard_fd),
        )
        if identities != (expected_identity, expected_identity):
            return False
        original = fcntl.fcntl(guard_fd, fcntl.F_GETFL)
        witness_before = fcntl.fcntl(witness_fd, fcntl.F_GETFL)
        bit = os.O_NONBLOCK
        target = (original & ~bit) | ((witness_before ^ bit) & bit)
        fcntl.fcntl(guard_fd, fcntl.F_SETFL, target)
        changed = True
        witness_during = fcntl.fcntl(witness_fd, fcntl.F_GETFL)
        fcntl.fcntl(guard_fd, fcntl.F_SETFL, target ^ bit)
        witness_returned = fcntl.fcntl(witness_fd, fcntl.F_GETFL)
    except (OSError, TypeError, ValueError):
        return False
    finally:
        if changed and original is not None:
            try:
                fcntl.fcntl(guard_fd, fcntl.F_SETFL, original)
            except (OSError, TypeError, ValueError):
                pass
    try:
        witness_after = fcntl.fcntl(witness_fd, fcntl.F_GETFL)
    except (OSError, TypeError, ValueError):
        return False
    return (
        witness_during & bit == target & bit
        and witness_returned & bit == witness_before & bit
        and witness_after & bit == witness_before & bit
    )


def close_guarded_witness_fd_v1(
    witness_fd: int, guard_fd: int, expected_identity: tuple[int, int]
) -> None:
    """Close only the still-duplicated public witness descriptor."""
    if not same_open_description_v1(witness_fd, guard_fd, expected_identity):
        return
    try:
        os.close(witness_fd)
    except (OSError, TypeError, ValueError):
        pass


def close_owned_fd_v1(fd: int | None, expected_identity: object) -> None:
    """Best-effort close of one private descriptor with exact identity."""
    if fd is None or not valid_descriptor_identity_v1(expected_identity):
        return
    try:
        if descriptor_identity_v1(fd) == expected_identity:
            os.close(fd)
    except (OSError, TypeError, ValueError):
        pass


def release_owned_lock_fd_v1(
    fd: int | None, expected_identity: object
) -> None:
    """Best-effort unlock and close without ever raising from teardown."""
    if fd is None or not valid_descriptor_identity_v1(expected_identity):
        return
    try:
        owned = descriptor_identity_v1(fd) == expected_identity
    except (OSError, TypeError, ValueError):
        return
    if not owned:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    except (OSError, TypeError, ValueError):
        pass
    close_owned_fd_v1(fd, expected_identity)
