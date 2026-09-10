"""Fail-closed admitted-media authority for the late b-roll pool."""
from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from ingest_admission import collect_ingest_candidates
from ingest_execution_authority import execution_media_authority_entries

MAX_MANIFEST_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class PoolAsset:
    """One pool original and its executable admitted snapshot."""

    original_path: str
    snapshot_path: str
    sha256: str
    receipt_path: str
    receipt_sha256: str


@dataclass(frozen=True)
class PoolAuthority:
    """Verified pool root, manifest, and admitted asset mapping."""

    root: Path
    manifest_path: Path
    assets: dict[str, PoolAsset]


def _real_directory(path: Path) -> None:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise RuntimeError("b-roll pool directory is unavailable") from exc
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise RuntimeError("b-roll pool must be a real non-symlink directory")


def _read_manifest_bytes(
    descriptor: int,
    size: int,
) -> tuple[bytes, os.stat_result]:
    chunks, remaining = [], size
    while remaining:
        chunk = os.read(descriptor, min(1024 * 1024, remaining))
        if not chunk:
            raise RuntimeError("b-roll pool manifest was truncated")
        chunks.append(chunk)
        remaining -= len(chunk)
    if os.read(descriptor, 1):
        raise RuntimeError("b-roll pool manifest grew while reading")
    return b"".join(chunks), os.fstat(descriptor)


def _read_manifest(path: Path) -> dict:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise RuntimeError("b-roll pool manifest is unavailable") from exc
    try:
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode)
                or not 0 < before.st_size <= MAX_MANIFEST_BYTES):
            raise RuntimeError("b-roll pool manifest is not a bounded file")
        payload, after = _read_manifest_bytes(
            descriptor, before.st_size)
    finally:
        os.close(descriptor)
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if any(getattr(before, field) != getattr(after, field)
           for field in fields):
        raise RuntimeError("b-roll pool manifest changed while reading")
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("b-roll pool manifest is malformed") from exc
    if type(value) is not dict:
        raise RuntimeError("b-roll pool manifest is not an object")
    return value


def _inside(original: str, root: Path) -> bool:
    try:
        absolute = os.path.abspath(original)
        return os.path.commonpath([absolute, str(root)]) == str(root)
    except ValueError:
        return False


def _pool_assets(entries: list[dict], root: Path) -> dict[str, PoolAsset]:
    assets: dict[str, PoolAsset] = {}
    for entry in entries:
        original = entry["originalPath"]
        if entry["lane"] != "broll" or not _inside(original, root):
            continue
        absolute = os.path.abspath(original)
        if absolute in assets:
            raise RuntimeError("b-roll pool repeats an admitted original")
        assets[absolute] = PoolAsset(
            original_path=absolute,
            snapshot_path=entry["snapshotPath"],
            sha256=entry["sha256"],
            receipt_path=entry["admissionReceiptPath"],
            receipt_sha256=entry["admissionReceiptSha256"],
        )
    return assets


def _reject_unadmitted_files(root: Path, assets: dict[str, PoolAsset]) -> None:
    candidates = collect_ingest_candidates([], root, None)
    unadmitted = sorted(
        str(candidate.original_path)
        for candidate in candidates
        if str(candidate.original_path) not in assets
    )
    if unadmitted:
        detail = ", ".join(unadmitted[:3])
        raise RuntimeError(
            "b-roll pool contains media absent from the admitted source set; "
            f"re-run canonical ingest before scan: {detail}")


def open_pool(broll_dir: Path, manifest_path: Path) -> PoolAuthority:
    """Reverify the manifest/source set and open only its admitted b-roll."""
    root = Path(os.path.abspath(broll_dir))
    manifest_file = Path(os.path.abspath(manifest_path))
    _real_directory(root)
    manifest = _read_manifest(manifest_file)
    entries = execution_media_authority_entries(
        {}, manifest, str(manifest_file))
    if entries is None:
        raise RuntimeError("b-roll pool requires source-set admission")
    assets = _pool_assets(entries, root)
    _reject_unadmitted_files(root, assets)
    return PoolAuthority(root, manifest_file, assets)


def proof_fields(asset: PoolAsset) -> dict:
    """Return the exact manifest projection of one pool admission."""
    return {
        "originalPath": asset.original_path,
        "sourceSha256": asset.sha256,
        "admissionReceiptPath": asset.receipt_path,
        "admissionReceiptSha256": asset.receipt_sha256,
    }
