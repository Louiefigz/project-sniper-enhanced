"""Hash and lease validation shared by Desktop Palmier mutation hooks."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from fingerprints import file_sha256
from palmier.mcp_client import PalmierError


def read_bound_json(path: str) -> dict:
    """Read one immutable Desktop authority artifact."""
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise PalmierError(f"cannot read Desktop Palmier artifact: {exc}") from exc
    if not isinstance(value, dict):
        raise PalmierError("Desktop Palmier artifact is not an object")
    return value


def _expired(value: object) -> bool:
    if not isinstance(value, str):
        return True
    try:
        return datetime.fromisoformat(value) <= datetime.now(timezone.utc)
    except ValueError:
        return True


def _receipt_current(row: object, label: str) -> None:
    if not isinstance(row, dict) or set(row) != {"path", "hash"}:
        raise PalmierError(f"Desktop Palmier {label} receipt is malformed")
    path, digest = row.get("path"), row.get("hash")
    if not isinstance(path, str) or not os.path.isfile(path) \
            or os.path.islink(path) or file_sha256(path) != digest:
        raise PalmierError(f"Desktop Palmier {label} changed after authorization")


def _coherent(state: dict, gates: dict, operations: dict) -> bool:
    return gates.get("ok") is True \
        and gates.get("stage") == state.get("stage") \
        and operations.get("stage") == state.get("stage") \
        and gates.get("planHash") == operations.get("planHash") \
        == state["plan"]["hash"] \
        and gates.get("manifestHash") == operations.get("manifestHash") \
        == state["manifest"]["hash"]


def _revision_current(state: dict, operations: dict) -> None:
    revision = state.get("revision")
    manifest = operations.get("revision")
    valid = isinstance(revision, dict) and isinstance(manifest, dict) \
        and revision.get("revisionSetId") == manifest.get("revisionSetId") \
        and revision.get("path") == manifest.get("path") \
        and revision.get("hash") == manifest.get("hash")
    if not valid:
        raise PalmierError("Desktop Palmier revision authority is incoherent")
    _receipt_current({key: revision[key] for key in ("path", "hash")},
                     "revision")


def validate_authority(state: dict) -> None:
    """Fail unless every current lease and content receipt still matches."""
    if state.get("status") != "active" or _expired(state.get("expiresAt")):
        raise PalmierError("Desktop Palmier authority is inactive or expired")
    for key in ("plan", "manifest", "gates", "operations"):
        _receipt_current(state.get(key), key)
    gates = read_bound_json(state["gates"]["path"])
    operations = read_bound_json(state["operations"]["path"])
    if not _coherent(state, gates, operations):
        raise PalmierError("Desktop Palmier stage artifacts are stale or incoherent")
    if state.get("stage") == "revision":
        _revision_current(state, operations)
