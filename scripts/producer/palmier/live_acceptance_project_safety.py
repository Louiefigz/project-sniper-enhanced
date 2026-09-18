"""Palmier open-state and protected-project safety for live acceptance."""
from __future__ import annotations

import os
from typing import Any

from palmier.mcp_client import PalmierError
from palmier.timeline_authority import read_active


def _rows(payload: object) -> list[dict]:
    rows = payload.get("projects") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or any(
            not isinstance(row, dict) for row in rows):
        raise PalmierError("Palmier project-state readback is malformed")
    return rows


def project_surface(payload: object) -> dict:
    """Return the exact open-project surface and reject incoherent counts."""
    rows = _rows(payload)
    count = payload.get("openCount") if isinstance(payload, dict) else None
    opened = [row for row in rows if row.get("isOpen") is True]
    active = [row for row in rows if row.get("isActive") is True]
    valid_count = (
        isinstance(count, int) and not isinstance(count, bool)
        and count >= 0 and count == len(opened)
    )
    if not valid_count or len(active) > 1 \
            or any(row.get("isOpen") is not True for row in active):
        raise PalmierError("Palmier openCount/active project state is incoherent")
    identities = []
    for row in opened:
        ident, path = row.get("id"), row.get("path")
        if not isinstance(ident, str) or not isinstance(path, str):
            raise PalmierError("open Palmier project has no stable identity/path")
        identities.append({
            "id": ident, "path": path, "name": row.get("name"),
            "isActive": row.get("isActive") is True,
        })
    return {
        "openCount": count,
        "openProjects": sorted(
            identities, key=lambda row: (row["path"], row["id"])),
    }


def project_paths(payload: object) -> list[str]:
    """Return every known stable bundle path from one project observation."""
    paths = [row.get("path") for row in _rows(payload)]
    if any(not isinstance(path, str) or not path for path in paths):
        raise PalmierError("Palmier project catalog has an unstable path")
    return sorted(set(paths))


def active_project(payload: object) -> dict | None:
    """Return the sole active project from a coherent project payload."""
    project_surface(payload)
    active = [row for row in _rows(payload)
              if row.get("isActive") is True]
    return active[0] if active else None


def require_disposable_bundle(
        path: object, name: object,
        prior_paths: set[str] | None = None) -> str:
    """Reject aliases or non-bundles before any disposable-project mutation."""
    valid = (
        isinstance(path, str) and path == os.path.abspath(path)
        and isinstance(name, str) and bool(name)
        and path.endswith(".palmier")
        and os.path.basename(path).startswith(name)
        and os.path.isdir(path) and not os.path.islink(path)
    )
    prior = {os.path.realpath(value) for value in (prior_paths or set())
             if isinstance(value, str)}
    if not valid or os.path.realpath(str(path)) in prior:
        raise PalmierError(
            "Palmier project path is not a safely disposable bundle")
    return str(path)


def require_active_project(client: Any, project_id: str) -> dict:
    """Fence a forthcoming mutation to one exact active project."""
    active = active_project(client.call_json("get_projects", {}))
    if not isinstance(active, dict) or active.get("id") != project_id:
        raise PalmierError(
            "Palmier disposable project is not the active mutation target")
    return active


def capture_prior(client: Any) -> dict:
    """Capture exact open state and active timeline before a live cohort."""
    payload = client.call_json("get_projects", {})
    active = active_project(payload)
    shared = {
        "surface": project_surface(payload),
        "knownProjectPaths": project_paths(payload),
    }
    if active is None:
        return {
            "project": None, "timelineId": None,
            "fingerprint": None, **shared,
        }
    ident, path = active.get("id"), active.get("path")
    if not isinstance(ident, str) or not isinstance(path, str):
        raise PalmierError("active Palmier project has no stable identity/path")
    found = read_active(client, ident)
    return {
        "project": active, "timelineId": found.timeline_id,
        "fingerprint": found.fingerprint, **shared,
    }


def require_surface(client: Any, expected: dict) -> dict:
    """Require the current open-project surface to equal an earlier snapshot."""
    actual = project_surface(client.call_json("get_projects", {}))
    if actual != expected:
        raise PalmierError(
            f"Palmier open-project surface was not restored: "
            f"{actual} != {expected}")
    return actual


def restore_project(
        client: Any, prior: dict, project: dict | None) -> dict:
    """Restore the exact prior timeline and open-project surface."""
    previous = prior.get("project") or {}
    if previous.get("path"):
        client.call_json("open_project", {"path": previous["path"]})
        if prior.get("timelineId"):
            client.call("set_active_timeline", {
                "timelineId": prior["timelineId"]})
    elif project and project.get("path"):
        client.call("close_project", {"path": project["path"]})
    if previous and project and project.get("path"):
        client.call("close_project", {"path": project["path"]})
    active = active_project(client.call_json("get_projects", {}))
    expected = previous.get("id")
    actual = active.get("id") if isinstance(active, dict) else None
    if actual != expected:
        raise PalmierError("Palmier prior project was not restored")
    if expected:
        found = read_active(client, expected)
        if found.timeline_id != prior.get("timelineId") \
                or found.fingerprint != prior.get("fingerprint"):
            raise PalmierError("Palmier prior timeline was not restored exactly")
    surface = require_surface(client, prior.get("surface"))
    return {
        "priorProjectId": expected, "activeProjectId": actual,
        "timelineId": prior.get("timelineId"),
        "fingerprint": prior.get("fingerprint"),
        "openState": surface,
    }


def validate_protected_path(path: str | None) -> str | None:
    """Validate an optional existing .palmier bundle without mutating it."""
    if path is None:
        return None
    absolute = os.path.abspath(path)
    if path != absolute or os.path.islink(absolute) \
            or not os.path.isdir(absolute) \
            or not absolute.endswith(".palmier"):
        raise PalmierError(
            "protected Palmier project must be an absolute regular bundle")
    return absolute


def _matching_project(payload: object, path: str) -> dict:
    target = os.path.realpath(path)
    matches = [
        row for row in _rows(payload)
        if isinstance(row.get("path"), str)
        and os.path.realpath(row["path"]) == target
    ]
    if len(matches) != 1:
        raise PalmierError(
            "protected Palmier project is absent or ambiguous")
    row = matches[0]
    valid = (
        isinstance(row.get("id"), str)
        and row.get("isAccessible") is True
        and row.get("isOpen") is False
        and row.get("isActive") is False
    )
    if not valid:
        raise PalmierError(
            "protected Palmier project must be accessible and closed")
    return row


def _close_if_open(client: Any, path: str) -> None:
    payload = client.call_json("get_projects", {})
    target = os.path.realpath(path)
    opened = [
        row for row in _rows(payload)
        if isinstance(row.get("path"), str)
        and os.path.realpath(row["path"]) == target
        and row.get("isOpen") is True
    ]
    if len(opened) > 1:
        raise PalmierError("protected Palmier project close is ambiguous")
    if opened:
        client.call("close_project", {"path": path})


def fingerprint_protected_project(
        client: Any, path: str, expected_surface: dict) -> dict:
    """Open/read/close one closed bundle and restore exact openCount state."""
    if expected_surface != {"openCount": 0, "openProjects": []}:
        raise PalmierError(
            "protected-project proof requires an initial openCount of zero")
    require_surface(client, expected_surface)
    row = _matching_project(client.call_json("get_projects", {}), path)
    found = None
    try:
        client.call_json("open_project", {"path": path})
        found = read_active(client, row["id"])
    finally:
        _close_if_open(client, path)
    require_surface(client, expected_surface)
    if found is None or found.coverage.get("complete") is not True:
        raise PalmierError(
            "protected Palmier timeline readback was incomplete")
    return {
        "kind": "protected-project-timeline-fingerprint",
        "projectId": row["id"], "name": row.get("name"), "path": path,
        "timelineId": found.timeline_id,
        "fingerprint": found.fingerprint,
        "semanticFingerprint": found.semantic_fingerprint,
        "readbackComplete": True,
        "openStateAfter": expected_surface,
        "projectLifecycleOperationsIssued": ["open_project", "close_project"],
        "timelineContentMutationsIssued": 0,
    }


def require_same_protected_project(before: dict, after: dict) -> None:
    """Reject any identity or canonical timeline-content change."""
    keys = (
        "projectId", "name", "path", "timelineId",
        "fingerprint", "semanticFingerprint", "readbackComplete",
        "projectLifecycleOperationsIssued", "timelineContentMutationsIssued",
    )
    if any(before.get(key) != after.get(key) for key in keys):
        raise PalmierError(
            "protected Palmier project changed during live acceptance")


def checkpoint_protected_project(
        client: Any, path: str | None,
        surface: dict, disposition: str) -> dict | None:
    """Fingerprint one protected bundle inside a bound mutation phase."""
    if not isinstance(path, str):
        return None
    with client.phase(disposition):
        proof = fingerprint_protected_project(client, path, surface)
    client.bind_proof(disposition, proof)
    return proof


def record_protected_checkpoint(
        client: Any, evidence: Any,
        phase: str, surface: dict) -> dict | None:
    """Checkpoint and compare a protected bundle in acceptance evidence."""
    path = (evidence.value.get("config") or {}).get(
        "protected_project_path")
    proof = checkpoint_protected_project(
        client, path, surface, "project-lifecycle")
    if proof is None:
        return None
    expected = evidence.value["phases"].get("protectedBefore")
    if isinstance(expected, dict):
        require_same_protected_project(expected, proof)
    evidence.phase(phase, proof)
    return proof


def recover_disposable_project(
        client: Any, name: str) -> dict | None:
    """Resolve one exact named disposable bundle without fuzzy matching."""
    rows = _rows(client.call_json("get_projects", {}))
    found = [
        row for row in rows
        if row.get("name") == name
        and isinstance(row.get("path"), str)
        and row["path"].endswith(".palmier")
        and os.path.basename(row["path"]).startswith(name)
    ]
    if len(found) > 1:
        raise PalmierError("disposable project recovery is ambiguous")
    if not found:
        return None
    row = found[0]
    require_disposable_bundle(row.get("path"), row.get("name"))
    if row.get("isAccessible") is not True:
        raise PalmierError("disposable project recovery is inaccessible")
    return row
