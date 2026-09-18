"""Guarded descriptor lifecycle for the V3 operation-admission writer."""

from __future__ import annotations

import contextlib
import fcntl
import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import partial

from .authority_record import ensure_authority_record
from .durable_files import open_private_file, private_child_dir
from .exclusive_lock_lease import (
    close_guarded_witness_fd_v1,
    close_owned_fd_v1,
    descriptor_identity_v1,
    install_exclusive_lock_lease_v1,
    release_owned_lock_fd_v1,
)
from .fork_fd_cleanup import (
    begin_inherited_fd_cleanup_v1,
    close_tracked_fd_v1,
    create_tracked_fd_v1,
    finish_inherited_fd_cleanup_v1,
    track_inherited_fd_v1,
)

OPERATION_ADMISSION_LOCK_NAME = ".operation-admission-v3.lock"
OPERATION_ADMISSION_STORE_NAME = "operation-admissions-v3"


@dataclass(frozen=True)
class OperationAdmissionLockResourcesV3:
    """Private guards plus public duplicate descriptors for one writer."""

    root_guard_fd: int
    lock_guard_fd: int
    store_guard_fd: int
    root_fd: int
    lock_fd: int
    store_fd: int
    root_identity: tuple[int, int]
    lock_identity: tuple[int, int]
    store_identity: tuple[int, int]
    lease_token: bytes


def _acquire(
    root_fd: int,
    authority_id: str,
    validate_outer: Callable[[], None],
    cleanup_token: object,
) -> tuple[int, int, bytes]:
    validate_outer()
    lock_fd = create_tracked_fd_v1(
        cleanup_token,
        lambda: open_private_file(
            root_fd,
            OPERATION_ADMISSION_LOCK_NAME,
            os.O_CREAT | os.O_RDWR,
        ),
    )
    try:
        validate_outer()
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        validate_outer()
        lease = install_exclusive_lock_lease_v1(
            root_fd, lock_fd, OPERATION_ADMISSION_LOCK_NAME
        )
        validate_outer()
        ensure_authority_record(root_fd, authority_id)
        validate_outer()
        store_fd = create_tracked_fd_v1(
            cleanup_token,
            lambda: private_child_dir(root_fd, OPERATION_ADMISSION_STORE_NAME),
        )
        try:
            validate_outer()
        except BaseException:
            close_tracked_fd_v1(cleanup_token, store_fd)
            raise
        return lock_fd, store_fd, lease
    except BaseException:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except OSError:
            pass
        close_tracked_fd_v1(cleanup_token, lock_fd)
        raise


def _resources(
    guards: tuple[int, int, int], lease: bytes, cleanup_token: object
) -> OperationAdmissionLockResourcesV3:
    root_guard_fd, lock_guard_fd, store_guard_fd = guards
    root_fd = _tracked_dup(root_guard_fd, cleanup_token)
    lock_fd = store_fd = None
    try:
        lock_fd = _tracked_dup(lock_guard_fd, cleanup_token)
        store_fd = _tracked_dup(store_guard_fd, cleanup_token)
        return OperationAdmissionLockResourcesV3(
            *guards,
            root_fd,
            lock_fd,
            store_fd,
            descriptor_identity_v1(root_guard_fd),
            descriptor_identity_v1(lock_guard_fd),
            descriptor_identity_v1(store_guard_fd),
            lease,
        )
    except BaseException:
        if store_fd is not None:
            close_tracked_fd_v1(cleanup_token, store_fd)
        if lock_fd is not None:
            close_tracked_fd_v1(cleanup_token, lock_fd)
        close_tracked_fd_v1(cleanup_token, root_fd)
        raise


def _tracked_dup(fd: int, cleanup_token: object) -> int:
    return create_tracked_fd_v1(cleanup_token, lambda: os.dup(fd))


def _safe_identity(fd: int | None) -> tuple[int, int] | None:
    if fd is None:
        return None
    try:
        return descriptor_identity_v1(fd)
    except OSError:
        return None


def _close(
    guards: tuple[int, int | None, int | None],
    anchors: tuple[int | None, int | None, int | None],
    value: OperationAdmissionLockResourcesV3 | None,
) -> None:
    root_guard_fd, lock_guard_fd, store_guard_fd = guards
    root_anchor_fd, lock_anchor_fd, store_anchor_fd = anchors
    if value is not None:
        pairs = (
            (value.store_fd, store_anchor_fd, value.store_identity),
            (value.lock_fd, lock_anchor_fd, value.lock_identity),
            (value.root_fd, root_anchor_fd, value.root_identity),
        )
        for public_fd, guard_fd, identity in pairs:
            close_guarded_witness_fd_v1(public_fd, guard_fd, identity)
    pairs = (
        (store_guard_fd, store_anchor_fd),
        (lock_guard_fd, lock_anchor_fd),
        (root_guard_fd, root_anchor_fd),
    )
    for guard_fd, anchor_fd in pairs:
        if anchor_fd is not None:
            close_guarded_witness_fd_v1(
                guard_fd, anchor_fd, _safe_identity(anchor_fd)
            )
    close_owned_fd_v1(store_anchor_fd, _safe_identity(store_anchor_fd))
    release_owned_lock_fd_v1(lock_anchor_fd, _safe_identity(lock_anchor_fd))
    close_owned_fd_v1(root_anchor_fd, _safe_identity(root_anchor_fd))
    if store_anchor_fd is None:
        close_owned_fd_v1(store_guard_fd, _safe_identity(store_guard_fd))
    if lock_anchor_fd is None:
        release_owned_lock_fd_v1(lock_guard_fd, _safe_identity(lock_guard_fd))
    if root_anchor_fd is None:
        close_owned_fd_v1(root_guard_fd, _safe_identity(root_guard_fd))


@contextlib.contextmanager
def guarded_operation_admission_lock_resources_v3(
    root_guard_fd: int,
    authority_id: str,
    validate_outer: Callable[[], None],
) -> Iterator[OperationAdmissionLockResourcesV3]:
    """Acquire one inner epoch and release only descriptors still owned."""
    lock_guard_fd = store_guard_fd = None
    root_anchor_fd = lock_anchor_fd = store_anchor_fd = None
    value = None
    owner_pid = os.getpid()
    cleanup_token = begin_inherited_fd_cleanup_v1()
    try:
        track_inherited_fd_v1(cleanup_token, root_guard_fd)
        lock_guard_fd, store_guard_fd, lease = _acquire(
            root_guard_fd, authority_id, validate_outer, cleanup_token
        )
        root_anchor_fd = _tracked_dup(root_guard_fd, cleanup_token)
        lock_anchor_fd = _tracked_dup(lock_guard_fd, cleanup_token)
        store_anchor_fd = _tracked_dup(store_guard_fd, cleanup_token)
        value = _resources(
            (root_guard_fd, lock_guard_fd, store_guard_fd),
            lease,
            cleanup_token,
        )
        yield value
    finally:
        if os.getpid() == owner_pid:
            cleanup = partial(
                _close,
                (root_guard_fd, lock_guard_fd, store_guard_fd),
                (root_anchor_fd, lock_anchor_fd, store_anchor_fd),
                value,
            )
            finish_inherited_fd_cleanup_v1(cleanup_token, cleanup)
        else:
            finish_inherited_fd_cleanup_v1(cleanup_token)
