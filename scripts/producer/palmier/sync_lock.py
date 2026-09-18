"""Crash-safe process locks for Palmier sync-on-demand.

A sync holds per-dir and global ``/tmp`` flocks; same-dir contenders share a
one-slot plan-hash queue because Palmier is a singleton.
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from palmier.sync_lock_storage import (
    atomic_json as _atomic_json,
    mutex as _mutex,
    read_json as _read_json,
    remove as _remove,
    try_lock as _try_lock,
    unlock_close as _unlock_close,
    write_fd as _write_fd,
)

DIR_LOCK_NAME = ".palmier.sync.lock"
MUTEX_NAME = ".palmier.sync.mutex"
PENDING_NAME = ".palmier.sync.pending.json"
GLOBAL_LOCK_PATH = f"/tmp/palmier-sync-{os.getuid()}.lock"

class SyncLockState(str, Enum):
    """Result of a Palmier sync-lock acquisition attempt."""
    ACQUIRED = "acquired"
    QUEUED = "queued"
    WAITING = "waiting"


class SyncWaitReason(str, Enum):
    """Typed reasons for an acquisition that must wait."""
    ASSEMBLE_ACTIVE = "assemble_active"
    PALMIER_BUSY = "palmier_busy"


@dataclass(frozen=True)
class SyncLockResult:
    """Acquisition result returned to the push CLI."""

    state: SyncLockState
    plan_hash: str
    lease: SyncLock | None = None
    reason: SyncWaitReason | None = None
    holder_pid: int | None = None
    holder_out_dir: str | None = None

@dataclass
class _HeldFiles:
    dir_fd: int
    global_fd: int
    out_dir: str
    mutex_path: str
    pending_path: str


@dataclass(frozen=True)
class _AcquireRequest:
    out_dir: str
    plan_hash: str
    paths: dict[str, str]
    queue_if_busy: bool


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _pid_alive(pid: object) -> bool:
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _live_assemble_pid(out_dir: str) -> int | None:
    """Return a live assemble holder without modifying its marker."""
    lock_path = os.path.join(out_dir, ".assemble.lock")
    guard = _mutex(lock_path + ".mutex")
    try:
        pid = _read_json(lock_path).get("pid")
        return pid if _pid_alive(pid) else None
    finally:
        _unlock_close(guard)


class SyncLock:
    """Lease owning the per-directory and user-global Palmier flocks."""

    def __init__(self, plan_hash: str, token: str, held: _HeldFiles):
        self.out_dir = held.out_dir
        self.plan_hash = plan_hash
        self._token = token
        self._held = held
        self._active = True
        self._owner_pid = os.getpid()

    @classmethod
    def acquire(cls, out_dir: str, plan_hash: str,
                global_path: str | None = None,
                queue_if_busy: bool = True) -> SyncLockResult:
        """Acquire, optionally queue a mirror rerun, or return typed waiting."""
        out_dir = os.path.realpath(out_dir)
        if not os.path.isdir(out_dir):
            raise NotADirectoryError(out_dir)
        if not isinstance(plan_hash, str) or not plan_hash.strip():
            raise ValueError("plan_hash must be a non-empty string")
        paths = cls._paths(out_dir, global_path or GLOBAL_LOCK_PATH)
        mutex_fd = _mutex(paths["mutex"])
        request = _AcquireRequest(out_dir, plan_hash, paths, queue_if_busy)
        try:
            return cls._acquire_locked(request)
        finally:
            _unlock_close(mutex_fd)

    @classmethod
    def _acquire_locked(cls, request: _AcquireRequest) -> SyncLockResult:
        """Acquire both flocks while the directory metadata mutex is held."""
        out_dir, plan_hash = request.out_dir, request.plan_hash
        paths, queue_if_busy = request.paths, request.queue_if_busy
        dir_fd: int | None = None
        global_fd: int | None = None
        try:
            assemble_pid = _live_assemble_pid(out_dir)
            if assemble_pid is not None:
                return SyncLockResult(
                    SyncLockState.WAITING, plan_hash,
                    reason=SyncWaitReason.ASSEMBLE_ACTIVE,
                    holder_pid=assemble_pid)
            dir_fd, owner = _try_lock(paths["dir"])
            if dir_fd is None:
                if not queue_if_busy:
                    return SyncLockResult(
                        SyncLockState.WAITING, plan_hash,
                        reason=SyncWaitReason.PALMIER_BUSY,
                        holder_pid=owner.get("pid"),
                        holder_out_dir=owner.get("outDir"))
                cls._queue(paths["pending"], plan_hash, owner)
                return SyncLockResult(
                    SyncLockState.QUEUED, plan_hash,
                    holder_pid=owner.get("pid"),
                    holder_out_dir=owner.get("outDir"))
            global_fd, owner = _try_lock(paths["global"])
            if global_fd is None:
                _unlock_close(dir_fd)
                dir_fd = None
                return SyncLockResult(
                    SyncLockState.WAITING, plan_hash,
                    reason=SyncWaitReason.PALMIER_BUSY,
                    holder_pid=owner.get("pid"),
                    holder_out_dir=owner.get("outDir"))
            token = secrets.token_hex(16)
            held = _HeldFiles(dir_fd, global_fd, out_dir, paths["mutex"],
                              paths["pending"])
            lease = cls(plan_hash, token, held)
            _remove(paths["pending"])
            lease._write_owner()
            return SyncLockResult(SyncLockState.ACQUIRED, plan_hash, lease)
        except BaseException:
            _unlock_close(global_fd)
            _unlock_close(dir_fd)
            raise

    @staticmethod
    def _paths(out_dir: str, global_path: str) -> dict[str, str]:
        return {
            "dir": os.path.join(out_dir, DIR_LOCK_NAME),
            "mutex": os.path.join(out_dir, MUTEX_NAME),
            "pending": os.path.join(out_dir, PENDING_NAME),
            "global": global_path,
        }

    @staticmethod
    def _queue(path: str, plan_hash: str,
               owner: dict[str, Any]) -> None:
        _atomic_json(path, {
            "planHash": plan_hash,
            "ownerToken": owner.get("token"),
            "pid": os.getpid(),
            "queuedAt": _now(),
        })

    def _write_owner(self) -> None:
        owner = {"pid": os.getpid(), "token": self._token,
                 "outDir": self.out_dir, "planHash": self.plan_hash,
                 "acquiredAt": _now()}
        _write_fd(self._held.dir_fd, owner)
        _write_fd(self._held.global_fd, owner)

    def claim_pending(self) -> str | None:
        """Claim latest hash and retain locks; or atomically release if none."""
        if os.getpid() != self._owner_pid:
            raise RuntimeError("a forked process cannot claim its parent's lock")
        if not self._active:
            return None
        mutex_fd = _mutex(self._held.mutex_path)
        try:
            pending = _read_json(self._held.pending_path)
            valid = (pending.get("ownerToken") == self._token and
                     isinstance(pending.get("planHash"), str) and
                     bool(pending["planHash"].strip()))
            _remove(self._held.pending_path)
            if valid:
                self.plan_hash = pending["planHash"]
                self._write_owner()
                return self.plan_hash
            self._release_fds()
            return None
        finally:
            _unlock_close(mutex_fd)

    def release(self) -> None:
        """Force-release only this lease's fds; safe and idempotent."""
        if os.getpid() != self._owner_pid:
            raise RuntimeError("a forked process cannot release its parent's lock")
        if not self._active:
            return
        mutex_fd = _mutex(self._held.mutex_path)
        try:
            pending = _read_json(self._held.pending_path)
            if pending.get("ownerToken") == self._token:
                _remove(self._held.pending_path)
            self._release_fds()
        finally:
            _unlock_close(mutex_fd)

    def _release_fds(self) -> None:
        if not self._active:
            return
        _unlock_close(self._held.global_fd)
        _unlock_close(self._held.dir_fd)
        self._active = False

    def __enter__(self) -> SyncLock:
        return self

    def __exit__(self, _exc_type: object, _exc: object,
                 _traceback: object) -> None:
        self.release()
