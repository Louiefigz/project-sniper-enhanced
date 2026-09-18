"""Fail-closed lifecycle for the single governed Palmier candidate slot."""
from __future__ import annotations

import json
import os
from typing import Any

from palmier.candidate_receipt import load_candidate, save_candidate
from palmier.mcp_client import PalmierError
from palmier.native_qc_archive import archive_discarded_candidate
from palmier.native_qc_authority import identity, restore_parent
from palmier.native_qc_contract import load_qc, now, qc_path, save_qc
from palmier.timeline_authority import (TimelineConflict, compare_authority,
                                        load_authority, read_active)

_UNRESOLVED = {"staged", "edited", "qc-approved", "quarantined",
               "quarantined-recovered"}
_RESOLVED = {"promoted", "superseded-manual"}


def _archive_path(candidate: dict) -> str | None:
    qc = candidate.get("qc") or {}
    resolution = candidate.get("resolution") or {}
    value = resolution.get("archivePath") or qc.get("archivePath")
    return value if isinstance(value, str) else None


def _valid_archive(out_dir: str, candidate: dict, state: str) -> bool:
    archive = _archive_path(candidate)
    if archive is None or not os.path.isabs(archive):
        return False
    try:
        inside = os.path.commonpath(
            [os.path.realpath(out_dir), os.path.realpath(archive)]) \
            == os.path.realpath(out_dir)
        with open(os.path.join(archive, "archive.json"), encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    expected = {key: candidate.get(key) for key in
                ("projectId", "timelineId", "fingerprint")}
    return inside and manifest.get("schemaVersion") == 1 \
        and manifest.get("state") == state \
        and manifest.get("candidate") == expected


def _blocked_message(status: object) -> str:
    if status == "qc-approved":
        action = "use the approved candidate, or choose Discard candidate & keep parent"
    elif status in ("quarantined", "quarantined-recovered"):
        action = "choose Discard candidate & keep parent to archive the failure"
    else:
        action = "review it and run candidate QC, or choose Discard candidate & keep parent"
    return (f"A Palmier AI candidate is already {status}; {action} before asking "
            "AI for another change. Its receipt and QC evidence were preserved.")


def assert_candidate_slot_available(out_dir: str) -> None:
    """Refuse a new fork until the prior candidate has a durable resolution."""
    candidate = load_candidate(out_dir)
    if candidate is None or candidate.get("status") in _RESOLVED:
        return
    status = candidate.get("status")
    if status == "qc-rejected" and _valid_archive(
            out_dir, candidate, "qc-rejected"):
        return
    if status == "discarded" and _valid_archive(out_dir, candidate, "discarded"):
        return
    if status in _UNRESOLVED:
        raise PalmierError(_blocked_message(status))
    raise PalmierError(
        "The prior Palmier candidate has no verified lifecycle resolution; "
        "its receipt was preserved and a new AI fork was refused.")


def _optional_qc(out_dir: str, candidate: dict) -> tuple[dict, bool]:
    if not os.path.isfile(qc_path(out_dir)):
        return {"schemaVersion": 1, "status": "not-started"}, False
    receipt = load_qc(out_dir)
    receipt_candidate = receipt.get("candidate")
    if not isinstance(receipt_candidate, dict) \
            or identity(receipt_candidate) != identity(candidate):
        return {"schemaVersion": 1, "status": "not-started"}, False
    return receipt, True


def _visible_is_safe(client: Any, parent: dict, candidate: dict) -> str:
    visible = read_active(client, str(parent.get("projectId")))
    if visible.timeline_id == parent.get("timelineId"):
        if compare_authority(parent, visible) != "unchanged":
            raise TimelineConflict("Palmier parent changed before candidate discard")
        return "parent"
    if visible.timeline_id != candidate.get("timelineId"):
        raise TimelineConflict(
            "Palmier is showing another timeline; nothing was switched or discarded")
    if compare_authority(candidate, visible) != "unchanged":
        raise TimelineConflict(
            "the visible Palmier candidate changed manually; its newer edit remains "
            "active and was not discarded")
    return "candidate"


def _require_same_visible(client: Any, expected: dict, label: str) -> Any:
    visible = read_active(client, str(expected.get("projectId")))
    if visible.timeline_id != expected.get("timelineId"):
        raise TimelineConflict(
            "Palmier switched timelines while the candidate was being archived; "
            "nothing was switched or discarded")
    if compare_authority(expected, visible) != "unchanged":
        raise TimelineConflict(
            f"the visible Palmier {label} changed while the candidate was being "
            "archived; its newer edit remains active and was not discarded")
    return visible


def discard_candidate(client: Any, out_dir: str) -> dict:
    """Archive one unresolved candidate, restore its exact parent, then resolve it."""
    parent, candidate = load_authority(out_dir), load_candidate(out_dir)
    if parent is None or candidate is None or candidate.get("status") not in _UNRESOLVED:
        raise PalmierError("there is no unresolved Palmier candidate to discard")
    if candidate.get("base") != identity(parent):
        raise TimelineConflict("Palmier candidate parent is stale; nothing was discarded")
    visible_kind = _visible_is_safe(client, parent, candidate)
    qc, current_qc = _optional_qc(out_dir, candidate)
    reason = {"schemaVersion": 1, "reason": "operator-discard",
              "reviewArtifacts": [], "discardedAt": now()}
    archive = archive_discarded_candidate(
        out_dir, candidate, qc, reason)
    expected = parent if visible_kind == "parent" else candidate
    visible_now = _require_same_visible(client, expected, visible_kind)
    restored = visible_now if visible_kind == "parent" \
        else restore_parent(client, parent)
    discarded_at = reason["discardedAt"]
    if current_qc:
        save_qc(out_dir, {**qc, "status": "discarded", "resolution": {
            "kind": "operator-discard", "archivePath": archive,
            "discardedAt": discarded_at}})
    candidate.update({"status": "discarded", "qc": {
        "status": "discarded", "approved": False}, "resolution": {
            "kind": "operator-discard", "archivePath": archive,
            "discardedAt": discarded_at}})
    saved = save_candidate(out_dir, candidate)
    return {"schemaVersion": 1, "status": "discarded",
            "candidate": identity(saved), "parent": identity(restored),
            "archivePath": archive, "discardedAt": discarded_at}
