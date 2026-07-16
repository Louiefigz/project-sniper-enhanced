"""Durable state for non-authoritative Palmier AI candidate timelines."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from palmier.mcp_client import PalmierError
from palmier.timeline_authority import (
    atomic_write_record, candidate_path, compare_authority, load_authority,
    read_active)

STATUSES = {
    "staged", "edited", "qc-approved", "quarantined",
    "quarantined-recovered", "superseded-manual", "promoted", "qc-rejected",
    "discarded",
}


def load_candidate(out_dir: str) -> dict | None:
    """Read one candidate receipt without treating it as timeline authority."""
    try:
        with open(candidate_path(out_dir), encoding="utf-8") as handle:
            value = json.load(handle)
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        raise PalmierError(f"cannot read Palmier timeline candidate: {exc}") from exc
    if not isinstance(value, dict) or value.get("schemaVersion") != 1:
        raise PalmierError("Palmier timeline candidate is not schemaVersion 1")
    return value


def save_candidate(out_dir: str, record: dict) -> dict:
    """Atomically persist a validated candidate lifecycle receipt."""
    if not isinstance(record, dict) or record.get("schemaVersion") != 1 \
            or record.get("status") not in STATUSES:
        raise PalmierError("Palmier candidate receipt is malformed")
    atomic_write_record(candidate_path(out_dir), record)
    return record


def recover_quarantined_parent(client, out_dir: str, sidecar: dict) -> dict:
    """Reactivate the parent without resolving or hiding the quarantine."""
    authority = load_authority(out_dir)
    candidate = load_candidate(out_dir)
    if authority is None or candidate is None:
        raise PalmierError("quarantined candidate recovery has no saved authority")
    if candidate.get("status") != "quarantined":
        raise PalmierError("there is no quarantined Palmier candidate to recover")
    project_id = sidecar.get("projectId")
    if project_id != authority.get("projectId") \
            or candidate.get("base") != {
                key: authority.get(key) for key in
                ("projectId", "timelineId", "fingerprint")}:
        raise PalmierError("quarantined candidate parent authority is stale")
    client.call_json("set_active_timeline", {
        "timelineId": authority["timelineId"]})
    restored = read_active(client, project_id)
    change = compare_authority(authority, restored)
    if change != "unchanged":
        raise PalmierError(f"quarantined parent recovery readback is {change}")
    candidate.update({
        "recovery": {
            "status": "restored", "timelineId": restored.timeline_id,
            "fingerprint": restored.fingerprint,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    })
    return save_candidate(out_dir, candidate)
