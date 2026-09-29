"""Freeze and re-derive the admitted unified catalog authority."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from graphics import comp_capabilities
from graphics.catalog_discovery import inventory_catalog, load_catalog
from graphics.catalog_discovery_sources import CATALOG_DIR, STUDY_PATH, DiscoveryPaths
from graphics.catalog_snapshot_registry import REGISTRY_NAME, resolve_snapshot
from planner.visual_plan_fields import canonical_hash

MAX_CATALOG_BYTES = 4 * 1024 * 1024
CATALOG_ID = "hyperframes"


def file_sha256(path: str) -> str:
    """Hash one bounded regular file."""
    file = Path(path)
    if file.is_symlink() or not file.is_file() or file.stat().st_size > MAX_CATALOG_BYTES:
        raise ValueError(f"catalog metadata is not one bounded regular file: {path}")
    digest = hashlib.sha256()
    with file.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def trusted_snapshot_pin(version: str | None = None) -> dict:
    """Return the exact installed registry and derivation-input identities."""
    snapshot = resolve_snapshot(CATALOG_DIR, version)
    registry = os.path.join(CATALOG_DIR, REGISTRY_NAME)
    capability = os.path.realpath(comp_capabilities._MATRIX_PATH)
    study = os.path.realpath(STUDY_PATH)
    return {
        "catalogId": CATALOG_ID, "version": snapshot.snapshot_id,
        "registryPath": os.path.realpath(registry),
        "registrySha256": file_sha256(registry),
        "snapshotIndexPath": os.path.realpath(snapshot.index_path),
        "snapshotIndexSha256": file_sha256(snapshot.index_path),
        "snapshotLockPath": os.path.realpath(snapshot.lock_path),
        "snapshotLockSha256": file_sha256(snapshot.lock_path),
        "snapshotResourcePath": os.path.realpath(snapshot.resource_path),
        "snapshotResourceSha256": file_sha256(snapshot.resource_path),
        "capabilityPath": capability, "capabilitySha256": file_sha256(capability),
        "studyPath": study, "studySha256": file_sha256(study),
    }


def build_catalog_authority(version: str | None = None) -> tuple[dict, dict]:
    """Rebuild all discovery records from one admitted installed snapshot."""
    metadata = trusted_snapshot_pin(version)
    paths = DiscoveryPaths(
        catalog_dir=CATALOG_DIR, study_path=metadata["studyPath"],
        capability_path=metadata["capabilityPath"], snapshot_id=metadata["version"])
    inventory = inventory_catalog(load_catalog(paths))
    items = inventory["items"]
    authority = {**inventory,
                 "resourceItems": {row["id"]: row["resourceEvidence"] for row in items},
                 "admissionInputs": metadata}
    return authority, metadata


def source_set_sha256(items: list[dict]) -> str:
    """Bind the exact per-record source digests in one stable value."""
    rows = [{"id": row["ref"], "sha256": row["source"].get("sha256")}
            for row in items]
    return canonical_hash(sorted(rows, key=lambda row: row["id"]))


def _source_root(items: list[dict]) -> str:
    paths = [row["source"]["path"] for row in items if row["source"].get("exists")]
    if not paths:
        raise ValueError("catalog authority has no available sources")
    root = os.path.commonpath(paths)
    while not os.path.isdir(root):
        root = os.path.dirname(root)
    return os.path.realpath(root)


def _write_exact(path: Path, data: bytes) -> None:
    if len(data) > MAX_CATALOG_BYTES:
        raise ValueError("unified catalog authority exceeds 4 MiB")
    if path.exists():
        invalid = path.is_symlink() or not path.is_file()
        oversized = not invalid and path.stat().st_size > MAX_CATALOG_BYTES
        if invalid or oversized or path.read_bytes() != data:
            raise ValueError("existing catalog authority differs from current corpus")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(data)


def materialize_catalog_authority(raw_path: str) -> dict:
    """Write the canonical 372-record discovery authority and return its pin."""
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        raise ValueError("catalog authority destination must be absolute")
    authority, metadata = build_catalog_authority()
    data = (json.dumps(authority, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode()
    _write_exact(path, data)
    digest = hashlib.sha256(data).hexdigest()
    return {**metadata, "indexPath": str(path.resolve()), "indexSha256": digest,
            "resourceIndexPath": str(path.resolve()), "resourceIndexSha256": digest,
            "sourceRootPath": _source_root(authority["items"]),
            "sourceSetSha256": source_set_sha256(authority["items"])}
