"""Bounded held caption bytes and new-only dependency staging, never rendering.

Hashes are observations, not execution/source/approval authority. The caller
must separately hold the actual render return and original work deadline.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

from cut_preview_io import real_directory

Guard = Callable[[], None]
MAX_FILE_BYTES = 2 * 1024 ** 3
MAX_TOTAL_BYTES = 16 * 1024 ** 3
MAX_FILES = 4096
MAX_JSON_BYTES = 16 * 1024 ** 2
_SHA = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class CaptionFile:
    """An exact caller-held regular file, not a directory-selected generation."""

    path: str
    sha256: str
    size_bytes: int


def _identity(info: os.stat_result) -> tuple:
    """Include link count and metadata changes around every bounded read."""
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _path(value: str) -> Path:
    """Reject lexical aliases and every symlinked parent before opening."""
    if type(value) is not str or not value or len(value) > 4096 \
            or any(ord(char) < 32 for char in value):
        raise RuntimeError("held caption path is malformed")
    path = Path(value)
    if str(path) != value or not path.is_absolute():
        raise RuntimeError("held caption path is not canonical")
    real_directory(path.parent)
    return path


def _regular(info: os.stat_result, maximum: int) -> None:
    """Refuse FIFOs, links, empty inputs and unbounded media before reading."""
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 \
            or not 0 < info.st_size <= maximum:
        raise RuntimeError("held caption file is unsafe or exceeds its byte bound")


def _chunks(fd: int, size: int, guard: Guard) -> Iterator[bytes]:
    """Yield at most the preflight size; each chunk spends the original budget."""
    remaining = size
    while remaining:
        guard()
        value = os.read(fd, min(remaining, 1024 * 1024))
        if not value:
            raise RuntimeError("held caption file truncated during read")
        remaining -= len(value)
        yield value
        guard()


def _collect(fd: int, size: int, options: tuple[Guard, bool]) -> tuple[str, bytes]:
    """Share the bounded streaming hash without retaining media in memory."""
    guard, collect = options
    chunks, sha = [], hashlib.sha256()
    for chunk in _chunks(fd, size, guard):
        sha.update(chunk)
        if collect:
            chunks.append(chunk)
    return sha.hexdigest(), b"".join(chunks)


def _observe(path: Path, guard: Guard, collect: bool,
             expected_size: int | None = None) -> tuple[CaptionFile, bytes]:
    """Read one bounded descriptor and require unchanged path/descriptor identity."""
    guard()
    _path(str(path))
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        _regular(before, MAX_JSON_BYTES if collect else MAX_FILE_BYTES)
        if expected_size is not None and before.st_size != expected_size:
            raise RuntimeError("held caption preflight size changed")
        sha, raw = _collect(fd, before.st_size, (guard, collect))
        if _identity(before) != _identity(os.fstat(fd)) \
                or _identity(before) != _identity(path.lstat()):
            raise RuntimeError("held caption file changed during read")
    finally:
        os.close(fd)
    _path(str(path))
    guard()
    return CaptionFile(str(path), sha, before.st_size), raw


def hold_caption_file(path: Path, guard: Guard, expected_size: int | None = None) -> CaptionFile:
    """Observe bytes only; callers must bind this to an actual trusted return."""
    return _observe(path, guard, False, expected_size)[0]


def verify_caption_files(rows: tuple[CaptionFile, ...], guard: Guard) -> None:
    """Preflight aggregate sizes before exact per-chunk reobservation."""
    if type(rows) is not tuple or not rows or len(rows) > MAX_FILES:
        raise RuntimeError("held caption inventory exceeds its file bound")
    paths, total = set(), 0
    for row in rows:
        if not isinstance(row, CaptionFile) or not _SHA.fullmatch(str(row.sha256)) \
                or type(row.size_bytes) is not int or not 0 < row.size_bytes <= MAX_FILE_BYTES:
            raise RuntimeError("held caption reference is malformed")
        path = _path(row.path)
        _regular(path.lstat(), row.size_bytes)
        paths.add(row.path)
        total += row.size_bytes
    if len(paths) != len(rows) or total > MAX_TOTAL_BYTES:
        raise RuntimeError("held caption inventory is duplicated or exceeds aggregate bytes")
    for row in rows:
        if _observe(Path(row.path), guard, False, row.size_bytes)[0] != row:
            raise RuntimeError("held caption dependency bytes changed")
    guard()


def _pairs(pairs: list[tuple]) -> dict:
    """Reject duplicate JSON fields instead of silently accepting the last one."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise RuntimeError("held caption JSON repeats a key")
        result[key] = value
    return result


def _constant(value: str) -> None:
    """Reject nonfinite JSON constants in every nested object."""
    raise RuntimeError("held caption JSON contains a nonfinite number: " + value)


def _float(value: str) -> float:
    """Reject exponent overflow as well as explicit NaN/Infinity spellings."""
    result = float(value)
    if not math.isfinite(result):
        _constant(value)
    return result


def read_caption_json(row: CaptionFile, guard: Guard) -> dict:
    """Parse the same bounded bytes whose separately held SHA was compared."""
    actual, raw = _observe(_path(row.path), guard, True, row.size_bytes)
    if actual != row:
        raise RuntimeError("held caption JSON bytes changed")
    try:
        value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant, parse_float=_float)
    except (ValueError, RecursionError) as error:
        raise RuntimeError("held caption JSON is malformed") from error
    if type(value) is not dict:
        raise RuntimeError("held caption JSON must be an object")
    guard()
    return value


def _copy(row: CaptionFile, directory: int, guard: Guard) -> None:
    """Copy held bytes to one exclusive directory-relative file; retain failures."""
    source = _path(row.path)
    reader = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    writer = None
    sha = hashlib.sha256()
    try:
        before = os.fstat(reader)
        _regular(before, row.size_bytes)
        if before.st_size != row.size_bytes:
            raise RuntimeError("caption staging source size changed")
        writer = os.open(source.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=directory)
        for chunk in _chunks(reader, row.size_bytes, guard):
            sha.update(chunk)
            _write(writer, chunk, guard)
        os.fsync(writer)
        if sha.hexdigest() != row.sha256 or _identity(before) != _identity(os.fstat(reader)) \
                or _identity(before) != _identity(source.lstat()):
            raise RuntimeError("caption staging source changed")
    finally:
        os.close(reader)
        if writer is not None:
            os.close(writer)


def _write(fd: int, data: bytes, guard: Guard) -> None:
    """Handle short writes without extending the original work allowance."""
    remaining = memoryview(data)
    while remaining:
        guard()
        count = os.write(fd, remaining)
        if count <= 0:
            raise RuntimeError("caption staging write made no progress")
        remaining = remaining[count:]


def stage_caption_files(rows: tuple[CaptionFile, ...], destination: Path,
                        guard: Guard) -> tuple[CaptionFile, ...]:
    """Create a private new directory; never copy source manifests/fonts/tools."""
    verify_caption_files(rows, guard)
    if len({Path(row.path).name for row in rows}) != len(rows):
        raise RuntimeError("caption staging names collide")
    _path(str(destination))
    if any(destination == Path(row.path).parent or destination.is_relative_to(Path(row.path).parent)
           for row in rows):
        raise RuntimeError("caption staging cannot mutate a retained source tree")
    guard()
    directory = _new_directory(destination, guard)
    identity = os.fstat(directory)
    try:
        for row in rows:
            _copy(row, directory, guard)
        os.fsync(directory)
        real_directory(destination)
        if (identity.st_dev, identity.st_ino) != (destination.stat().st_dev, destination.stat().st_ino):
            raise RuntimeError("caption staging directory changed")
    finally:
        os.close(directory)
    result = tuple(CaptionFile(str(destination / Path(row.path).name), row.sha256, row.size_bytes) for row in rows)
    verify_caption_files(rows, guard)
    verify_caption_files(result, guard)
    return result


def _new_directory(destination: Path, guard: Guard) -> int:
    """Anchor mkdir/openat to a held parent; path aliases cannot redirect writes."""
    parent = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    child = None
    try:
        guard()
        os.mkdir(destination.name, 0o700, dir_fd=parent)
        child = os.open(destination.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        real_directory(destination)
        actual, visible = os.fstat(child), destination.lstat()
        if (actual.st_dev, actual.st_ino) != (visible.st_dev, visible.st_ino):
            raise RuntimeError("caption staging directory was redirected")
        guard()
    except BaseException:
        if child is not None:
            os.close(child)
        raise
    finally:
        os.close(parent)
    return child
