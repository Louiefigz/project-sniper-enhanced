"""Closure-owned descriptors for one publisher-mutex acquisition."""

from __future__ import annotations

import contextlib
import fcntl
import os
from collections.abc import Iterator
from dataclasses import dataclass
from functools import partial

from .durable_files import open_private_dir, open_private_file
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
)

PUBLISH_MUTEX_NAME = ".publish.mutex"


@dataclass(frozen=True)
class ActiveFenceLockResourcesV1:
    """Validation guards and public duplicates; cleanup anchors stay hidden."""

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
    except (OSError, TypeError, ValueError):
        return None


def _tracked_dup(fd: int, cleanup_token: object) -> int:
    return create_tracked_fd_v1(cleanup_token, lambda: os.dup(fd))


def _open_guards(
    authority_root: str, create: bool, cleanup_token: object
) -> tuple[int, int, bytes]:
    root_fd = create_tracked_fd_v1(
        cleanup_token, lambda: open_private_dir(authority_root)
    )
    lock_fd = None
    try:
        flags = os.O_RDWR | (os.O_CREAT if create else 0)
        lock_fd = create_tracked_fd_v1(
            cleanup_token,
            lambda: open_private_file(root_fd, PUBLISH_MUTEX_NAME, flags),
        )
        if create:
            os.fsync(root_fd)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        lease = install_exclusive_lock_lease_v1(
            root_fd, lock_fd, PUBLISH_MUTEX_NAME
        )
        return root_fd, lock_fd, lease
    except BaseException:
        if lock_fd is not None:
            close_tracked_fd_v1(cleanup_token, lock_fd)
        close_tracked_fd_v1(cleanup_token, root_fd)
        raise


def _build_resources(
    guards: tuple[int, int], lease: bytes, cleanup_token: object
) -> ActiveFenceLockResourcesV1:
    root_guard_fd, lock_guard_fd = guards
    root_fd = _tracked_dup(root_guard_fd, cleanup_token)
    lock_fd = None
    try:
        lock_fd = _tracked_dup(lock_guard_fd, cleanup_token)
        return ActiveFenceLockResourcesV1(
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


def _close_resources(
    guards: tuple[int | None, int | None],
    anchors: tuple[int | None, int | None],
    value: ActiveFenceLockResourcesV1 | None,
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
    if lock_anchor_fd is not None:
        close_guarded_witness_fd_v1(
            lock_guard_fd, lock_anchor_fd, lock_identity
        )
        release_owned_lock_fd_v1(lock_anchor_fd, lock_identity)
    else:
        release_owned_lock_fd_v1(lock_guard_fd, _safe_identity(lock_guard_fd))
    if root_anchor_fd is not None:
        close_guarded_witness_fd_v1(
            root_guard_fd, root_anchor_fd, root_identity
        )
        close_owned_fd_v1(root_anchor_fd, root_identity)
    else:
        close_owned_fd_v1(root_guard_fd, _safe_identity(root_guard_fd))


@contextlib.contextmanager
def guarded_active_fence_lock_resources_v1(
    authority_root: str, create: bool
) -> Iterator[ActiveFenceLockResourcesV1]:
    """Acquire guards and retain unshared anchors for exact parent cleanup."""
    owner_pid = os.getpid()
    cleanup_token = begin_inherited_fd_cleanup_v1()
    root_guard_fd = lock_guard_fd = None
    root_anchor_fd = lock_anchor_fd = None
    value = None
    try:
        root_guard_fd, lock_guard_fd, lease = _open_guards(
            authority_root, create, cleanup_token
        )
        root_anchor_fd = _tracked_dup(root_guard_fd, cleanup_token)
        lock_anchor_fd = _tracked_dup(lock_guard_fd, cleanup_token)
        value = _build_resources(
            (root_guard_fd, lock_guard_fd), lease, cleanup_token
        )
        yield value
    finally:
        if owner_pid == os.getpid():
            cleanup = partial(
                _close_resources,
                (root_guard_fd, lock_guard_fd),
                (root_anchor_fd, lock_anchor_fd),
                value,
            )
            finish_inherited_fd_cleanup_v1(cleanup_token, cleanup)
        else:
            finish_inherited_fd_cleanup_v1(cleanup_token)
