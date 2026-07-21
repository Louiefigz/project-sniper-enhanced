"""Kernel-held single-controller ownership for one headless authority."""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import stat
from dataclasses import dataclass
from typing import Iterator

from .boot_identity import read_boot_id
from .durable_files import (
    open_private_dir,
    open_private_file,
    read_private_file,
    write_pending_replace,
)

LOCK_NAME = ".controller.lock"
IDENTITY_NAME = ".controller-lock.json"
_PENDING_IDENTITY = ".controller-lock.pending"


class ControllerOwnershipError(RuntimeError):
    """An authority is already controlled or its ownership proof is unsafe."""


@dataclass
class _LeaseState:
    authority_root: str
    root_fd: int
    lock_fd: int
    root_identity: tuple[int, int]
    lock_identity: tuple[int, int]
    owner_pid: int
    boot_id: str
    active: bool = True


class ControllerLease:
    """Opaque capability whose mutable state is revoked before unlock."""

    __slots__ = ("_state",)

    def __init__(self, state: _LeaseState):
        self._state = state


_LIVE_STATES: dict[int, _LeaseState] = {}


def _canonical(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=True, separators=(",", ":"),
                       sort_keys=True) + "\n").encode("ascii")


def _lock_record(root: os.stat_result, lock: os.stat_result) -> dict:
    return {"lockDevice": lock.st_dev, "lockInode": lock.st_ino,
            "rootDevice": root.st_dev, "rootInode": root.st_ino,
            "schemaVersion": 1}


def _read_record(root_fd: int) -> dict | None:
    try:
        os.stat(IDENTITY_NAME, dir_fd=root_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    raw = read_private_file(root_fd, IDENTITY_NAME)
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ControllerOwnershipError("controller lock identity is invalid") from exc
    if raw != _canonical(value):
        raise ControllerOwnershipError("controller lock identity is not canonical")
    return value


def _bind_lock_identity(root_fd: int, root: os.stat_result,
                        lock: os.stat_result) -> None:
    expected = _lock_record(root, lock)
    current = _read_record(root_fd)
    if current is None:
        write_pending_replace(
            root_fd, (_PENDING_IDENTITY, IDENTITY_NAME), _canonical(expected))
        return
    if current != expected:
        raise ControllerOwnershipError("controller lock identity was replaced")


def _path_identity(path: str) -> tuple[int, int]:
    info = os.stat(path, follow_symlinks=False)
    return info.st_dev, info.st_ino


def _safe_lock(info: os.stat_result) -> bool:
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and info.st_uid == os.geteuid()
            and stat.S_IMODE(info.st_mode) == 0o600)


def assert_controller_ownership(lease: ControllerLease,
                                authority_root: str) -> None:
    """Require the original live process, root inode, and bound lock inode."""
    state = lease._state
    if not state.active or _LIVE_STATES.get(id(state)) is not state:
        raise ControllerOwnershipError("controller lease is expired")
    if (state.authority_root != authority_root or state.owner_pid != os.getpid()
            or state.boot_id != read_boot_id()):
        raise ControllerOwnershipError("controller lease belongs to another owner")
    try:
        root_info = os.fstat(state.root_fd)
        lock_info = os.fstat(state.lock_fd)
        current_lock = os.stat(LOCK_NAME, dir_fd=state.root_fd,
                               follow_symlinks=False)
    except (OSError, ValueError) as exc:
        raise ControllerOwnershipError("controller lease is no longer live") from exc
    current = ((_path_identity(authority_root), (root_info.st_dev, root_info.st_ino),
                (current_lock.st_dev, current_lock.st_ino),
                (lock_info.st_dev, lock_info.st_ino)))
    expected = (state.root_identity, state.root_identity,
                state.lock_identity, state.lock_identity)
    if current != expected or not _safe_lock(lock_info):
        raise ControllerOwnershipError("controller root or lock pathname was replaced")


def _revoke(state: _LeaseState, inherited: bool = False) -> None:
    state.active = False
    _LIVE_STATES.pop(id(state), None)
    if not inherited:
        try:
            fcntl.flock(state.lock_fd, fcntl.LOCK_UN)
        except OSError:
            pass
    for fd in (state.lock_fd, state.root_fd):
        try:
            os.close(fd)
        except OSError:
            pass


def _after_fork_child() -> None:
    for state in tuple(_LIVE_STATES.values()):
        _revoke(state, inherited=True)


os.register_at_fork(after_in_child=_after_fork_child)


def _acquire_lock(root_fd: int, blocking: bool) -> int:
    lock_fd = open_private_file(root_fd, LOCK_NAME, os.O_CREAT | os.O_RDWR)
    operation = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
    try:
        fcntl.flock(lock_fd, operation)
    except BlockingIOError as exc:
        os.close(lock_fd)
        raise ControllerOwnershipError(
            "another controller already owns this authority") from exc
    return lock_fd


def _lease_state(authority_root: str, root_fd: int,
                 lock_fd: int) -> _LeaseState:
    root_info, lock_info = os.fstat(root_fd), os.fstat(lock_fd)
    _bind_lock_identity(root_fd, root_info, lock_info)
    return _LeaseState(
        authority_root, root_fd, lock_fd,
        (root_info.st_dev, root_info.st_ino),
        (lock_info.st_dev, lock_info.st_ino), os.getpid(), read_boot_id())


def _unlock_close(lock_fd: int) -> None:
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
    except OSError:
        pass
    os.close(lock_fd)


def _cleanup_acquisition(state: _LeaseState | None, root_fd: int,
                         lock_fd: int | None) -> None:
    if state is not None:
        _revoke(state)
        return
    if lock_fd is not None:
        _unlock_close(lock_fd)
    try:
        os.close(root_fd)
    except OSError:
        pass


@contextlib.contextmanager
def controller_ownership(authority_root: str,
                         blocking: bool = False) -> Iterator[ControllerLease]:
    """Hold exclusive authority ownership until the controller fully exits."""
    root_fd = open_private_dir(authority_root)
    state, lock_fd = None, None
    try:
        lock_fd = _acquire_lock(root_fd, blocking)
        state = _lease_state(authority_root, root_fd, lock_fd)
        _LIVE_STATES[id(state)] = state
        lease = ControllerLease(state)
        assert_controller_ownership(lease, authority_root)
        yield lease
    finally:
        _cleanup_acquisition(state, root_fd, lock_fd)
