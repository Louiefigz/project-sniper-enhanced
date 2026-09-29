#!/usr/bin/env python3
"""Resolve immutable catalog snapshots without overwriting historical pins."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from graphics.catalog_resource_index import file_sha256

REGISTRY_NAME = "catalog-snapshots-v1.json"
SCHEMA_VERSION = 1
MAX_REGISTRY_BYTES = 4 * 1024 * 1024
MAX_SNAPSHOTS = 256


@dataclass(frozen=True)
class SnapshotPaths:
    """Resolved files for one admitted immutable snapshot."""

    snapshot_id: str
    root: str
    index_path: str
    lock_path: str
    resource_path: str


def _read_registry(catalog_dir: str) -> dict | None:
    """Read the optional v1 registry; legacy fixtures remain directly readable."""
    path = os.path.join(catalog_dir, REGISTRY_NAME)
    if not os.path.exists(path):
        return None
    if not os.path.isfile(path) or os.path.islink(path):
        raise RuntimeError(f"catalog snapshot registry is not a regular file: {path}")
    if os.path.getsize(path) > MAX_REGISTRY_BYTES:
        raise RuntimeError(f"catalog snapshot registry exceeds the bounded read size: {path}")
    try:
        with open(path, "rb") as handle:
            content = handle.read(MAX_REGISTRY_BYTES + 1)
        if len(content) > MAX_REGISTRY_BYTES:
            raise RuntimeError(
                f"catalog snapshot registry grew beyond the bounded read size: {path}")
        data = json.loads(content)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"catalog snapshot registry unreadable: {path} — {exc}") from exc
    if not isinstance(data, dict) or data.get("schemaVersion") != SCHEMA_VERSION:
        raise RuntimeError("catalog snapshot registry schema/version is invalid")
    snapshots = data.get("snapshots")
    if (not isinstance(data.get("current"), str)
            or not isinstance(snapshots, dict)
            or not snapshots or len(snapshots) > MAX_SNAPSHOTS):
        raise RuntimeError("catalog snapshot registry inventory is invalid or unbounded")
    return data


def resolve_snapshot(catalog_dir: str, snapshot_id: str | None = None) -> SnapshotPaths:
    """Resolve current or explicit snapshot and verify its metadata digests."""
    registry = _read_registry(catalog_dir)
    if registry is None:
        if snapshot_id is not None:
            raise RuntimeError("explicit catalog snapshot requires a snapshot registry")
        return _legacy_paths(catalog_dir)
    chosen = snapshot_id or registry.get("current")
    snapshots = registry.get("snapshots")
    row = snapshots.get(chosen) if isinstance(snapshots, dict) else None
    if not isinstance(chosen, str) or not isinstance(row, dict):
        raise RuntimeError(f"catalog snapshot is not admitted: {chosen!r}")
    paths = _snapshot_paths(catalog_dir, chosen, row)
    _verify_digests(paths, row)
    return paths


def _legacy_paths(catalog_dir: str) -> SnapshotPaths:
    """Keep pre-registry test fixtures and historical installs readable."""
    return SnapshotPaths("legacy-unversioned", os.path.realpath(catalog_dir),
                         os.path.join(catalog_dir, "catalog-index.json"),
                         os.path.join(catalog_dir, "hyperframes-catalog-lock.json"),
                         os.path.join(catalog_dir, "catalog-resource-index-v1.json"))


def _snapshot_paths(catalog_dir: str, snapshot_id: str, row: dict) -> SnapshotPaths:
    """Resolve one safe relative root inside the catalog directory."""
    base = os.path.realpath(catalog_dir)
    declared = os.path.abspath(os.path.join(base, str(row.get("root", ""))))
    if not os.path.isdir(declared) or os.path.islink(declared):
        raise RuntimeError(f"catalog snapshot root is not a regular directory: {snapshot_id}")
    root = os.path.realpath(declared)
    if os.path.commonpath((base, root)) != base:
        raise RuntimeError(f"catalog snapshot root escapes mirror: {snapshot_id}")
    return SnapshotPaths(snapshot_id, root, os.path.join(root, "catalog-index.json"),
                         os.path.join(root, "hyperframes-catalog-lock.json"),
                         os.path.join(root, "catalog-resource-index-v1.json"))


def _verify_digests(paths: SnapshotPaths, row: dict) -> None:
    """Reject a snapshot whose admitted metadata bytes changed in place."""
    expected = {"indexSha256": paths.index_path, "lockSha256": paths.lock_path,
                "resourceSha256": paths.resource_path}
    for key, path in expected.items():
        if not os.path.isfile(path) or os.path.islink(path):
            raise RuntimeError(f"catalog snapshot file unavailable: {path}")
        if row.get(key) != file_sha256(path):
            raise RuntimeError(f"catalog snapshot digest mismatch: {paths.snapshot_id} {key}")
