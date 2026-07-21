"""Small fail-closed filesystem helpers for headless authority records."""

from __future__ import annotations

import contextlib
import fcntl
import os
import stat
from collections.abc import Iterator


class DurableFileError(RuntimeError):
    """An authority path or durable file violates the local safety contract."""


def exact_directory_entries(
    dir_fd: int, expected: set[str] | frozenset[str]
) -> bool:
    """Compare an expected set and fail on the first unknown entry."""
    valid = (
        type(expected) in {set, frozenset}
        and len(expected) <= 65_536
        and all(type(name) is str for name in expected)
    )
    if not valid:
        raise DurableFileError("expected directory closure is invalid")
    remaining = set(expected)
    try:
        with os.scandir(dir_fd) as entries:
            for entry in entries:
                if entry.name not in remaining:
                    return False
                remaining.remove(entry.name)
    except OSError as exc:
        raise DurableFileError("cannot inspect durable directory") from exc
    return not remaining


def bounded_directory_entries(dir_fd: int, limit: int) -> tuple[str, ...]:
    """Return sorted names only when their count is bounded."""
    if type(limit) is not int or not 0 <= limit <= 1_000_000:
        raise DurableFileError("durable directory entry limit is invalid")
    names = []
    try:
        with os.scandir(dir_fd) as entries:
            for entry in entries:
                if len(names) == limit:
                    raise DurableFileError(
                        "durable directory exceeds entry limit"
                    )
                names.append(entry.name)
    except OSError as exc:
        raise DurableFileError("cannot inspect durable directory") from exc
    return tuple(sorted(names))


def _dir_safe(info: os.stat_result) -> bool:
    return (
        stat.S_ISDIR(info.st_mode)
        and info.st_uid == os.geteuid()
        and stat.S_IMODE(info.st_mode) == 0o700
    )


def open_private_dir(path: str) -> int:
    """Open one canonical owned mode-0700 directory without symlinks."""
    if (
        type(path) is not str
        or not os.path.isabs(path)
        or os.path.realpath(path) != path
    ):
        raise DurableFileError(
            "authority directory must be canonical and symlink-free"
        )
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise DurableFileError(
            f"cannot safely open authority directory: {path}"
        ) from exc
    if _dir_safe(os.fstat(fd)):
        return fd
    os.close(fd)
    raise DurableFileError("authority directory must be owned mode 0700")


def open_private_child_dir(parent_fd: int, name: str) -> int:
    """Open one existing owned mode-0700 direct child without creating it."""
    if not name or "/" in name or name in {".", ".."}:
        raise DurableFileError("private child name is invalid")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(name, flags, dir_fd=parent_fd)
    except OSError as exc:
        raise DurableFileError(
            f"cannot safely open private child: {name}"
        ) from exc
    if _dir_safe(os.fstat(fd)):
        return fd
    os.close(fd)
    raise DurableFileError(f"private child {name} must be owned mode 0700")


def private_child_dir(parent_fd: int, name: str) -> int:
    """Create or reopen one owned mode-0700 direct child."""
    if not name or "/" in name or name in {".", ".."}:
        raise DurableFileError("private child name is invalid")
    try:
        os.mkdir(name, 0o700, dir_fd=parent_fd)
        os.chmod(name, 0o700, dir_fd=parent_fd, follow_symlinks=False)
        os.fsync(parent_fd)
    except FileExistsError:
        pass
    return open_private_child_dir(parent_fd, name)


def _open_create_or_existing(
    dir_fd: int, name: str, safe_flags: int, flags: int
) -> tuple[int, bool]:
    if flags & os.O_CREAT and not flags & os.O_EXCL:
        try:
            return (
                os.open(name, safe_flags | os.O_EXCL, 0o600, dir_fd=dir_fd),
                True,
            )
        except FileExistsError:
            return (
                os.open(name, safe_flags & ~os.O_EXCL, 0o600, dir_fd=dir_fd),
                False,
            )
    return os.open(name, safe_flags, 0o600, dir_fd=dir_fd), bool(
        flags & os.O_CREAT
    )


def open_private_file(dir_fd: int, name: str, flags: int) -> int:
    """Open an owned single-link mode-0600 file by directory handle."""
    safe_flags = (
        flags | os.O_NONBLOCK | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        fd, created = _open_create_or_existing(dir_fd, name, safe_flags, flags)
    except OSError as exc:
        raise DurableFileError(
            f"cannot safely open durable file: {name}"
        ) from exc
    if created:
        os.fchmod(fd, 0o600)
    info = os.fstat(fd)
    safe = (
        stat.S_ISREG(info.st_mode)
        and info.st_nlink == 1
        and info.st_uid == os.geteuid()
        and stat.S_IMODE(info.st_mode) == 0o600
    )
    if safe:
        return fd
    os.close(fd)
    raise DurableFileError(
        f"durable file {name} must be owned, private, and single-link"
    )


def assert_private_lock_identity(dir_fd: int, name: str, lock_fd: int) -> None:
    """Require a held private lock to remain the named single-link inode."""
    try:
        held = os.fstat(lock_fd)
        named = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except OSError as exc:
        raise DurableFileError(
            "durable lock identity cannot be observed"
        ) from exc
    identity = (held.st_dev, held.st_ino) == (named.st_dev, named.st_ino)
    safe = (
        stat.S_ISREG(held.st_mode)
        and held.st_nlink == 1
        and held.st_uid == os.geteuid()
        and stat.S_IMODE(held.st_mode) == 0o600
    )
    if not identity or not safe:
        raise DurableFileError("durable lock inode was replaced")


def _assert_root_identity(path: str, dir_fd: int) -> None:
    try:
        held = os.fstat(dir_fd)
        named = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise DurableFileError(
            "authority directory identity cannot be observed"
        ) from exc
    if (held.st_dev, held.st_ino) != (named.st_dev, named.st_ino):
        raise DurableFileError("authority directory inode was replaced")
    if not _dir_safe(held) or not _dir_safe(named):
        raise DurableFileError("authority directory is no longer private")


def write_all(fd: int, data: bytes) -> None:
    """Write every byte or fail."""
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise DurableFileError("zero-byte durable write")
        view = view[written:]


def _read_bounded(fd: int, limit: int) -> bytes:
    chunks, remaining = [], limit + 1
    while remaining:
        chunk = os.read(fd, min(1024 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_private_file(dir_fd: int, name: str, limit: int = 1_048_576) -> bytes:
    """Read one bounded authority record and reject oversized content."""
    fd = open_private_file(dir_fd, name, os.O_RDONLY | os.O_NONBLOCK)
    try:
        data = _read_bounded(fd, limit)
    finally:
        os.close(fd)
    if len(data) > limit:
        raise DurableFileError(f"durable file {name} exceeds its size limit")
    return data


def write_pending_replace(
    dir_fd: int, names: tuple[str, str], data: bytes
) -> None:
    """Flush pending bytes, replace final, then flush the directory."""
    pending, final = names
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = open_private_file(dir_fd, pending, flags)
    try:
        write_all(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(pending, final, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
    os.fsync(dir_fd)


@contextlib.contextmanager
def locked_private_dir(path: str, lock_name: str) -> Iterator[int]:
    """Hold an exclusive flock inside one private directory."""
    dir_fd = open_private_dir(path)
    lock_fd = None
    try:
        lock_fd = open_private_file(dir_fd, lock_name, os.O_CREAT | os.O_RDWR)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        os.fsync(dir_fd)
        assert_private_lock_identity(dir_fd, lock_name, lock_fd)
        _assert_root_identity(path, dir_fd)
        yield dir_fd
        assert_private_lock_identity(dir_fd, lock_name, lock_fd)
        _assert_root_identity(path, dir_fd)
    finally:
        if lock_fd is not None:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
        os.close(dir_fd)


@contextlib.contextmanager
def locked_existing_private_dir(path: str, lock_name: str) -> Iterator[int]:
    """Hold an existing lock without creating read-side state."""
    dir_fd = open_private_dir(path)
    lock_fd = None
    try:
        lock_fd = open_private_file(dir_fd, lock_name, os.O_RDWR)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        assert_private_lock_identity(dir_fd, lock_name, lock_fd)
        _assert_root_identity(path, dir_fd)
        yield dir_fd
        assert_private_lock_identity(dir_fd, lock_name, lock_fd)
        _assert_root_identity(path, dir_fd)
    finally:
        if lock_fd is not None:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
        os.close(dir_fd)
