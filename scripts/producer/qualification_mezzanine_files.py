"""Stable byte observation and atomic publication for qualification media."""
from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass

from headless.external_media_snapshot import MAX_EXTERNAL_MEDIA_BYTES
from headless.qualification_mezzanine_policy import (
    MAX_QUALIFICATION_SOURCE_BYTES,
)
from ingest_admission_contract import canonical_bytes

MAX_EVIDENCE_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class FileFact:
    """Stable full-byte identity observed without media parsing."""

    path: str
    sha256: str
    size_bytes: int
    device: int
    inode: int
    mtime_ns: int
    ctime_ns: int


def regular_directory(path: Path, label: str) -> None:
    """Require an existing non-link directory."""
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise RuntimeError(f"{label} is unavailable") from exc
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise RuntimeError(f"{label} must be a real directory")


def _hash_descriptor(descriptor: int) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            return digest.hexdigest(), size
        digest.update(chunk)
        size += len(chunk)


def _observe(path: str, minimum: int, maximum: int, label: str) -> FileFact:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise RuntimeError(f"{label} is unavailable") from exc
    try:
        before = os.fstat(descriptor)
        valid = (stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                 and minimum < before.st_size <= maximum)
        if not valid:
            raise RuntimeError(f"{label} is outside its immutable byte bounds")
        digest, size = _hash_descriptor(descriptor)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    current = os.lstat(path)
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if (size != before.st_size
            or any(getattr(before, key) != getattr(after, key) for key in fields)
            or any(getattr(current, key) != getattr(after, key) for key in fields)):
        raise RuntimeError(f"{label} changed during full-byte observation")
    return FileFact(os.path.abspath(path), digest, size, before.st_dev,
                    before.st_ino, before.st_mtime_ns, before.st_ctime_ns)


def observe_overcap_source(path: str) -> FileFact:
    """Hash/stat only; never host-probe or host-decode the raw source."""
    return _observe(
        path, MAX_EXTERNAL_MEDIA_BYTES, MAX_QUALIFICATION_SOURCE_BYTES,
        "over-cap qualification source")


def observe_qualified_output(path: str) -> FileFact:
    """Bind a nonempty output under the unchanged admission cap."""
    return _observe(path, 0, MAX_EXTERNAL_MEDIA_BYTES, "qualified output")


def read_canonical_evidence(path: str) -> dict:
    """Read one bounded, no-link, exact canonical JSON evidence file."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or not 0 < before.st_size <= MAX_EVIDENCE_BYTES):
            raise RuntimeError("qualification evidence is not one bounded file")
        payload = os.read(descriptor, before.st_size + 1)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    current = os.lstat(path)
    if (len(payload) != before.st_size
            or any(getattr(before, key) != getattr(after, key) for key in fields)
            or any(getattr(current, key) != getattr(after, key) for key in fields)):
        raise RuntimeError("qualification evidence changed while reading")
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError("qualification evidence is invalid JSON") from exc
    if payload != canonical_bytes(document):
        raise RuntimeError("qualification evidence is not exact canonical JSON")
    return document
