"""Typed, content-addressed revision sets for long-running Palmier edits."""
from __future__ import annotations

import hashlib
import json
import os
import re

from fingerprints import json_canon
from palmier.mcp_client import PalmierError
from palmier.timeline_authority import atomic_write_record

KIND = "palmier-revision-set"
SCHEMA_VERSION = 1
MAX_OPERATIONS = 256
REVISION_ID_RE = re.compile(r"^rev-[0-9a-f]{16}$")
OPERATION_ID_RE = re.compile(r"^rop-[0-9a-f]{16}$")
LANES = {"graphics", "nativeText"}
ACTIONS = {"add", "remove", "replace", "move", "update"}


def stable_digest(value: object) -> str:
    """Return a deterministic digest for JSON-compatible revision content."""
    blob = json.dumps(json_canon(value), sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def operation_id(operation: dict) -> str:
    """Mint one deterministic operation identity from its semantic payload."""
    payload = {key: value for key, value in operation.items()
               if key not in {"operationId", "page", "status"}}
    return f"rop-{stable_digest(payload)[:16]}"


def _validate_operation(row: object, seen: set[str]) -> dict:
    if not isinstance(row, dict):
        raise PalmierError("Palmier revision operation must be an object")
    operation = dict(row)
    operation.setdefault("operationId", operation_id(operation))
    ident = operation.get("operationId")
    element = operation.get("elementId")
    if not isinstance(ident, str) or not OPERATION_ID_RE.fullmatch(ident):
        raise PalmierError("Palmier revision operationId is malformed")
    if ident in seen:
        raise PalmierError(f"duplicate Palmier revision operation {ident!r}")
    if operation.get("lane") not in LANES:
        raise PalmierError(f"unsupported Palmier revision lane {operation.get('lane')!r}")
    if operation.get("action") not in ACTIONS:
        raise PalmierError(f"unsupported Palmier revision action {operation.get('action')!r}")
    if not isinstance(element, str) or not element:
        raise PalmierError("Palmier revision operation needs a stable elementId")
    version = operation.get("expectedVersion", 0)
    if not isinstance(version, int) or isinstance(version, bool) or version < 0:
        raise PalmierError("Palmier revision expectedVersion must be a non-negative integer")
    operation["expectedVersion"] = version
    seen.add(ident)
    return operation


def validate_revision(value: object) -> dict:
    """Normalize and validate one revision set without touching Palmier."""
    if not isinstance(value, dict):
        raise PalmierError("Palmier revision set must be an object")
    operations = value.get("operations")
    if not isinstance(operations, list) or not 1 <= len(operations) <= MAX_OPERATIONS:
        raise PalmierError(
            f"Palmier revision set requires 1-{MAX_OPERATIONS} operations")
    seen: set[str] = set()
    normalized = [_validate_operation(row, seen) for row in operations]
    targets = [(row["lane"], row["elementId"]) for row in normalized]
    if len(targets) != len(set(targets)):
        raise PalmierError(
            "Palmier revision has conflicting operations for one element")
    payload = {**value, "schemaVersion": SCHEMA_VERSION, "kind": KIND,
               "operations": normalized}
    identity_payload = {key: item for key, item in payload.items()
                        if key not in {"revisionSetId", "digest", "pages"}}
    expected_id = f"rev-{stable_digest(identity_payload)[:16]}"
    supplied_id = payload.get("revisionSetId")
    if supplied_id not in (None, expected_id):
        raise PalmierError("Palmier revisionSetId does not match its content")
    payload["revisionSetId"] = expected_id
    payload["digest"] = stable_digest(identity_payload)
    return payload


def read_revision(path: str) -> dict:
    """Read and validate a regular JSON revision-set file."""
    absolute = os.path.abspath(path)
    if not os.path.isfile(absolute) or os.path.islink(absolute):
        raise PalmierError(f"Palmier revision set is missing: {absolute}")
    try:
        with open(absolute, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise PalmierError(f"cannot read Palmier revision set: {exc}") from exc
    return validate_revision(value)


def write_revision(out_dir: str, value: object) -> dict:
    """Persist one normalized revision set by content identity."""
    revision = validate_revision(value)
    path = os.path.join(out_dir, f".palmier-revision-{revision['revisionSetId']}.json")
    atomic_write_record(path, revision)
    return {"path": path, "content": revision}
