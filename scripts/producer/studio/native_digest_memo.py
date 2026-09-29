"""Process-local SHA-256 memo bound to exact file identity, plus integrity telemetry.

Repeated integrity checks inside one process re-read the same pinned files: the
audited attempts spent 327.82 s in 553 worker checks alone, and each owner's
supervisor re-read about 1.6 GB of pins three times. A digest computed earlier in
the SAME process is returned only while the path's exact identity is unchanged:
``(st_dev, st_ino, st_mode, st_nlink, st_size, st_mtime_ns, st_ctime_ns)`` of the
path itself (lstat) and of its followed target (stat). A content write, rename or
replacement, symlink swap, chmod or link-count change alters that identity and
forces a full re-read. A file whose newest timestamp is within ``MEMO_MARGIN_NS``
of the hash is never memoized (the racy-clean rule git's index uses), so a rewrite
inside one timestamp tick cannot hide behind an unchanged identity.

Scope limits (explicit, not enforced here): the memo never outlives its process,
so every new worker or supervisor process reads each pin in full first. It relies
on the local kernel maintaining ctime, which user space cannot set; a clock
rollback onto the exact prior timestamp, or a network filesystem serving stale
cached attributes, is outside this guarantee.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from cut_preview_io import file_hash, file_identity, real_directory

MEMO_MARGIN_NS = 2_000_000_000
TELEMETRY_NAME = 'integrity-telemetry.jsonl'
_COUNTERS = ('files', 'hashedFiles', 'hashedBytes', 'memoFiles', 'memoBytes')
Identity = tuple[int, ...]


@dataclass(frozen=True)
class _Entry:
    """One full read: the path's lstat/stat identities and the resulting digest."""

    link: Identity
    target: Identity
    digest: str


_MEMO: dict[str, _Entry] = {}
_TOTALS: dict[str, float] = {**{key: 0 for key in _COUNTERS}, 'hashSeconds': 0.0}


def _now_ns() -> int:
    """Wall clock used only for the racy-clean margin (patched by tests)."""
    return time.time_ns()


def _identity(info: os.stat_result) -> Identity:
    """Every field that a content, replacement, link or permission change moves."""
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _observe(path: Path) -> tuple[Identity, Identity] | None:
    """Return (lstat, stat) identities of a regular target, else None (never memoized)."""
    try:
        link, target = os.lstat(path), os.stat(path)
    except OSError:
        return None
    return (_identity(link), _identity(target)) if stat.S_ISREG(target.st_mode) else None


def _settled(observed: tuple[Identity, Identity]) -> bool:
    """Memoize only files last changed at least the racy margin before this read."""
    newest = max(row[index] for row in observed for index in (5, 6))
    return newest <= _now_ns() - MEMO_MARGIN_NS


def _record(observed: tuple[Identity, Identity], value: str, key: str) -> None:
    """Keep a verified full read; any other outcome forgets the path."""
    if _settled(observed):
        _MEMO[key] = _Entry(observed[0], observed[1], value)
    else:
        _MEMO.pop(key, None)


def _count(kind: str, size: int, seconds: float = 0.0) -> None:
    """Accumulate process-wide hashed and memoized files and bytes."""
    _TOTALS['files'] += 1
    _TOTALS[f'{kind}Files'] += 1
    _TOTALS[f'{kind}Bytes'] += size
    _TOTALS['hashSeconds'] += seconds


def file_digest(file: Path) -> str:
    """SHA-256 of ``file`` following links, reusing a same-process read of identical identity."""
    key = os.fspath(file)
    before = _observe(file)
    entry = _MEMO.get(key)
    if before is not None and entry is not None and (entry.link, entry.target) == before:
        _count('memo', before[1][4])
        return entry.digest
    started = time.monotonic()
    with open(file, 'rb') as handle:
        opened = _identity(os.fstat(handle.fileno()))
        value = hashlib.file_digest(handle, 'sha256').hexdigest()
        read = _identity(os.fstat(handle.fileno()))
    _count('hashed', read[4], time.monotonic() - started)
    if before is not None and opened == read == before[1] and _observe(file) == before:
        _record(before, value, key)
    else:
        _MEMO.pop(key, None)
    return value


def pinned_file_hash(path: Path, maximum: int) -> str:
    """``cut_preview_io.file_hash`` semantics (no-follow, single link, bounded) with the same memo."""
    key = os.fspath(path)
    real_directory(path.parent)
    link = os.lstat(path)
    entry = _MEMO.get(key)
    if entry is not None and stat.S_ISREG(link.st_mode) and link.st_nlink == 1 \
            and 0 < link.st_size <= maximum and entry.link == entry.target == _identity(link):
        _count('memo', link.st_size)
        return entry.digest
    started = time.monotonic()
    value = file_hash(path, maximum=maximum)
    _count('hashed', link.st_size, time.monotonic() - started)
    after = os.lstat(path)
    if file_identity(after) == file_identity(link) and _identity(after) == _identity(link):
        _record((_identity(link), _identity(link)), value, key)
    else:
        _MEMO.pop(key, None)
    return value


def totals() -> dict[str, float]:
    """Process-cumulative counters since this interpreter started."""
    return dict(_TOTALS)


def forget() -> None:
    """Drop every memoized digest (tests and explicit trust-boundary resets)."""
    _MEMO.clear()


def _append(root: Path, row: dict) -> None:
    """Best-effort telemetry: a telemetry write never changes a pipeline outcome."""
    try:
        descriptor = os.open(root / TELEMETRY_NAME, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(descriptor, (json.dumps(row, allow_nan=False) + '\n').encode())
        finally:
            os.close(descriptor)
    except (OSError, TypeError, ValueError):
        return


@contextlib.contextmanager
def integrity_boundary(root: str | Path | None, boundary: str) -> Iterator[None]:
    """Record files, bytes and time hashed or memoized inside one named check."""
    before, started, status = totals(), time.monotonic(), 'failed'
    try:
        yield
        status = 'completed'
    finally:
        if root:
            after = totals()
            delta = {key: after[key] - before[key] for key in (*_COUNTERS, 'hashSeconds')}
            _append(Path(root), {'schemaVersion': 1, 'boundary': boundary, 'pid': os.getpid(),
                                 'status': status, 'seconds': time.monotonic() - started,
                                 **delta, 'processTotals': after})
