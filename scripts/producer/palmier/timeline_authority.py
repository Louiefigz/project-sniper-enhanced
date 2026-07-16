#!/usr/bin/env python3
"""Canonical, MCP-readable Palmier timeline snapshots and safe candidate forks."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from palmier.mcp_client import PalmierError

AUTHORITY_NAME = "palmier.timeline-authority.json"
CANONICAL_CANDIDATE_NAME = "palmier.timeline-candidate.json"
ORIGINS = ("sniper-bootstrap", "sniper-promoted", "palmier-manual",
           "untrusted-bootstrap")
_REFERENCE_KEYS = {"clipId", "trackId", "timelineId",
                   "captionGroupId", "linkGroupId"}
_STRUCTURAL_ID_PARENTS = {"tracks", "clips", "audio", "linkedClips"}
_RUNTIME_ROOT_KEYS = {"canGenerate", "currentFrame", "timelines"}

class TimelineConflict(PalmierError):
    """Palmier no longer matches the revision a caller intended to edit."""


@dataclass(frozen=True)
class TimelineSnapshot:
    """One immutable observation of the active timeline."""
    project_id: str
    timeline_id: str
    fingerprint: str
    semantic_fingerprint: str
    timeline: dict
    coverage: dict


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PalmierError(f"Palmier timeline is not canonical JSON: {exc}") from exc


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _content_timeline(timeline: dict) -> dict:
    """Exclude Palmier runtime capability state, never unknown edit fields."""
    return {key: value for key, value in timeline.items()
            if key not in _RUNTIME_ROOT_KEYS}


def _semantic(value: Any, root: bool = False, parent: str | None = None,
              identities: dict | None = None) -> Any:
    """Normalize only known structural identities; unknown fields stay content."""
    identities = {} if identities is None else identities
    if isinstance(value, list):
        return [_semantic(item, parent=parent, identities=identities)
                for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in sorted(value.items()):
        if root and key in ("id", "name"):
            continue
        if key == "id" and parent in _STRUCTURAL_ID_PARENTS:
            continue
        if key in _REFERENCE_KEYS and isinstance(item, str):
            bucket = identities.setdefault(key, {})
            result[key] = bucket.setdefault(item, f"{key}:{len(bucket) + 1}")
            continue
        result[key] = _semantic(item, parent=key, identities=identities)
    return result


def _coverage(timeline: dict) -> dict:
    """Declare whether caption-detail readback can represent the whole edit."""
    capped: list[dict] = []
    for track_index, track in enumerate(timeline.get("tracks", [])):
        if not isinstance(track, dict):
            continue
        groups = track.get("captionGroups") or []
        if not isinstance(groups, list):
            continue
        for group_index, group in enumerate(groups):
            if not isinstance(group, dict):
                continue
            count = group.get("clipCount", 0)
            if isinstance(count, int) and not isinstance(count, bool) and count > 200:
                capped.append({"track": track_index, "group": group_index,
                               "clipCount": count})
    return {
        "scope": "mcp-readable-timeline",
        "captionDetailRequested": True,
        "complete": not capped,
        "limitations": (["caption groups above Palmier's 200-row detail cap"]
                        if capped else []),
        "cappedCaptionGroups": capped,
    }


def snapshot(project_id: str, timeline: dict) -> TimelineSnapshot:
    """Validate and fingerprint one get_timeline(captionDetail=true) result."""
    if not isinstance(project_id, str) or not project_id:
        raise PalmierError("Palmier canonical snapshot has no project id")
    if not isinstance(timeline, dict):
        raise PalmierError("get_timeline did not return an object")
    timeline_id = timeline.get("id")
    tracks = timeline.get("tracks")
    if not isinstance(timeline_id, str) or not timeline_id:
        raise PalmierError("get_timeline did not return a timeline id")
    if not isinstance(tracks, list):
        raise PalmierError("get_timeline did not return tracks")
    normalized = json.loads(_canonical(timeline))
    content = _content_timeline(normalized)
    return TimelineSnapshot(
        project_id, timeline_id, _hash(content),
        _hash(_semantic(content, root=True)), normalized,
        _coverage(normalized))


def _active_project_id(projects: dict) -> str | None:
    rows = projects.get("projects") if isinstance(projects, dict) else None
    if not isinstance(rows, list):
        return None
    active = [row.get("id") for row in rows if isinstance(row, dict)
              and row.get("isActive") is True]
    return active[0] if len(active) == 1 and isinstance(active[0], str) else None


def read_active(client: Any, expected_project_id: str) -> TimelineSnapshot:
    """Read the visible timeline without opening, switching, or editing anything."""
    projects = client.call_json("get_projects", {})
    active_id = _active_project_id(projects)
    if active_id != expected_project_id:
        raise TimelineConflict(
            "Palmier is not showing this Sniper project's canonical project")
    timeline = client.call_json("get_timeline", {"captionDetail": True})
    return snapshot(active_id, timeline)


def authority_path(out_dir: str) -> str:
    return os.path.join(out_dir, AUTHORITY_NAME)


def candidate_path(out_dir: str) -> str:
    return os.path.join(out_dir, CANONICAL_CANDIDATE_NAME)


def load_authority(out_dir: str) -> dict | None:
    try:
        with open(authority_path(out_dir), encoding="utf-8") as handle:
            value = json.load(handle)
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        raise PalmierError(f"cannot read Palmier timeline authority: {exc}") from exc
    if not isinstance(value, dict) or value.get("schemaVersion") != 1:
        raise PalmierError("Palmier timeline authority is not schemaVersion 1")
    return value


def atomic_write_record(path: str, value: dict) -> None:
    temp = f"{path}.{os.getpid()}.{secrets.token_hex(6)}.tmp"
    try:
        with open(temp, "x", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        try:
            os.unlink(temp)
        except FileNotFoundError:
            pass


def record_authority(out_dir: str, found: TimelineSnapshot, origin: str,
                     parent: dict | None = None) -> dict:
    """Atomically make an observed Palmier revision the saved baseline."""
    if origin not in ORIGINS:
        raise PalmierError(f"unknown Palmier timeline authority origin {origin!r}")
    record = {
        "schemaVersion": 1, "authority": "palmier", "origin": origin,
        "projectId": found.project_id, "timelineId": found.timeline_id,
        "fingerprint": found.fingerprint,
        "semanticFingerprint": found.semantic_fingerprint,
        "capturedAt": _now(), "readbackCoverage": found.coverage,
        "timeline": found.timeline,
        "workingHead": {
            "projectId": found.project_id, "timelineId": found.timeline_id,
            "fingerprint": found.fingerprint,
            "semanticFingerprint": found.semantic_fingerprint,
        },
    }
    if parent:
        record["parent"] = {
            "timelineId": parent.get("timelineId"),
            "fingerprint": parent.get("fingerprint"),
        }
        if isinstance(parent.get("approvedHead"), dict):
            record["approvedHead"] = parent["approvedHead"]
            record["approvalCurrent"] = (
                parent["approvedHead"].get("fingerprint") == found.fingerprint)
    atomic_write_record(authority_path(out_dir), record)
    return record


def record_active_authority(client: Any, out_dir: str, project_id: str,
                            origin: str) -> dict:
    """Read then persist the active revision as the canonical baseline."""
    return record_authority(out_dir, read_active(client, project_id), origin)


def _snapshot_record(found: TimelineSnapshot) -> dict:
    return {
        "projectId": found.project_id, "timelineId": found.timeline_id,
        "fingerprint": found.fingerprint,
        "semanticFingerprint": found.semantic_fingerprint,
        "readbackCoverage": found.coverage, "timeline": found.timeline,
    }


def record_candidate(out_dir: str, found: TimelineSnapshot,
                     parent: dict) -> dict:
    """Stage a copy without moving the canonical Palmier authority pointer."""
    record = {
        "schemaVersion": 1, "status": "staged", "createdAt": _now(),
        **_snapshot_record(found),
        "base": {"projectId": parent.get("projectId"),
                 "timelineId": parent.get("timelineId"),
                 "fingerprint": parent.get("fingerprint")},
    }
    atomic_write_record(candidate_path(out_dir), record)
    return record


def compare_authority(expected: dict, current: TimelineSnapshot) -> str:
    """Classify current Palmier state without treating a drift as an overwrite."""
    if expected.get("projectId") != current.project_id:
        return "project-changed"
    if expected.get("timelineId") != current.timeline_id:
        return "timeline-changed"
    if expected.get("fingerprint") != current.fingerprint:
        return "content-changed"
    return "unchanged"


def fork_candidate(client: Any, out_dir: str, expected: dict,
                   name: str) -> dict:
    """Copy the canonical timeline after a fresh precondition readback."""
    project_id = expected.get("projectId")
    if not isinstance(project_id, str):
        raise PalmierError("candidate fork has no canonical project id")
    current = read_active(client, project_id)
    change = compare_authority(expected, current)
    if change != "unchanged":
        raise TimelineConflict(f"Palmier canonical timeline {change} before AI fork")
    if current.coverage.get("complete") is not True:
        raise TimelineConflict("Palmier readback is incomplete; refusing an AI fork")
    result = client.call_json("create_timeline", {
        "name": name, "from": current.timeline_id})
    candidate = snapshot(project_id, client.call_json(
        "get_timeline", {"captionDetail": True}))
    returned_id = result.get("timelineId") if isinstance(result, dict) else None
    if candidate.timeline_id == current.timeline_id or returned_id != candidate.timeline_id:
        raise PalmierError("Palmier candidate fork did not return a new active timeline")
    if candidate.semantic_fingerprint != current.semantic_fingerprint:
        raise PalmierError("Palmier candidate fork is not a semantic copy of its source")
    return record_candidate(out_dir, candidate, expected)


def promote_candidate(out_dir: str, proof: object) -> dict:
    """Promote only fresh QC/CAS evidence; never receipt-embedded timeline JSON."""
    from palmier.native_qc_authority import promote_qc_candidate
    return promote_qc_candidate(out_dir, proof)
