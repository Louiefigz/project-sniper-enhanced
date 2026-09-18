"""Ephemeral descriptor-linked source identities, never persisted admission authority."""
from __future__ import annotations

import math
import os
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class SourceVerificationRuntime:
    """Borrow only the original cheap clock, not a recursive full-source guard."""

    remaining: Callable[[], float]

    def check(self) -> float:
        """Do not start a timer or replace the calling owner's work/cleanup scope."""
        if not callable(self.remaining):
            raise RuntimeError("source verification requires the original clock callback")
        value = self.remaining()
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise RuntimeError("source verification original clock is unavailable or expired")
        return float(value)


@dataclass(frozen=True)
class VerifiedSnapshotIdentity:
    """Actual hash-pass identity; a constructed dataclass is not source authority."""

    path: str
    sha256: str
    size_bytes: int
    stat_identity: tuple[int, ...]


def snapshot_stat_identity(info: os.stat_result) -> tuple[int, ...]:
    """Keep all nine source identity fields in the presenter-compatible ordering."""
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def check_verification_clock(runtime: SourceVerificationRuntime | None) -> None:
    """Legacy verification keeps its caller timer; opt-in capture borrows its clock."""
    if runtime is None:
        return
    if type(runtime) is not SourceVerificationRuntime:
        raise RuntimeError("source verification runtime is malformed")
    runtime.check()


def assert_verified_snapshots(rows: tuple[VerifiedSnapshotIdentity, ...],
                              runtime: SourceVerificationRuntime) -> None:
    """Recheck original identities cheaply, without adopting late stats or hashing again."""
    runtime.check()
    for row in rows:
        runtime.check()
        if type(row) is not VerifiedSnapshotIdentity or snapshot_stat_identity(os.lstat(row.path)) != row.stat_identity:
            raise RuntimeError("verified source snapshot identity changed after its original hash")
    runtime.check()
