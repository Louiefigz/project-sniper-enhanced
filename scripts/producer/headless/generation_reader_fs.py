"""Descriptor-only filesystem primitives for sealed generation reads."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .generation_schema import GenerationManifestRowV1

_CLOSE_ON_EXEC = getattr(os, "O_CLOEXEC", 0)
_NO_FOLLOW = os.O_NOFOLLOW


class GenerationReadError(RuntimeError):
    """Published generation state is absent, unsafe, mixed, or corrupt."""


@dataclass(frozen=True)
class _Policy:
    device: int
    owner: int


@dataclass(frozen=True)
class _OpenSpec:
    flags: int
    mode: int
    directory: bool


@dataclass(frozen=True)
class _Pinned:
    fd: int
    parent_fd: int | None
    name: str
    snapshot: tuple[int, ...]


_MUTABLE_DIR = _OpenSpec(os.O_RDONLY | os.O_DIRECTORY, 0o700, True)
_MUTABLE_FILE = _OpenSpec(os.O_RDONLY | os.O_NONBLOCK, 0o600, False)
_LOCK_FILE = _OpenSpec(os.O_RDWR | os.O_NONBLOCK, 0o600, False)
_SEALED_DIR = _OpenSpec(os.O_RDONLY | os.O_DIRECTORY, 0o500, True)
_SEALED_FILE = _OpenSpec(os.O_RDONLY | os.O_NONBLOCK, 0o400, False)


def _snapshot(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_uid,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _safe(info: os.stat_result, spec: _OpenSpec, policy: _Policy) -> bool:
    node_type = (
        stat.S_ISDIR(info.st_mode)
        if spec.directory
        else stat.S_ISREG(info.st_mode)
    )
    links_safe = spec.directory or info.st_nlink == 1
    return (
        node_type
        and links_safe
        and info.st_dev == policy.device
        and info.st_uid == policy.owner
        and stat.S_IMODE(info.st_mode) == spec.mode
    )


def _open_at(
    parent_fd: int, name: str, spec: _OpenSpec, policy: _Policy
) -> _Pinned:
    flags = spec.flags | _NO_FOLLOW | _CLOSE_ON_EXEC
    fd = os.open(name, flags, dir_fd=parent_fd)
    try:
        info = os.fstat(fd)
        entry = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if not _safe(info, spec, policy) or _snapshot(info) != _snapshot(
            entry
        ):
            raise GenerationReadError(f"unsafe generation node: {name}")
        return _Pinned(fd, parent_fd, name, _snapshot(info))
    except Exception:
        os.close(fd)
        raise


def _open_root(path: str) -> tuple[_Pinned, _Policy]:
    if (
        type(path) is not str
        or not os.path.isabs(path)
        or os.path.realpath(path) != path
    ):
        raise GenerationReadError(
            "directory must be an absolute canonical path"
        )
    flags = os.O_RDONLY | os.O_DIRECTORY | _NO_FOLLOW | _CLOSE_ON_EXEC
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        policy = _Policy(info.st_dev, os.geteuid())
        if not _safe(info, _MUTABLE_DIR, policy):
            raise GenerationReadError("directory must be owned mode 0700")
        entry = os.stat(path, follow_symlinks=False)
        if (info.st_dev, info.st_ino) != (entry.st_dev, entry.st_ino):
            raise GenerationReadError("directory pathname identity changed")
        return _Pinned(fd, None, path, _snapshot(info)), policy
    except Exception:
        os.close(fd)
        raise


def _entry_stat(node: _Pinned) -> os.stat_result:
    if node.parent_fd is None:
        return os.stat(node.name, follow_symlinks=False)
    return os.stat(node.name, dir_fd=node.parent_fd, follow_symlinks=False)


def _recheck(node: _Pinned) -> None:
    if _snapshot(os.fstat(node.fd)) != node.snapshot:
        raise GenerationReadError(f"generation node changed: {node.name}")
    if _snapshot(_entry_stat(node)) != node.snapshot:
        raise GenerationReadError(f"generation entry changed: {node.name}")


def _recheck_safe(node: _Pinned, spec: _OpenSpec, policy: _Policy) -> None:
    info = os.fstat(node.fd)
    if not _safe(info, spec, policy) or _snapshot(info) != _snapshot(
        _entry_stat(node)
    ):
        raise GenerationReadError(
            f"materialization directory changed: {node.name}"
        )


def _read_all(fd: int, limit: int) -> bytes:
    os.lseek(fd, 0, os.SEEK_SET)
    chunks, total = [], 0
    while True:
        chunk = os.read(fd, min(1024 * 1024, limit + 1 - total))
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        total += len(chunk)
        if total > limit:
            raise GenerationReadError(
                "generation authority record is oversized"
            )


def _read_stable(node: _Pinned, limit: int) -> bytes:
    data = _read_all(node.fd, limit)
    _recheck(node)
    return data


def _write_chunk(fd: int, chunk: bytes) -> None:
    view = memoryview(chunk)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise GenerationReadError("zero-byte generation copy write")
        view = view[written:]


def _stream(source_fd: int, destination_fd: int | None) -> tuple[int, str]:
    os.lseek(source_fd, 0, os.SEEK_SET)
    digest, total = hashlib.sha256(), 0
    while True:
        chunk = os.read(source_fd, 1024 * 1024)
        if not chunk:
            return total, digest.hexdigest()
        digest.update(chunk)
        total += len(chunk)
        if destination_fd is not None:
            _write_chunk(destination_fd, chunk)


def _new_output(parent_fd: int, name: str, policy: _Policy) -> int:
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | _NO_FOLLOW | _CLOSE_ON_EXEC
    fd = os.open(name, flags, 0o600, dir_fd=parent_fd)
    try:
        os.fchmod(fd, 0o600)
        if not _safe(os.fstat(fd), _MUTABLE_FILE, policy):
            raise GenerationReadError("materialized file is unsafe")
        return fd
    except Exception:
        os.close(fd)
        raise


def _new_output_dir(parent_fd: int, name: str, policy: _Policy) -> _Pinned:
    os.mkdir(name, 0o700, dir_fd=parent_fd)
    os.chmod(name, 0o700, dir_fd=parent_fd, follow_symlinks=False)
    return _open_at(parent_fd, name, _MUTABLE_DIR, policy)


def _output_indexes(
    rows: tuple["GenerationManifestRowV1", ...],
) -> tuple[
    dict[tuple[str, ...], frozenset[str]],
    dict[tuple[str, ...], "GenerationManifestRowV1"],
]:
    mutable_names: dict[tuple[str, ...], set[str]] = {}
    leaves = {}
    for row in rows:
        parts = tuple(row.path.split("/"))
        leaves[parts] = row
        for index, name in enumerate(parts):
            mutable_names.setdefault(parts[:index], set()).add(name)
    names = {path: frozenset(items) for path, items in mutable_names.items()}
    return names, leaves


def _fresh_pin(node: _Pinned, policy: _Policy) -> _Pinned:
    _recheck_safe(node, _MUTABLE_DIR, policy)
    return _Pinned(
        node.fd, node.parent_fd, node.name, _snapshot(os.fstat(node.fd))
    )


def _exact_entries(fd: int, expected: set[str] | frozenset[str]) -> bool:
    """Compare directory names without retaining attacker-controlled extras."""
    remaining = set(expected)
    with os.scandir(fd) as entries:
        for entry in entries:
            if entry.name not in remaining:
                return False
            remaining.remove(entry.name)
    return not remaining
