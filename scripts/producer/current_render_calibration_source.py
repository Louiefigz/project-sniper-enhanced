#!/usr/bin/env python3
"""Immutable content-addressed source authority for codec-floor calibration."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from current_render_graph_contract import file_hash

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RETAINED_ROOT = (
    PROJECT_ROOT / "artifacts" / "current-render-codec-floor-calibration-v1"
    / "sources"
)
STORAGE_CLASS = "content-addressed-retained-calibration-source-v1"


def _regular(path: Path, label: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"{label} must be a regular non-symlink file")
    return path.resolve(strict=True)


def _secure_directory(path: Path) -> Path:
    if path.is_symlink():
        raise RuntimeError("calibration retained-source root is a symlink")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise RuntimeError("calibration retained-source root is not a directory")
    return resolved


def _secure_child(parent: Path, name: str) -> Path:
    lexical = parent / name
    if lexical.is_symlink():
        raise RuntimeError("calibration retained-source directory is a symlink")
    lexical.mkdir(mode=0o700, exist_ok=True)
    resolved = lexical.resolve(strict=True)
    if resolved.parent != parent or not resolved.is_dir():
        raise RuntimeError("calibration retained-source directory escapes root")
    return resolved


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _target(root: Path, digest: str) -> Path:
    retained = _secure_directory(root)
    hash_root = _secure_child(retained, "sha256")
    shard = _secure_child(hash_root, digest[:2])
    return shard / f"{digest}.media"


def _copy_atomic(source: Path, target: Path, expected_digest: str) -> None:
    descriptor, staged = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with source.open("rb") as reader, os.fdopen(descriptor, "wb") as writer:
            shutil.copyfileobj(reader, writer, length=1024 * 1024)
            writer.flush()
            os.fsync(writer.fileno())
        if file_hash(Path(staged)) != expected_digest:
            raise RuntimeError("calibration input changed while being retained")
        os.chmod(staged, 0o444)
        os.replace(staged, target)
        _sync_directory(target.parent)
    finally:
        try:
            os.unlink(staged)
        except FileNotFoundError:
            pass


def source_facts(path: Path, retained_root: Path = RETAINED_ROOT) -> dict:
    """Return strict facts only for a canonical retained-source location."""
    resolved = _regular(path, "calibration retained source")
    root = retained_root.resolve(strict=True)
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(
            "calibration source is outside the retained-source root") from exc
    digest = file_hash(resolved)
    expected = Path("sha256") / digest[:2] / f"{digest}.media"
    if relative != expected:
        raise RuntimeError("calibration retained-source path is not content-addressed")
    return {
        "path": str(resolved),
        "sha256": digest,
        "sizeBytes": resolved.stat().st_size,
        "storageClass": STORAGE_CLASS,
    }


def retain_source(source: Path, retained_root: Path = RETAINED_ROOT) -> dict:
    """Snapshot a mutable input once and return immutable retained authority."""
    source_path = _regular(source, "calibration input source")
    digest = file_hash(source_path)
    target = _target(retained_root, digest)
    if target.exists():
        facts = source_facts(target, retained_root)
        if (
            facts["sizeBytes"] != source_path.stat().st_size
            or file_hash(source_path) != digest
        ):
            raise RuntimeError("calibration retained source has a hash collision")
        return facts
    _copy_atomic(source_path, target, digest)
    facts = source_facts(target, retained_root)
    if facts["sha256"] != digest:
        raise RuntimeError("calibration retained-source copy changed bytes")
    return facts


def validate_source_record_shape(
    record: object,
    retained_root: Path = RETAINED_ROOT,
) -> dict:
    """Validate content-addressed location/identity without reading media."""
    keys = {"path", "sha256", "sizeBytes", "storageClass"}
    if not isinstance(record, dict) or set(record) != keys:
        raise RuntimeError("calibration source record is malformed")
    digest = record["sha256"]
    valid_digest = (
        isinstance(digest, str)
        and len(digest) == 64
        and all(char in "0123456789abcdef" for char in digest)
    )
    if (
        not valid_digest
        or type(record["sizeBytes"]) is not int
        or record["sizeBytes"] <= 0
        or record["storageClass"] != STORAGE_CLASS
    ):
        raise RuntimeError("calibration source record is malformed")
    root = retained_root.absolute()
    expected = root / "sha256" / digest[:2] / f"{digest}.media"
    if Path(record["path"]) != expected:
        raise RuntimeError("calibration source record is not content-addressed")
    return record


def verify_source_record(
    record: object,
    retained_root: Path = RETAINED_ROOT,
) -> dict:
    """Rehash a persisted retained-source record and reject mutable locations."""
    record = validate_source_record_shape(record, retained_root)
    facts = source_facts(Path(record["path"]), retained_root)
    if facts != record:
        raise RuntimeError("calibration retained-source record is stale")
    return facts
