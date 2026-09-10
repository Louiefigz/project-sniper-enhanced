"""Immutable no-follow snapshots for untrusted external media."""
from __future__ import annotations

import hashlib
import os
import stat
import uuid
from dataclasses import dataclass
from typing import Callable

from .external_media_verification import (
    SourceVerificationRuntime, VerifiedSnapshotIdentity, check_verification_clock, snapshot_stat_identity,
)

# Admission class bound for one untrusted external media file. Raised from
# 8 GiB to 16 GiB on 2026-09-07 to admit the real long-form source class
# (C0679.MP4: 10,280,473,262 bytes, 834 s 4K 23.976 XAVC-S). The snapshot is
# a chunked copy with a running SHA-256, so the cost is disk plus one pass
# (measured on that source in the qualification ledger), never memory.
MAX_EXTERNAL_MEDIA_BYTES = 16 * 1024 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class ExternalMediaSnapshot:
    """One content-addressed regular file captured from a stable source inode."""

    path: str
    sha256: str
    size_bytes: int
    source_device: int
    source_inode: int


def _source_fd(path: str) -> int:
    """Open one safe source leaf and close on every failed acquisition path."""
    flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
             | getattr(os, "O_NONBLOCK", 0))
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or not 0 < info.st_size <= MAX_EXTERNAL_MEDIA_BYTES):
            raise RuntimeError("external media must be one bounded regular file")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _destination_fd(path: str) -> int:
    """Create only a new private snapshot stage with the historical file mode."""
    flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL
             | getattr(os, "O_NOFOLLOW", 0))
    fd = os.open(path, flags, 0o600)
    os.fchmod(fd, 0o600)
    return fd


def _write_chunk(destination_fd: int, chunk: bytes) -> None:
    """Write the entire chunk or fail rather than publishing partial copied bytes."""
    view = memoryview(chunk)
    while view:
        written = os.write(destination_fd, view)
        if written <= 0:
            raise RuntimeError("external media snapshot write stalled")
        view = view[written:]


def _copy(source_fd: int, destination_fd: int) -> tuple[str, int]:
    """Preserve the existing bounded snapshot copy and its single running digest."""
    digest = hashlib.sha256()
    size = 0
    while True:
        chunk = os.read(source_fd, CHUNK_BYTES)
        if not chunk:
            break
        size += len(chunk)
        if size > MAX_EXTERNAL_MEDIA_BYTES:
            raise RuntimeError("external media exceeded its snapshot bound")
        digest.update(chunk)
        _write_chunk(destination_fd, chunk)
    os.fsync(destination_fd)
    return digest.hexdigest(), size


def _same_source(before: os.stat_result, after: os.stat_result) -> bool:
    """Compare the original ingress copy's existing endpoint identity fields."""
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    return all(getattr(before, key) == getattr(after, key) for key in fields)


def _hash_descriptor(fd: int, maximum: int = MAX_EXTERNAL_MEDIA_BYTES,
                     runtime: SourceVerificationRuntime | None = None) -> tuple[str, int]:
    """Hash the existing descriptor once, bounding growth and the original work clock."""
    digest = hashlib.sha256()
    size = 0
    while True:
        check_verification_clock(runtime)
        chunk = os.read(fd, CHUNK_BYTES)
        if not chunk:
            return digest.hexdigest(), size
        size += len(chunk)
        if size > maximum:
            raise RuntimeError("content-addressed external media snapshot is corrupt or grew during verification")
        digest.update(chunk)


def _verify_snapshot(path: str, expected_hash: str, expected_size: int,
                     runtime: SourceVerificationRuntime | None = None) -> VerifiedSnapshotIdentity:
    """Retain same-FD hash/stat identity, never attach a late path stat to a known SHA."""
    check_verification_clock(runtime)
    fd = _source_fd(path)
    try:
        before = snapshot_stat_identity(os.fstat(fd))
        if before != snapshot_stat_identity(os.lstat(path)) or before[6] != expected_size:
            raise RuntimeError("content-addressed external media snapshot is corrupt or changed before verification")
        observed_hash, size = _hash_descriptor(fd, expected_size, runtime)
        check_verification_clock(runtime)
        if before != snapshot_stat_identity(os.fstat(fd)) or before != snapshot_stat_identity(os.lstat(path)):
            raise RuntimeError("content-addressed external media snapshot identity changed during verification")
        if size != expected_size or observed_hash != expected_hash:
            raise RuntimeError("content-addressed external media snapshot is corrupt")
        check_verification_clock(runtime)
        return VerifiedSnapshotIdentity(path, observed_hash, size, before)
    finally:
        os.close(fd)


def verify_external_media_snapshot(snapshot: ExternalMediaSnapshot) -> None:
    """Reobserve the immutable snapshot's bytes immediately around decode."""
    _verify_snapshot(snapshot.path, snapshot.sha256, snapshot.size_bytes)


def observe_external_media_snapshot(snapshot: ExternalMediaSnapshot,
                                    runtime: SourceVerificationRuntime) -> VerifiedSnapshotIdentity:
    """Opt-in return of the identity from the original verification pass, not another hash."""
    return _verify_snapshot(snapshot.path, snapshot.sha256, snapshot.size_bytes, runtime)


def _publish(stage: str, store: str, digest: str, size: int) -> str:
    """Publish the original content address without replacing an existing snapshot."""
    destination = os.path.join(store, f"{digest}.media")
    try:
        os.link(stage, destination, follow_symlinks=False)
        os.unlink(stage)
        directory_fd = os.open(store, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except FileExistsError:
        _verify_snapshot(destination, digest, size)
    return destination


def capture_external_media_snapshot(
    source: str,
    store_root: str,
    after_copy: Callable[[], None] | None = None,
) -> ExternalMediaSnapshot:
    """Copy one stable source inode and publish only its full-byte identity."""
    store = os.path.abspath(store_root)
    try:
        store_info = os.lstat(store)
    except OSError as exc:
        raise RuntimeError(
            "external media snapshot store must be a real directory") from exc
    if not stat.S_ISDIR(store_info.st_mode) or stat.S_ISLNK(store_info.st_mode):
        raise RuntimeError("external media snapshot store must be a real directory")
    source_fd = _source_fd(source)
    stage = os.path.join(store, f".snapshot-{uuid.uuid4().hex}.tmp")
    destination_fd = -1
    try:
        before = os.fstat(source_fd)
        destination_fd = _destination_fd(stage)
        digest, size = _copy(source_fd, destination_fd)
        os.close(destination_fd)
        destination_fd = -1
        if after_copy:
            after_copy()
        after = os.fstat(source_fd)
        if not _same_source(before, after):
            raise RuntimeError("external media changed during snapshot capture")
        destination = _publish(stage, store, digest, size)
        _verify_snapshot(destination, digest, size)
        return ExternalMediaSnapshot(
            destination, digest, size, before.st_dev, before.st_ino)
    finally:
        os.close(source_fd)
        if destination_fd >= 0:
            os.close(destination_fd)
        try:
            os.unlink(stage)
        except FileNotFoundError:
            pass
