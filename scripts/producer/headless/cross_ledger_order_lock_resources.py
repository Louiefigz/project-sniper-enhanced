"""Guarded descriptor lifecycle for the cross-ledger order lock."""

from __future__ import annotations

import contextlib
import fcntl
import os
from collections.abc import Iterator
from dataclasses import dataclass
from functools import partial

from .active_fence_lock import (
    ActiveFenceLockV1,
    validate_active_fence_lock_v1,
)
from .durable_files import open_private_file
from .exclusive_lock_lease import (
    ExclusiveLockLeaseError,
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

CROSS_LEDGER_ORDER_LOCK_NAME = ".cross-ledger-order-v1.lock"


@dataclass(frozen=True)
class CrossLedgerOrderLockResourcesV1:
    """Private guards plus public duplicate descriptors for one acquisition."""

    root_guard_fd: int
    lock_guard_fd: int
    root_fd: int
    lock_fd: int
    root_identity: tuple[int, int]
    lock_identity: tuple[int, int]
    lease_token: bytes


def _safe_identity(fd: int | None) -> tuple[int, int] | None:
    if fd is None:
        return None
    try:
        return descriptor_identity_v1(fd)
    except OSError:
        return None


def _close_resources(
    guards: tuple[int, int | None],
    anchors: tuple[int | None, int | None],
    value: CrossLedgerOrderLockResourcesV1 | None,
) -> None:
    root_guard_fd, lock_guard_fd = guards
    root_anchor_fd, lock_anchor_fd = anchors
    root_identity = _safe_identity(root_anchor_fd)
    lock_identity = _safe_identity(lock_anchor_fd)
    if value is not None:
        close_guarded_witness_fd_v1(
            value.lock_fd, lock_anchor_fd, value.lock_identity
        )
        close_guarded_witness_fd_v1(
            value.root_fd, root_anchor_fd, value.root_identity
        )
    if lock_anchor_fd is None:
        release_owned_lock_fd_v1(lock_guard_fd, _safe_identity(lock_guard_fd))
    else:
        close_guarded_witness_fd_v1(
            lock_guard_fd, lock_anchor_fd, lock_identity
        )
        release_owned_lock_fd_v1(lock_anchor_fd, lock_identity)
    if root_anchor_fd is None:
        close_owned_fd_v1(root_guard_fd, _safe_identity(root_guard_fd))
    else:
        close_guarded_witness_fd_v1(
            root_guard_fd, root_anchor_fd, root_identity
        )
        close_owned_fd_v1(root_anchor_fd, root_identity)


def _validate_parent(root_fd: int, parent: ActiveFenceLockV1 | None) -> None:
    if parent is None:
        return
    validate_active_fence_lock_v1(parent)
    if descriptor_identity_v1(root_fd) != parent.root_identity:
        raise ExclusiveLockLeaseError("cross lock root left publisher root")


def _acquire(
    root_fd: int,
    create: bool,
    parent: ActiveFenceLockV1 | None,
    cleanup_token: object,
) -> tuple[int, bytes]:
    _validate_parent(root_fd, parent)
    flags = (os.O_CREAT if create else 0) | os.O_RDWR
    lock_fd = create_tracked_fd_v1(
        cleanup_token,
        lambda: open_private_file(
            root_fd, CROSS_LEDGER_ORDER_LOCK_NAME, flags
        ),
    )
    try:
        _validate_parent(root_fd, parent)
        if create:
            os.fsync(root_fd)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        _validate_parent(root_fd, parent)
        lease = install_exclusive_lock_lease_v1(
            root_fd, lock_fd, CROSS_LEDGER_ORDER_LOCK_NAME
        )
        _validate_parent(root_fd, parent)
        return lock_fd, lease
    except BaseException:
        close_tracked_fd_v1(cleanup_token, lock_fd)
        raise


def _tracked_dup(fd: int, cleanup_token: object) -> int:
    return create_tracked_fd_v1(cleanup_token, lambda: os.dup(fd))


def _resources(
    root_guard_fd: int,
    lock_guard_fd: int,
    lease: bytes,
    cleanup_token: object,
) -> CrossLedgerOrderLockResourcesV1:
    root_fd = _tracked_dup(root_guard_fd, cleanup_token)
    lock_fd = None
    try:
        lock_fd = _tracked_dup(lock_guard_fd, cleanup_token)
        return CrossLedgerOrderLockResourcesV1(
            root_guard_fd,
            lock_guard_fd,
            root_fd,
            lock_fd,
            descriptor_identity_v1(root_guard_fd),
            descriptor_identity_v1(lock_guard_fd),
            lease,
        )
    except BaseException:
        if lock_fd is not None:
            close_tracked_fd_v1(cleanup_token, lock_fd)
        close_tracked_fd_v1(cleanup_token, root_fd)
        raise


@contextlib.contextmanager
def guarded_cross_ledger_order_lock_resources_v1(
    root_guard_fd: int,
    create: bool,
    parent: ActiveFenceLockV1 | None,
) -> Iterator[CrossLedgerOrderLockResourcesV1]:
    """Acquire one epoch and safely release only descriptors still owned."""
    lock_guard_fd = None
    root_anchor_fd = lock_anchor_fd = None
    value = None
    owner_pid = os.getpid()
    cleanup_token = begin_inherited_fd_cleanup_v1()
    try:
        track_inherited_fd_v1(cleanup_token, root_guard_fd)
        lock_guard_fd, lease = _acquire(
            root_guard_fd, create, parent, cleanup_token
        )
        root_anchor_fd = _tracked_dup(root_guard_fd, cleanup_token)
        lock_anchor_fd = _tracked_dup(lock_guard_fd, cleanup_token)
        value = _resources(root_guard_fd, lock_guard_fd, lease, cleanup_token)
        yield value
    finally:
        if os.getpid() == owner_pid:
            cleanup = partial(
                _close_resources,
                (root_guard_fd, lock_guard_fd),
                (root_anchor_fd, lock_anchor_fd),
                value,
            )
            finish_inherited_fd_cleanup_v1(cleanup_token, cleanup)
        else:
            finish_inherited_fd_cleanup_v1(cleanup_token)
