"""Immutable before-state sidecars for crash-safe Desktop mutations."""
from __future__ import annotations

import hashlib
import json
import os

from fingerprints import file_sha256
from palmier.mcp_client import PalmierError
from palmier.timeline_authority import (TimelineSnapshot, atomic_write_record,
                                        snapshot_with_coverage)

ROOT_NAME = ".palmier-desktop-operation-snapshots"
_RECORD_KEYS = {
    "schemaVersion", "kind", "projectId", "timelineId", "fingerprint",
    "semanticFingerprint", "readbackCoverage", "timeline",
}
_REF_KEYS = {"schemaVersion", "path", "hash", "timelineId", "fingerprint"}


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PalmierError(
            f"Desktop before-state is not canonical JSON: {exc}") from exc


def _record(found: TimelineSnapshot) -> dict:
    return {
        "schemaVersion": 1,
        "kind": "palmier-desktop-operation-before",
        "projectId": found.project_id,
        "timelineId": found.timeline_id,
        "fingerprint": found.fingerprint,
        "semanticFingerprint": found.semantic_fingerprint,
        "readbackCoverage": found.coverage,
        "timeline": found.timeline,
    }


def _snapshot_root(state: dict) -> str:
    out_dir = state.get("outDir")
    if not isinstance(out_dir, str) or not os.path.isabs(out_dir):
        raise PalmierError("Desktop authority has no absolute output directory")
    root = os.path.join(out_dir, ROOT_NAME)
    os.makedirs(root, mode=0o700, exist_ok=True)
    return root


def _read(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise PalmierError(
            f"cannot read Desktop immutable before-state: {exc}") from exc
    if not isinstance(value, dict) or set(value) != _RECORD_KEYS \
            or value.get("schemaVersion") != 1 \
            or value.get("kind") != "palmier-desktop-operation-before":
        raise PalmierError("Desktop immutable before-state is malformed")
    return value


def _assert_existing(path: str, record: dict) -> None:
    if os.path.islink(path) or not os.path.isfile(path):
        raise PalmierError("Desktop immutable before-state is not a regular file")
    if _read(path) != record:
        raise PalmierError("Desktop immutable before-state path has conflicting bytes")


def write_before_snapshot(state: dict,
                          found: TimelineSnapshot) -> dict:
    """Persist exact pre-mutation readback before the MCP call can execute."""
    record = _record(found)
    logical = hashlib.sha256(_canonical(record)).hexdigest()
    path = os.path.join(_snapshot_root(state), f"{logical}.json")
    if os.path.lexists(path):
        _assert_existing(path, record)
    else:
        atomic_write_record(path, record)
        _assert_existing(path, record)
    return {
        "schemaVersion": 1, "path": path, "hash": file_sha256(path),
        "timelineId": found.timeline_id, "fingerprint": found.fingerprint,
    }


def _validate_reference(state: dict, pending: dict) -> tuple[dict, dict]:
    reference = pending.get("beforeSnapshot")
    if not isinstance(reference, dict) or set(reference) != _REF_KEYS \
            or reference.get("schemaVersion") != 1:
        raise PalmierError(
            "pending Desktop operation has no immutable before-state")
    root = _snapshot_root(state)
    path = reference.get("path")
    if not isinstance(path, str) or os.path.islink(path) \
            or os.path.dirname(os.path.realpath(path)) != os.path.realpath(root):
        raise PalmierError("Desktop immutable before-state path is outside authority")
    if not os.path.isfile(path) or file_sha256(path) != reference.get("hash"):
        raise PalmierError("Desktop immutable before-state bytes changed")
    return reference, _read(path)


def load_before_snapshot(state: dict,
                         pending: dict) -> TimelineSnapshot:
    """Reconstruct and verify a pending operation's exact prior timeline."""
    reference, record = _validate_reference(state, pending)
    found = snapshot_with_coverage(
        record["projectId"], record["timeline"], record["readbackCoverage"])
    expected = {
        "projectId": state.get("projectId"),
        "timelineId": state.get("candidate", {}).get("timelineId"),
        "fingerprint": pending.get("beforeFingerprint"),
    }
    actual = {
        "projectId": found.project_id, "timelineId": found.timeline_id,
        "fingerprint": found.fingerprint,
    }
    valid = actual == expected \
        and reference.get("timelineId") == found.timeline_id \
        and reference.get("fingerprint") == found.fingerprint \
        and record.get("fingerprint") == found.fingerprint \
        and record.get("semanticFingerprint") == found.semantic_fingerprint \
        and record.get("readbackCoverage") == found.coverage
    if not valid:
        raise PalmierError(
            "Desktop immutable before-state does not match pending ancestry")
    return found
