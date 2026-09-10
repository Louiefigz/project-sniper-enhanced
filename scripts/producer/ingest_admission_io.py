"""Existing canonical receipt bytes and bounded reads, shared without import cycles."""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path


def canonical_bytes(value: object) -> bytes:
    """One exact JSON encoding for receipt hashes and retained files."""
    return (json.dumps(value, ensure_ascii=True, separators=(",", ":"),
                       sort_keys=True, allow_nan=False) + "\n").encode("ascii")


def _read_descriptor(descriptor: int, size: int, label: str) -> bytes:
    """Read exactly the held size and reject truncated or growing receipt bytes."""
    chunks, remaining = [], size
    while remaining:
        chunk = os.read(descriptor, min(1024 * 1024, remaining))
        if not chunk:
            raise RuntimeError(f"{label} was truncated while reading")
        chunks.append(chunk)
        remaining -= len(chunk)
    if os.read(descriptor, 1):
        raise RuntimeError(f"{label} grew while reading")
    return b"".join(chunks)


def _bounded_regular(descriptor: int, maximum: int,
                     label: str) -> tuple[bytes, os.stat_result, os.stat_result]:
    """Preserve the existing descriptor-linked receipt size/type checks."""
    before = os.fstat(descriptor)
    valid = (stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= maximum)
    if not valid:
        raise RuntimeError(f"{label} is not one bounded regular file")
    payload = _read_descriptor(descriptor, before.st_size, label)
    return payload, before, os.fstat(descriptor)


def _read_regular(path: Path, maximum: int, label: str) -> bytes:
    """Preserve existing receipt transport semantics and error messages exactly."""
    flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise RuntimeError(f"{label} is unavailable") from exc
    try:
        payload, before, after = _bounded_regular(descriptor, maximum, label)
    finally:
        os.close(descriptor)
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if any(getattr(before, key) != getattr(after, key) for key in fields):
        raise RuntimeError(f"{label} changed while reading")
    return payload
