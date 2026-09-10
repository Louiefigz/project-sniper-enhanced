"""Content-hash authority joining one transcript to its exact input media."""
from __future__ import annotations

import hashlib
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from cross_runtime_canonical_json import canonical_compact_json

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_READ_SIZE = 1024 * 1024


@dataclass(frozen=True)
class SourceObservation:
    """Stable file identity and bytes observed around transcription."""

    path: str
    sha256: str
    size_bytes: int
    device: int
    inode: int
    mtime_ns: int
    ctime_ns: int


def _digest_result(result: dict) -> str:
    payload = canonical_compact_json(result).encode()
    return hashlib.sha256(payload).hexdigest()


def _identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev, value.st_ino, value.st_size,
        value.st_mtime_ns, value.st_ctime_ns,
    )


def _read_guarded(descriptor: int, guard: Callable[[], None] | None) -> bytes:
    """Charge each source read to an optional caller-held deadline."""
    if guard:
        guard()
    chunk = os.read(descriptor, _READ_SIZE)
    if guard:
        guard()
    return chunk


def observe_source(path: Path, expected: tuple[str, int],
                   guard: Callable[[], None] | None = None) -> SourceObservation:
    """Hash a regular non-symlink input and reject mutation during the read."""
    if guard:
        guard()
    absolute = Path(os.path.abspath(path))
    expected_sha, expected_size = expected
    if not _SHA256.fullmatch(expected_sha) or isinstance(expected_size, bool) \
            or not isinstance(expected_size, int) or expected_size <= 0:
        raise RuntimeError("transcript source authority is malformed")
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(absolute, flags)
    digest = hashlib.sha256()
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise RuntimeError("transcript input is not a regular file")
        for chunk in iter(lambda: _read_guarded(descriptor, guard), b""):
            digest.update(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    current = os.lstat(absolute)
    if _identity(before) != _identity(after) \
            or _identity(after) != _identity(current):
        raise RuntimeError("transcript input changed while it was observed")
    if after.st_size != expected_size or digest.hexdigest() != expected_sha:
        raise RuntimeError("transcript input does not match admitted media")
    if guard:
        guard()
    return SourceObservation(
        str(absolute), expected_sha, expected_size, after.st_dev, after.st_ino,
        after.st_mtime_ns, after.st_ctime_ns,
    )


def require_same_source(
    before: SourceObservation,
    after: SourceObservation,
) -> None:
    """Reject source replacement or mutation across the transcription call."""
    if before != after:
        raise RuntimeError("transcript input changed during transcription")


def bind_result(result: dict, source: SourceObservation) -> dict:
    """Return a transcript result carrying a digest-bound media observation."""
    if not isinstance(result, dict) or not isinstance(result.get("transcript"), list):
        raise RuntimeError("transcription result is malformed")
    if "sourceMediaAuthority" in result:
        raise RuntimeError("transcription result already declares source authority")
    authority = {
        "schemaVersion": 1,
        "sourcePath": source.path,
        "sourceSha256": source.sha256,
        "sourceSizeBytes": source.size_bytes,
        "transcriptionResultSha256": _digest_result(result),
    }
    authority["bindingDigest"] = _digest_result(authority)
    return {**result, "sourceMediaAuthority": authority}


def verify_result(payload: Any, source: dict, path: str) -> str | None:
    """Return a precise error when transcript and manifest media diverge."""
    if not isinstance(payload, dict):
        return "transcript root must be an object"
    authority = payload.get("sourceMediaAuthority")
    if not isinstance(authority, dict):
        return "transcript is missing sourceMediaAuthority"
    expected_path = os.path.abspath(str(source.get("path", "")))
    expected_sha = source.get("sourceSha256")
    expected_size = source.get("sourceSizeBytes")
    actual_size = os.path.getsize(expected_path) if os.path.isfile(expected_path) else None
    if expected_size is None:
        expected_size = actual_size
    fields_ok = (
        authority.get("schemaVersion") == 1
        and authority.get("sourcePath") == expected_path
        and authority.get("sourceSha256") == expected_sha
        and authority.get("sourceSizeBytes") == expected_size
        and expected_size == actual_size
        and _SHA256.fullmatch(str(expected_sha or "")) is not None
    )
    if not fields_ok:
        return "transcript source authority does not match manifest media"
    unsigned = {key: value for key, value in payload.items()
                if key != "sourceMediaAuthority"}
    if authority.get("transcriptionResultSha256") != _digest_result(unsigned):
        return "transcription result bytes do not match source authority"
    binding = {key: value for key, value in authority.items()
               if key != "bindingDigest"}
    if authority.get("bindingDigest") != _digest_result(binding):
        return "transcript source authority digest is invalid"
    if os.path.abspath(path) == expected_path:
        return "transcript path cannot alias its source media"
    return None
