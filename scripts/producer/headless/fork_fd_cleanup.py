"""Single at-fork cleanup registry for live lock descriptors."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable

_LIVE_FD_GROUPS: dict[object, set[int]] = {}
_CHILD_CLEANUPS: list[Callable[[], None]] = []
_REGISTRY_LOCK = threading.Lock()


def begin_inherited_fd_cleanup_v1() -> object:
    """Create one process-local group before acquiring any descriptor."""
    token = object()
    with _REGISTRY_LOCK:
        _LIVE_FD_GROUPS[token] = set()
    return token


def track_inherited_fd_v1(token: object, fd: int) -> int:
    """Track a newly owned descriptor and return it for inline use."""
    with _REGISTRY_LOCK:
        group = _LIVE_FD_GROUPS.get(token)
        if group is None or type(fd) is not int or fd < 0:
            raise RuntimeError("inherited descriptor cleanup group is invalid")
        group.add(fd)
    return fd


def create_tracked_fd_v1(token: object, create: Callable[[], int]) -> int:
    """Create and register one FD without a concurrent-fork gap."""
    with _REGISTRY_LOCK:
        fd = create()
        group = _LIVE_FD_GROUPS.get(token)
        if group is None:
            os.close(fd)
            raise RuntimeError("inherited descriptor cleanup group is invalid")
        group.add(fd)
        return fd


def close_tracked_fd_v1(token: object, fd: int) -> None:
    """Close and forget one FD while fork is excluded."""
    with _REGISTRY_LOCK:
        group = _LIVE_FD_GROUPS.get(token)
        if group is not None:
            group.discard(fd)
        try:
            os.close(fd)
        except OSError:
            pass


def finish_inherited_fd_cleanup_v1(
    token: object, cleanup: Callable[[], None] | None = None
) -> None:
    """Forget a group only after its parent-side teardown has completed."""
    with _REGISTRY_LOCK:
        try:
            if cleanup is not None:
                cleanup()
        finally:
            _LIVE_FD_GROUPS.pop(token, None)


def register_child_cleanup_v1(cleanup: Callable[[], None]) -> None:
    """Register one module-level child cleanup, never one per acquisition."""
    with _REGISTRY_LOCK:
        _CHILD_CLEANUPS.append(cleanup)


def _before_fork() -> None:
    _REGISTRY_LOCK.acquire()


def _after_fork_parent() -> None:
    _REGISTRY_LOCK.release()


def _after_fork_child() -> None:
    try:
        inherited = {fd for group in _LIVE_FD_GROUPS.values() for fd in group}
        _LIVE_FD_GROUPS.clear()
        for cleanup in _CHILD_CLEANUPS:
            cleanup()
        for fd in sorted(inherited, reverse=True):
            try:
                os.close(fd)
            except OSError:
                pass
    finally:
        _REGISTRY_LOCK.release()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(
        before=_before_fork,
        after_in_parent=_after_fork_parent,
        after_in_child=_after_fork_child,
    )
