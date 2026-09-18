"""New-only picture bytes anchored to held directory/file descriptors.

FFmpeg receives only the reserved regular-file descriptor. Renaming an ancestor
cannot redirect its output into retained opening artifacts or any other tree.
Changed names still fail readback; this does not protect against hostile writers
already holding the same inode or qualify encoded video content.
"""
from __future__ import annotations

import hashlib
import os
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Protocol

from cut_preview_io import real_directory
from opening_prefix_contract import HeldPrefixInput, MAX_INPUT_BYTES, PrefixOracleError


class RemainingDeadline(Protocol):
    """The owning invocation's decreasing allowance, not a new media budget."""

    def remaining(self) -> float:
        """Return current remaining seconds or raise on expiry."""
        ...


def _directory_identity(info: os.stat_result) -> tuple:
    return info.st_dev, info.st_ino, info.st_mode, info.st_uid


def _file_identity(info: os.stat_result) -> tuple:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


@dataclass(frozen=True)
class HeldPictureDirectory:
    """The original private directory, retained across the whole oracle/encode."""

    path: Path
    descriptor: int
    identity: tuple

    def assert_current(self) -> None:
        """Reject changed names before and after work, not as the write confinement."""
        real_directory(self.path.parent)
        if _directory_identity(os.fstat(self.descriptor)) != self.identity \
                or _directory_identity(self.path.parent.lstat()) != self.identity:
            raise PrefixOracleError("prefix output directory identity changed")


@dataclass(frozen=True)
class HeldPictureOutput:
    """One exclusively created regular file; the caller closes it after readback."""

    directory: HeldPictureDirectory
    descriptor: int
    inode: tuple[int, int]

    def observe(self, deadline: RemainingDeadline) -> HeldPrefixInput:
        """Bind actual output bytes without claiming frame/decode/audio approval."""
        deadline.remaining()
        self.directory.assert_current()
        os.fsync(self.descriptor)
        before = os.fstat(self.descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 \
                or (before.st_dev, before.st_ino) != self.inode or not 0 < before.st_size <= MAX_INPUT_BYTES:
            raise PrefixOracleError("prefix picture is not the reserved bounded regular file")
        os.lseek(self.descriptor, 0, os.SEEK_SET)
        value = _hash_output(self.descriptor, before.st_size, deadline)
        named = os.stat(self.directory.path.name, dir_fd=self.directory.descriptor, follow_symlinks=False)
        if _file_identity(before) != _file_identity(os.fstat(self.descriptor)) \
                or _file_identity(before) != _file_identity(named):
            raise PrefixOracleError("prefix picture bytes or reserved name changed")
        self.directory.assert_current()
        deadline.remaining()
        return HeldPrefixInput(str(self.directory.path), value, before.st_size)


def _hash_output(descriptor: int, remaining: int, deadline: RemainingDeadline) -> str:
    """Bound each output read under the same original caller allowance."""
    value = hashlib.sha256()
    while remaining:
        deadline.remaining()
        data = os.read(descriptor, min(remaining, 1024 * 1024))
        if not data:
            raise PrefixOracleError("prefix picture truncated during output readback")
        value.update(data)
        remaining -= len(data)
    return value.hexdigest()


@contextmanager
def hold_picture_directory(path_text: str) -> Iterator[HeldPictureDirectory]:
    """Open the original canonical private directory without creating an output."""
    if type(path_text) is not str or not path_text or len(path_text) > 4096 \
            or any(ord(char) < 32 for char in path_text):
        raise PrefixOracleError("prefix composition output path is malformed")
    path = Path(path_text)
    real_directory(path.parent)
    if str(path) != path_text or path.suffix != ".mp4" or path.exists() or path.is_symlink():
        raise PrefixOracleError("prefix composition requires a new MP4 in a private directory")
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        if stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.geteuid():
            raise PrefixOracleError("prefix output directory is not private and owned")
        held = HeldPictureDirectory(path, descriptor, _directory_identity(info))
        held.assert_current()
        yield held
    finally:
        os.close(descriptor)


@contextmanager
def reserve_picture(directory: HeldPictureDirectory) -> Iterator[HeldPictureOutput]:
    """Create relative to the held inode, never by following its mutable path."""
    directory.assert_current()
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_NONBLOCK
    descriptor = os.open(directory.path.name, flags, 0o600, dir_fd=directory.descriptor)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise PrefixOracleError("prefix output reservation is not a new regular file")
        yield HeldPictureOutput(directory, descriptor, (info.st_dev, info.st_ino))
    finally:
        os.close(descriptor)
