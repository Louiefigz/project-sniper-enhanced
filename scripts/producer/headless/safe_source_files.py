"""Descriptor-relative, no-follow reads from one pinned source root."""
from __future__ import annotations

import os
import stat
import unicodedata

_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
_FILE_FLAGS = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
_MAX_FILE_BYTES = 64 * 1024 * 1024


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_uid,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _safe_relative(relative: str) -> tuple[str, ...]:
    valid = (isinstance(relative, str) and relative
             and not os.path.isabs(relative) and "\\" not in relative
             and unicodedata.normalize("NFC", relative) == relative
             and not any(ord(char) < 32 for char in relative))
    parts = relative.split("/") if valid else []
    if not valid or any(part in {"", ".", ".."} for part in parts):
        raise RuntimeError(f"render source path is not canonical: {relative!r}")
    return tuple(parts)


def _open_root(path: str) -> int:
    if not os.path.isabs(path) or os.path.realpath(path) != path:
        raise RuntimeError("render source root must be canonical and absolute")
    current = os.open("/", _DIR_FLAGS)
    try:
        for part in path.split("/")[1:]:
            child = os.open(part, _DIR_FLAGS, dir_fd=current)
            os.close(current)
            current = child
        return current
    except BaseException:
        os.close(current)
        raise


def _open_parent(root_fd: int, parts: tuple[str, ...]) -> int:
    current = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            child = os.open(part, _DIR_FLAGS, dir_fd=current)
            os.close(current)
            current = child
        return current
    except BaseException:
        os.close(current)
        raise


def _read_fd(fd: int, relative: str) -> bytes:
    before = os.fstat(fd)
    safe = (stat.S_ISREG(before.st_mode) and before.st_nlink == 1
            and before.st_uid == os.geteuid()
            and 0 <= before.st_size <= _MAX_FILE_BYTES)
    if not safe:
        raise RuntimeError(f"render source is not one bounded regular file: {relative}")
    chunks = []
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            break
        chunks.append(chunk)
    if _identity(before) != _identity(os.fstat(fd)):
        raise RuntimeError(f"render source changed while reading: {relative}")
    return b"".join(chunks)


def read_stable_owned_file(path: str, label: str) -> bytes:
    """Read one owned regular leaf through a stable no-follow descriptor."""
    fd = os.open(path, _FILE_FLAGS)
    try:
        return _read_fd(fd, label)
    finally:
        os.close(fd)


class PinnedSourceRoot:
    """Keep the source root inode open for the full capture transaction."""

    def __init__(self, path: str):
        self.path = path
        self.fd = _open_root(path)
        self.identity = _identity(os.fstat(self.fd))

    def read(self, relative: str) -> bytes:
        """Read a leaf without following any directory or leaf symlink."""
        parts = _safe_relative(relative)
        parent = _open_parent(self.fd, parts)
        try:
            leaf = os.open(parts[-1], _FILE_FLAGS, dir_fd=parent)
        finally:
            os.close(parent)
        try:
            return _read_fd(leaf, relative)
        finally:
            os.close(leaf)

    def assert_current(self) -> None:
        """Reject source-root replacement during the capture transaction."""
        current = os.stat(self.path, follow_symlinks=False)
        if self.identity != _identity(current):
            raise RuntimeError("render source root changed while sealing")

    def close(self) -> None:
        """Close the pinned root descriptor."""
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def __enter__(self) -> PinnedSourceRoot:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
