"""Read and fingerprint Sniper's platform-specific runtime locks."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from release.runtime_target import target as runtime_target

HEADER = "# sniper-runtime-lock-v1"
_SHA = re.compile(r"^[0-9a-f]{64}$")
_KINDS = {"micromamba", "micromamba-bin", "conda", "local", "download"}


class LockFormatError(Exception):
    """A runtime lock is malformed."""


def file_sha256(path: Path) -> str:
    """Return the SHA-256 of one file, streamed."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_lock(
    path: Path | None = None,
    platform: str = "osx-arm64",
) -> tuple[dict[str, str], list[dict[str, str]]]:
    """Return a lock's header and rows, rejecting malformed input."""
    path = path or runtime_target(platform).lock
    header: dict[str, str] = {}
    rows: list[dict[str, str]] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].split(" —")[0] != HEADER:
        raise LockFormatError(f"{path.name} does not start with '{HEADER}'")
    for line in lines[1:]:
        if line.startswith("# ") and " " in line[2:]:
            key, value = line[2:].split(" ", 1)
            header[key] = value
            continue
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 5 or parts[0] not in _KINDS:
            raise LockFormatError(f"malformed lock row: {line}")
        if not _SHA.match(parts[1]) or not parts[2].isdigit():
            raise LockFormatError(f"malformed lock row: {line}")
        rows.append(dict(zip(("kind", "sha256", "bytes", "path", "source"), parts)))
    return header, rows


def conda_rows_sha256(rows: list[dict[str, str]]) -> str:
    """Fingerprint the conda package set a measured OS floor belongs to."""
    text = "\n".join(
        f"{row['sha256']} {row['path']}" for row in rows if row["kind"] == "conda"
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
