"""Canonical hash-bound artifact observations and proposed new paths for role packets."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path

from cut_preview_io import bound_json, file_hash, real_directory

WORK_MARKERS = ("SHORT-PROJECT.json", "LONG-PROJECT.json", "PROJECT-MANIFEST.json", "export-request.json")
REHASH_LIMIT = 256 * 1024 ** 2
MEDIA_LIMIT = 4 * 1024 ** 3
MAX_RECEIPT_JSON = 256 * 1024 ** 2


class ArtifactError(ValueError):
    """An input cannot be observed under the shared artifact rule; nothing is guessed."""


def canonical_file(path: str | Path) -> Path:
    """Resolve an existing regular file to its canonical real path."""
    try:
        resolved = Path(path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ArtifactError(f"missing or unreadable file: {path}") from error
    if not resolved.is_file():
        raise ArtifactError(f"not a regular file: {resolved}")
    return resolved


def canonical_directory(path: str | Path) -> Path:
    """Resolve an existing directory to its canonical real path."""
    try:
        resolved = Path(path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ArtifactError(f"missing or unreadable directory: {path}") from error
    if not resolved.is_dir():
        raise ArtifactError(f"not a directory: {resolved}")
    return resolved


def artifact(key: str, path: str | Path, why: str) -> dict:
    """Strict observation shared with the TypeScript reader: real directory, no link, one name."""
    file = canonical_file(path)
    info = file.lstat()
    if info.st_nlink != 1:
        raise ArtifactError(f"{key}: {file} has {info.st_nlink} hard links; the shared artifact reader "
                            "refuses linked files, so it cannot be bound")
    if info.st_size > REHASH_LIMIT:
        raise ArtifactError(f"{key}: {file} exceeds the {REHASH_LIMIT}-byte rehash limit")
    try:
        sha256 = file_hash(file, REHASH_LIMIT)
    except RuntimeError as error:
        raise ArtifactError(f"{key}: {file}: {error}") from error
    return {"key": key, "path": str(file), "sha256": sha256, "bytes": info.st_size,
            "observation": "strict", "why": why}


def _stream(descriptor: int, size: int) -> str:
    """Hash exactly the observed size from an open descriptor."""
    result, remaining = hashlib.sha256(), size
    while remaining:
        data = os.read(descriptor, min(remaining, 1024 * 1024))
        if not data:
            raise ArtifactError("delivered media was truncated during observation")
        result.update(data)
        remaining -= len(data)
    return result.hexdigest()


def _same_identity(before: os.stat_result, *later: os.stat_result) -> bool:
    """Device, inode, size and timestamps stayed fixed across one observation (link count may differ)."""
    identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    return all((info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns) == identity for info in later)


def linked_media(key: str, path: str | Path, why: str) -> dict:
    """Observe delivered media that a handoff may have hard-linked; bytes stay hash-verified."""
    file = canonical_file(path)
    real_directory(file.parent)
    descriptor = os.open(file, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MEDIA_LIMIT:
            raise ArtifactError(f"{key}: {file} is not bounded regular media")
        sha256 = _stream(descriptor, before.st_size)
        if not _same_identity(before, os.fstat(descriptor), file.lstat()):
            raise ArtifactError(f"{key}: {file} changed during observation")
    finally:
        os.close(descriptor)
    return {"key": key, "path": str(file), "sha256": sha256, "bytes": before.st_size,
            "observation": "linked-media", "links": before.st_nlink, "why": why}


def declared(key: str, binding: dict, why: str) -> dict:
    """List large media by the hash its receipt declares; the builder/exporter verifies bytes."""
    file = canonical_file(binding["path"])
    return {"key": key, "path": str(file), "declaredSha256": binding["sha256"],
            "bytes": file.stat().st_size, "observation": "declared-not-rehashed", "why": why}


def bound_artifact(key: str, binding: dict, why: str) -> dict:
    """Observe a {path, sha256} binding and refuse when the bytes no longer match it."""
    row = artifact(key, binding["path"], why)
    if row["sha256"] != binding.get("sha256"):
        raise ArtifactError(f"{key}: {row['path']} no longer matches the hash its binding declares")
    return row


def read_json(path: str | Path, maximum: int = 16 * 1024 * 1024) -> dict:
    """Parse a canonical single-link JSON object under the shared bounded reader."""
    try:
        return bound_json(canonical_file(path), maximum=maximum)
    except (RuntimeError, ValueError) as error:
        raise ArtifactError(f"cannot read {path}: {error}") from error


def next_version(directory: Path, prefix: str) -> int:
    """First unused version among prefix records, packets and observation drafts."""
    pattern = re.compile(rf"{re.escape(prefix)}(?:-v(\d+))?(?:-PACKET|-OBSERVATIONS)?\.json")
    versions = [int(match.group(1) or 0) for name in os.listdir(directory)
                if (match := pattern.fullmatch(name))]
    return max(versions, default=0) + 1


def next_sibling(parent: Path, stem: str, suffix: str = "") -> Path:
    """Propose the next unused <stem>-vN<suffix> sibling (directory or file) without creating it."""
    pattern = re.compile(rf"{re.escape(stem)}-v(\d+){re.escape(suffix)}")
    versions = [int(match.group(1)) for name in os.listdir(parent) if (match := pattern.fullmatch(name))]
    return parent / f"{stem}-v{max(versions, default=0) + 1}{suffix}"


def proposed_paths(directory: Path, prefix: str) -> dict:
    """New packet, observations draft and record paths sharing one unused version."""
    version = next_version(directory, prefix)
    stem = directory / f"{prefix}-v{version}"
    return {"version": version, "packet": Path(f"{stem}-PACKET.json"),
            "observations": Path(f"{stem}-OBSERVATIONS.json"), "record": Path(f"{stem}.json")}


def new_output(path: str | Path) -> Path:
    """Canonicalize a new output's parent directory; the output itself must not exist yet."""
    target = Path(path).expanduser()
    parent = canonical_directory(target.parent if target.is_absolute() else Path.cwd() / target.parent)
    output = parent / target.name
    if os.path.lexists(output):
        raise ArtifactError(f"output already exists: {output}")
    return output


def staged_work(directory: Path) -> Path | None:
    """The directory itself or nearest ancestor that is a staged project or an export/preview attempt."""
    for candidate in (directory, *directory.parents):
        if any((candidate / name).is_file() for name in WORK_MARKERS):
            return candidate
    return None


def json_bytes(value: dict) -> bytes:
    """The exact published serialization: indented, UTF-8, trailing newline."""
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def write_json_new(path: Path, value: dict) -> str:
    """Exclusive, durable, human-readable JSON; returns the published bytes' SHA-256."""
    real_directory(path.parent)
    raw = json_bytes(value)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
    try:
        view = memoryview(raw)
        while view:
            view = view[os.write(descriptor, view):]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    if os.name != "nt":  # Windows cannot open a directory descriptor to flush its entry.
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    return hashlib.sha256(raw).hexdigest()
