"""Descriptor-relative deletion primitives for abandoned pending records."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable

from .durable_files import (
    DurableFileError,
    exact_directory_entries,
    open_private_child_dir,
    open_private_file,
)


class PendingCleanupFileError(RuntimeError):
    """An abandoned pending node cannot be safely removed."""


PendingFileValidator = Callable[[bytes], None]


def _stable_file_metadata(info: os.stat_result) -> tuple[int, ...]:
    """Exclude link count and ctime, which change on a correct unlink."""
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_gid,
        info.st_size,
        info.st_mtime_ns,
    )


def _assert_named_unlink_target(
    parent_fd: int, name: str, fd: int, baseline: os.stat_result
) -> None:
    """Require the validated descriptor to remain the exact named file."""
    try:
        held = os.fstat(fd)
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as exc:
        raise PendingCleanupFileError(
            "pending node identity cannot be reobserved"
        ) from exc
    expected = _stable_file_metadata(baseline)
    same = (
        _stable_file_metadata(held) == expected
        and _stable_file_metadata(named) == expected
        and held.st_nlink == 1
        and named.st_nlink == 1
    )
    if not same:
        raise PendingCleanupFileError("pending file changed before unlink")


def _read_pinned(fd: int, max_bytes: int) -> bytes:
    os.lseek(fd, 0, os.SEEK_SET)
    chunks, remaining = [], max_bytes + 1
    while remaining:
        chunk = os.read(fd, min(1024 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _validate_pinned(
    fd: int,
    baseline: os.stat_result,
    max_bytes: int,
    validator: PendingFileValidator | None,
) -> None:
    if validator is None:
        return
    raw = _read_pinned(fd, max_bytes)
    if len(raw) != baseline.st_size or len(raw) > max_bytes:
        raise PendingCleanupFileError("pending file bytes changed")
    validator(raw)


def remove_private_pending_file(
    parent_fd: int,
    name: str,
    max_bytes: int,
    validator: PendingFileValidator | None = None,
) -> None:
    """Validate and unlink one pinned private file with post-unlink proof."""
    if type(max_bytes) is not int or not 0 <= max_bytes <= 1_073_741_824:
        raise PendingCleanupFileError("pending file bound is invalid")
    if validator is not None and not callable(validator):
        raise PendingCleanupFileError("pending file validator is invalid")
    try:
        fd = open_private_file(parent_fd, name, os.O_RDONLY)
        try:
            info = os.fstat(fd)
            safe = (
                stat.S_ISREG(info.st_mode)
                and info.st_nlink == 1
                and info.st_uid == os.geteuid()
                and stat.S_IMODE(info.st_mode) == 0o600
                and info.st_size <= max_bytes
            )
            if not safe:
                raise PendingCleanupFileError("pending file is unsafe")
            _assert_named_unlink_target(parent_fd, name, fd, info)
            _validate_pinned(fd, info, max_bytes, validator)
            _assert_named_unlink_target(parent_fd, name, fd, info)
            os.unlink(name, dir_fd=parent_fd)
            after = os.fstat(fd)
            if after.st_nlink != 0 or _stable_file_metadata(
                after
            ) != _stable_file_metadata(info):
                raise PendingCleanupFileError(
                    "pending file unlink identity is unproven"
                )
            os.fsync(parent_fd)
        finally:
            os.close(fd)
    except PendingCleanupFileError:
        raise
    except (DurableFileError, OSError) as exc:
        raise PendingCleanupFileError(
            "pending file cannot be removed"
        ) from exc


def remove_empty_private_pending_dir(parent_fd: int, name: str) -> None:
    """Remove one pinned empty owned mode-0700 directory."""
    try:
        fd = open_private_child_dir(parent_fd, name)
        try:
            if not exact_directory_entries(fd, frozenset()):
                raise PendingCleanupFileError("pending directory is not empty")
            if not _same_named_directory(parent_fd, name, fd):
                raise PendingCleanupFileError("pending directory changed")
            os.rmdir(name, dir_fd=parent_fd)
            os.fsync(parent_fd)
        finally:
            os.close(fd)
    except PendingCleanupFileError:
        raise
    except (DurableFileError, OSError) as exc:
        raise PendingCleanupFileError(
            "pending directory cannot be removed"
        ) from exc


def _same_named_directory(parent_fd: int, name: str, fd: int) -> bool:
    try:
        opened = os.fstat(fd)
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as exc:
        raise PendingCleanupFileError(
            "pending node identity cannot be reobserved"
        ) from exc
    return (opened.st_dev, opened.st_ino) == (named.st_dev, named.st_ino)
