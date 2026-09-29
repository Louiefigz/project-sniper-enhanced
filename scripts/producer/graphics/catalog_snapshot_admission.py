#!/usr/bin/env python3
"""Validate a prepared catalog snapshot before registry promotion."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from graphics.catalog_discovery_validation import MAX_ROWS, index_record_issue, validated_lock
from graphics.catalog_resource_index import file_sha256, load_resource_index

MAX_METADATA_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class AdmissionRequest:
    """Exact snapshot identity expected by the maintainer."""

    registry_root: str
    candidate_dir: str
    snapshot_id: str
    expected_commit: str


def inspect_candidate(request: AdmissionRequest) -> dict:
    """Return a registry row only for a complete digest-bound candidate."""
    registry_root = os.path.realpath(request.registry_root)
    declared_candidate = os.path.abspath(request.candidate_dir)
    if not os.path.isdir(declared_candidate) or os.path.islink(declared_candidate):
        raise RuntimeError("candidate snapshot must be a regular directory")
    candidate = os.path.realpath(declared_candidate)
    if os.path.commonpath((registry_root, candidate)) != registry_root:
        raise RuntimeError("candidate snapshot is outside the catalog registry root")
    paths = _paths(request.candidate_dir)
    raw_index = _read_json(paths["index"], "candidate index")
    raw_lock = _read_json(paths["lock"], "candidate lock")
    issues = _index_issues(raw_index)
    lock, lock_issues = validated_lock(raw_lock if isinstance(raw_lock, dict) else {})
    issues.extend(lock_issues)
    if not isinstance(raw_lock, dict) or raw_lock.get("sourceCommit") != request.expected_commit:
        issues.append("candidate lock sourceCommit does not match expected pinned commit")
    rows = raw_index if isinstance(raw_index, list) else []
    names = {row["name"] for row in rows if isinstance(row, dict)
             and isinstance(row.get("name"), str)}
    resources, resource_issues = load_resource_index(
        paths["resource"], paths["index"], paths["lock"])
    issues.extend(resource_issues)
    if set(resources) != names:
        issues.append("candidate resource rows do not exactly cover the index")
    issues.extend(_source_issues(request.candidate_dir, rows, lock["knownMissing"]))
    if lock.get("itemsListed") != len(rows):
        issues.append("candidate lock itemsListed does not equal index rows")
    return {"ok": not issues, "snapshotId": request.snapshot_id,
            "expectedCommit": request.expected_commit, "issues": issues,
            "registryEntry": _entry(request, paths, len(rows)) if not issues else None}


def _paths(root: str) -> dict[str, str]:
    """Resolve required candidate metadata under one regular directory."""
    root = os.path.realpath(root)
    if not os.path.isdir(root) or os.path.islink(root):
        raise RuntimeError(f"candidate snapshot is not a regular directory: {root}")
    return {"index": os.path.join(root, "catalog-index.json"),
            "lock": os.path.join(root, "hyperframes-catalog-lock.json"),
            "resource": os.path.join(root, "catalog-resource-index-v1.json")}


def _read_json(path: str, label: str) -> object:
    """Read one candidate file without following a symlink."""
    if not os.path.isfile(path) or os.path.islink(path):
        raise RuntimeError(f"{label} is not a regular file: {path}")
    if os.path.getsize(path) > MAX_METADATA_BYTES:
        raise RuntimeError(f"{label} exceeds the bounded read size: {path}")
    try:
        with open(path, "rb") as handle:
            content = handle.read(MAX_METADATA_BYTES + 1)
        if len(content) > MAX_METADATA_BYTES:
            raise RuntimeError(f"{label} grew beyond the bounded read size: {path}")
        return json.loads(content)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{label} unreadable: {path} — {exc}") from exc


def _index_issues(data: object) -> list[str]:
    """Reject malformed, duplicate or empty prepared indexes."""
    if not isinstance(data, list) or not data or len(data) > MAX_ROWS:
        return ["candidate index must be a nonempty list"]
    issues, names = [], set()
    for position, row in enumerate(data):
        issue = index_record_issue(row)
        if issue:
            issues.append(f"candidate index row #{position}: {issue}")
            continue
        if row["name"] in names:
            issues.append(f"candidate index duplicate name: {row['name']}")
        names.add(row["name"])
    return issues


def _source_issues(root: str, rows: list[dict], known_missing: dict[str, str]) -> list[str]:
    """Require every unblocked main source in the prepared immutable root."""
    issues = []
    for row in rows:
        if not isinstance(row, dict) or row.get("name") in known_missing:
            continue
        folder = "compositions" if row.get("type") == "block" else "compositions/components"
        path = os.path.join(root, folder, str(row.get("name")) + ".html")
        if not os.path.isfile(path) or os.path.islink(path):
            issues.append(f"candidate source missing: {row.get('name')}")
    return issues


def _entry(request: AdmissionRequest, paths: dict[str, str], items: int) -> dict:
    """Build the exact manifest row; callers choose whether it becomes current."""
    root = os.path.relpath(os.path.realpath(request.candidate_dir),
                           os.path.realpath(request.registry_root))
    return {"root": root,
            "sourceCommit": request.expected_commit, "items": items,
            "indexSha256": file_sha256(paths["index"]),
            "lockSha256": file_sha256(paths["lock"]),
            "resourceSha256": file_sha256(paths["resource"])}
