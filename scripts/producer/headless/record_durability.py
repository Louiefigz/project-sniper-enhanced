"""Small fsync barriers for already-validated private records."""

from __future__ import annotations

import os
import stat

from .durable_files import DurableFileError, open_private_file


def assert_named_private_directory_identity(
    parent_fd: int, name: str, child_fd: int
) -> None:
    """Require a held child directory to remain the named child inode."""
    try:
        held = os.fstat(child_fd)
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as exc:
        raise DurableFileError(
            "durable record directory identity cannot be observed"
        ) from exc
    if (held.st_dev, held.st_ino) != (named.st_dev, named.st_ino):
        raise DurableFileError("durable record directory was replaced")


def assert_named_private_file_identity(
    parent_fd: int, name: str, child_fd: int
) -> None:
    """Require a held private file to remain its safe named inode."""
    try:
        held = os.fstat(child_fd)
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as exc:
        raise DurableFileError(
            "durable record file identity cannot be observed"
        ) from exc
    safe = (
        stat.S_ISREG(held.st_mode)
        and held.st_nlink == 1
        and held.st_uid == os.geteuid()
        and stat.S_IMODE(held.st_mode) == 0o600
    )
    if (held.st_dev, held.st_ino) != (
        named.st_dev,
        named.st_ino,
    ) or not safe:
        raise DurableFileError("durable record file was replaced")


def _file_snapshot(fd: int) -> tuple[int, ...]:
    info = os.fstat(fd)
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_uid,
        info.st_gid,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _read_bounded_fd(fd: int, limit: int) -> bytes:
    os.lseek(fd, 0, os.SEEK_SET)
    chunks, remaining = [], limit + 1
    while remaining:
        chunk = os.read(fd, min(1024 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    raw = b"".join(chunks)
    if len(raw) > limit:
        raise DurableFileError("durable record file exceeds its size limit")
    return raw


def read_stable_private_fd(fd: int, limit: int) -> bytes:
    """Read the same pinned private inode twice without metadata drift."""
    try:
        before = _file_snapshot(fd)
        first = _read_bounded_fd(fd, limit)
        middle = _file_snapshot(fd)
        second = _read_bounded_fd(fd, limit)
        after = _file_snapshot(fd)
    except OSError as exc:
        raise DurableFileError("durable record file cannot be read") from exc
    if before != middle or middle != after or first != second:
        raise DurableFileError("durable record file changed during read")
    return first


def fsync_read_stable_private_fd(
    fd: int, limit: int
) -> tuple[bytes, tuple[int, ...]]:
    """Flush and read one inode without allowing metadata drift."""
    try:
        before = _file_snapshot(fd)
        os.fsync(fd)
        raw = read_stable_private_fd(fd, limit)
        after = _file_snapshot(fd)
    except OSError as exc:
        raise DurableFileError(
            "durable record file cannot be flushed"
        ) from exc
    if before != after:
        raise DurableFileError("durable record file changed across flush")
    return raw, after


def assert_private_file_snapshot(fd: int, expected: tuple[int, ...]) -> None:
    """Require a pinned file to retain its post-flush metadata snapshot."""
    try:
        observed = _file_snapshot(fd)
    except OSError as exc:
        raise DurableFileError(
            "durable record file snapshot cannot be observed"
        ) from exc
    if observed != expected:
        raise DurableFileError("durable record file changed after flush")


def fsync_private_file(dir_fd: int, name: str) -> None:
    """Flush one existing safe regular file opened relative to its directory."""
    fd = open_private_file(dir_fd, name, os.O_RDONLY | os.O_NONBLOCK)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
