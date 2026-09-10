"""Body-only remaining clocks and cheap held-file guards for publication seams.

The owner charges acquisition/verification before passing the remainder. This
worker cannot restore another process's monotonic epoch or renew the request.
Cleanup is separate owned termination work; it cannot authorize late success.
"""
from __future__ import annotations

import math
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path

from cut_preview_io import file_hash, real_directory
from guided_opening_execution import OpeningExecutionClock

MAX_BODY_WORK_SECONDS = 55 * 60


class BodyExecutionClock(OpeningExecutionClock):
    """One local monotonic budget plus an optional held original-wall watermark."""

    wall_deadline_ms: int | None = None
    previous_wall_ms: int | None = None

    def remaining(self) -> float:
        """A clock rollback or exhausted wall bound can only reduce permission."""
        remaining = super().remaining()
        if self.wall_deadline_ms is None:
            return remaining
        now = time.time_ns() // 1_000_000
        if now < self.previous_wall_ms or now >= self.wall_deadline_ms:
            self.end = min(self.end, time.monotonic())
            raise RuntimeError("body original wall clock rolled back or expired")
        self.previous_wall_ms = now
        return min(remaining, (self.wall_deadline_ms - now) / 1000)

    def bind_wall(self, deadline_ms: int, not_before_ms: int) -> None:
        """Bind once after control admission; never renew the actual entry budget."""
        if self.wall_deadline_ms is not None:
            raise RuntimeError("body original clock cannot be rebound")
        now = time.time_ns() // 1_000_000
        if now < not_before_ms or now >= deadline_ms:
            raise RuntimeError("body activation is future-dated or expired")
        self.end = min(self.end, time.monotonic() + (deadline_ms - now) / 1000)
        self.wall_deadline_ms, self.previous_wall_ms = deadline_ms, now
        self.remaining()


def body_clock(timeout: float) -> BodyExecutionClock:
    """Reuse phase/timer machinery with a separate explicit body admission ceiling."""
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= MAX_BODY_WORK_SECONDS:
        raise RuntimeError("body media requires a positive remaining budget at most55 minutes")
    return BodyExecutionClock(time.monotonic() + timeout)


def _identity(info: os.stat_result) -> tuple:
    """Cheap observed identity; whole source/decoded media checks stay separate."""
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


@dataclass(frozen=True)
class BodyHeldFile:
    """Initial exact-byte identity of one bounded immutable control-plane file."""

    path: Path
    sha256: str
    identity: tuple


def hold_body_file(path: Path, expected: str, maximum: int = 16 * 1024 * 1024) -> BodyHeldFile:
    """Capture actual bytes before using stat-only repeated publication guards."""
    real_directory(path.parent)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 < before.st_size <= maximum:
        raise RuntimeError("body held metadata is not a bounded single-link regular file")
    if file_hash(path, maximum) != expected or _identity(before) != _identity(path.lstat()):
        raise RuntimeError("body held metadata bytes changed")
    return BodyHeldFile(path, expected, _identity(before))


def assert_body_files(rows: tuple[BodyHeldFile, ...], clock: OpeningExecutionClock) -> None:
    """Check every file and shared ancestry without a full root walk per file.

    There is no cross-call cache. Every directory component is checked before
    and after every file identity sweep; exact full byte revalidation remains
    separate and unchanged. Stable directory metadata excludes mutable entry
    counts/timestamps so unrelated sibling creation is not a false conflict.
    """
    clock.remaining()
    parents = _parent_paths(rows)
    before = _directory_states(parents)
    for row in rows:
        if _identity(row.path.lstat()) != row.identity:
            raise RuntimeError("body held metadata identity changed during owned execution")
    if _directory_states(parents) != before:
        raise RuntimeError("body held directory ancestry changed during owned execution")
    clock.remaining()


def _parent_paths(rows: tuple[BodyHeldFile, ...]) -> tuple[Path, ...]:
    """Expand canonical lexical ancestry once, with parent-before-child order."""
    parents = set()
    for row in rows:
        if row.path.anchor != "/" or ".." in row.path.parts:
            raise RuntimeError("body held metadata path is not canonical")
        parents.update(row.path.parents)
    return tuple(sorted(parents, key=lambda item: (len(item.parts), str(item))))


def _directory_states(parents: tuple[Path, ...]) -> tuple[tuple, ...]:
    """Fresh no-link/type checks for ALL components, never a persisted shortcut."""
    result = []
    for parent in parents:
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise RuntimeError("body held directory ancestry is unsafe")
        result.append((info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid))
    return tuple(result)


def revalidate_body_files(rows: tuple[BodyHeldFile, ...], clock: OpeningExecutionClock) -> None:
    """Final exact bounded control-file bytes, not a source/admission shortcut."""
    assert_body_files(rows, clock)
    for row in rows:
        clock.remaining()
        if file_hash(row.path, row.identity[5]) != row.sha256:
            raise RuntimeError("body held metadata bytes changed during owned execution")
    assert_body_files(rows, clock)
