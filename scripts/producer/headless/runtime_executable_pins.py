"""No-follow path walk and held-descriptor checks for runtime executables."""

from __future__ import annotations

import hashlib
import os
import stat
import unicodedata
from dataclasses import dataclass

from .runtime_executable_reobservation_wire import RuntimeExecutableSnapshotV1

_CLOSE_ON_EXEC = getattr(os, "O_CLOEXEC", 0)
_NO_FOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | _NO_FOLLOW | _CLOSE_ON_EXEC
_FILE_FLAGS = os.O_RDONLY | os.O_NONBLOCK | _NO_FOLLOW | _CLOSE_ON_EXEC
_MAX_EXECUTABLE_BYTES = 1024 * 1024 * 1024


class RuntimeExecutableReobservationError(RuntimeError):
    """Declared tool bytes or callback-lifetime inode identity are not exact."""


@dataclass(frozen=True)
class _DirectoryIdentity:
    """Stable path binding; descendant-sensitive link count is excluded."""

    device: int
    inode: int
    mode: int
    uid: int
    gid: int


@dataclass(frozen=True)
class _FileIdentity:
    device: int
    inode: int
    mode: int
    link_count: int
    uid: int
    gid: int
    size_bytes: int
    mtime_ns: int
    ctime_ns: int


@dataclass(frozen=True)
class _PathNode:
    fd: int
    parent_fd: int | None
    name: str
    identity: _DirectoryIdentity


@dataclass(frozen=True)
class PinnedExecutableV1:
    """Internal held file and directory descriptor chain for one tool path."""

    path: str
    label: str
    expected_sha256: str
    directories: tuple[_PathNode, ...]
    fd: int
    parent_fd: int
    name: str
    identity: _FileIdentity


def _directory_identity(info: os.stat_result) -> _DirectoryIdentity:
    return _DirectoryIdentity(
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_gid,
    )


def _file_identity(info: os.stat_result) -> _FileIdentity:
    return _FileIdentity(
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


def _canonical_path(path: object, label: str) -> str:
    valid = (
        type(path) is str
        and path
        and "\0" not in path
        and "\\" not in path
        and not any(
            ord(character) < 32 or ord(character) == 127 for character in path
        )
        and os.path.isabs(path)
        and os.path.normpath(path) == path
        and unicodedata.normalize("NFC", path) == path
    )
    try:
        canonical = os.path.realpath(path) if valid else None
    except OSError:
        canonical = None
    if not valid or canonical != path:
        raise RuntimeExecutableReobservationError(
            f"{label} executable path is not canonical and symlink-free"
        )
    return path


def _entry_info(node: _PathNode) -> os.stat_result:
    if node.parent_fd is None:
        return os.stat(node.name, follow_symlinks=False)
    return os.stat(node.name, dir_fd=node.parent_fd, follow_symlinks=False)


def _open_directory(parent_fd: int, name: str) -> _PathNode:
    fd = os.open(name, _DIR_FLAGS, dir_fd=parent_fd)
    try:
        info = os.fstat(fd)
        entry = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        identity = _directory_identity(info)
        if not stat.S_ISDIR(info.st_mode) or identity != _directory_identity(
            entry
        ):
            raise RuntimeExecutableReobservationError(
                "executable path directory identity is unsafe"
            )
        return _PathNode(fd, parent_fd, name, identity)
    except BaseException:
        os.close(fd)
        raise


def _effective_execute(info: os.stat_result) -> bool:
    mode = stat.S_IMODE(info.st_mode)
    if os.geteuid() == 0:
        return bool(mode & 0o111)
    if info.st_uid == os.geteuid():
        return bool(mode & 0o100)
    if info.st_gid in {os.getegid(), *os.getgroups()}:
        return bool(mode & 0o010)
    return bool(mode & 0o001)


def _safe_executable(info: os.stat_result) -> bool:
    mode = stat.S_IMODE(info.st_mode)
    return (
        stat.S_ISREG(info.st_mode)
        and info.st_nlink == 1
        and info.st_uid in {0, os.geteuid()}
        and _effective_execute(info)
        and mode & 0o022 == 0
        and 0 < info.st_size <= _MAX_EXECUTABLE_BYTES
    )


def _open_leaf(
    path: str, label: str, expected: str, directories: tuple[_PathNode, ...]
) -> PinnedExecutableV1:
    parent, name = directories[-1].fd, path.rsplit("/", 1)[1]
    fd = os.open(name, _FILE_FLAGS, dir_fd=parent)
    try:
        info = os.fstat(fd)
        entry = os.stat(name, dir_fd=parent, follow_symlinks=False)
        identity = _file_identity(info)
        valid = identity == _file_identity(entry) and _safe_executable(info)
        if not valid or identity != _file_identity(
            os.stat(path, follow_symlinks=False)
        ):
            raise RuntimeExecutableReobservationError(
                f"{label} is not one safe executable inode"
            )
        return PinnedExecutableV1(
            path, label, expected, directories, fd, parent, name, identity
        )
    except BaseException:
        os.close(fd)
        raise


def pin_executable(
    path: object, label: str, expected: str
) -> PinnedExecutableV1:
    """Open every path component without symlinks and retain all descriptors."""
    checked = _canonical_path(path, label)
    root_fd = os.open("/", _DIR_FLAGS)
    root = _PathNode(
        root_fd, None, "/", _directory_identity(os.fstat(root_fd))
    )
    directories = [root]
    try:
        for name in checked.split("/")[1:-1]:
            directories.append(_open_directory(directories[-1].fd, name))
        return _open_leaf(checked, label, expected, tuple(directories))
    except BaseException:
        for node in reversed(directories):
            os.close(node.fd)
        raise


def _read_digest(pin: PinnedExecutableV1) -> str:
    if _file_identity(os.fstat(pin.fd)) != pin.identity:
        raise RuntimeExecutableReobservationError(
            f"{pin.label} inode changed before byte reobservation"
        )
    os.lseek(pin.fd, 0, os.SEEK_SET)
    digest, total = hashlib.sha256(), 0
    while True:
        chunk = os.read(pin.fd, 1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > _MAX_EXECUTABLE_BYTES:
            raise RuntimeExecutableReobservationError(
                f"{pin.label} executable exceeded its byte bound"
            )
        digest.update(chunk)
    if _file_identity(os.fstat(pin.fd)) != pin.identity:
        raise RuntimeExecutableReobservationError(
            f"{pin.label} inode changed during byte reobservation"
        )
    actual = digest.hexdigest()
    if total != pin.identity.size_bytes or actual != pin.expected_sha256:
        raise RuntimeExecutableReobservationError(
            f"{pin.label} executable bytes do not match the runtime declaration"
        )
    return actual


def _recheck_path(pin: PinnedExecutableV1) -> None:
    for node in pin.directories:
        current = _directory_identity(os.fstat(node.fd))
        if (
            current != node.identity
            or _directory_identity(_entry_info(node)) != current
        ):
            raise RuntimeExecutableReobservationError(
                f"{pin.label} executable path changed during observation"
            )
    descriptor = _file_identity(os.fstat(pin.fd))
    entry = os.stat(pin.name, dir_fd=pin.parent_fd, follow_symlinks=False)
    absolute = os.stat(pin.path, follow_symlinks=False)
    if descriptor != pin.identity or any(
        _file_identity(info) != descriptor for info in (entry, absolute)
    ):
        raise RuntimeExecutableReobservationError(
            f"{pin.label} executable inode changed during observation"
        )


def snapshot_for_pin(pin: PinnedExecutableV1) -> RuntimeExecutableSnapshotV1:
    """Return the immutable pre-callback public observation for one pin."""
    identity = pin.identity
    return RuntimeExecutableSnapshotV1(
        pin.path,
        pin.expected_sha256,
        identity.size_bytes,
        identity.device,
        identity.inode,
        identity.mode,
        identity.link_count,
        identity.uid,
        identity.gid,
        identity.mtime_ns,
        identity.ctime_ns,
    )


def verify_pins(pins: tuple[PinnedExecutableV1, ...]) -> None:
    """Recheck absolute path binding, held metadata, and all declared bytes."""
    for pin in pins:
        _recheck_path(pin)
        _read_digest(pin)
        _recheck_path(pin)


def close_pins(pins: tuple[PinnedExecutableV1, ...]) -> None:
    """Close every held file/directory descriptor and fail on lifetime damage."""
    first_error = None
    for pin in reversed(pins):
        for fd in (pin.fd, *(node.fd for node in reversed(pin.directories))):
            try:
                os.close(fd)
            except OSError as exc:
                first_error = first_error or exc
    if first_error is not None:
        raise RuntimeExecutableReobservationError(
            "held runtime executable descriptor could not be closed"
        ) from first_error
