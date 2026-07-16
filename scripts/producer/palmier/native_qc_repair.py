"""Reject-and-archive lifecycle boundary for separately governed repair."""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from palmier.candidate_receipt import load_candidate, save_candidate
from palmier.mcp_client import PalmierError
from palmier.native_qc_archive import archive_rejected_candidate
from palmier.native_qc_authority import (identity,
                                         read_candidate_restoring_parent,
                                         restore_parent)
from palmier.native_qc_contract import load_qc, now, save_qc
from palmier.timeline_authority import TimelineConflict, load_authority


def _load_reason(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise PalmierError(f"cannot read native QC rejection reason: {exc}") from exc
    expected = {"schemaVersion", "reason", "sourceCandidate", "originalRequest",
                "controllerLanes", "inputAuthorityDigest", "issues",
                "reviewArtifacts"}
    if not isinstance(value, dict) or set(value) != expected \
            or value.get("schemaVersion") != 1:
        raise PalmierError("native QC rejection reason has an invalid envelope")
    if set(value.get("sourceCandidate") or {}) != {"timelineId", "fingerprint"} \
            or set(value.get("originalRequest") or {}) != {"text", "hash"}:
        raise PalmierError("native QC rejection identity/request is malformed")
    if not isinstance(value.get("reason"), str) or not value["reason"].strip() \
            or len(value["reason"]) > 4_000 or not isinstance(value.get("issues"), list) \
            or not isinstance(value.get("reviewArtifacts"), list) \
            or any(not isinstance(item, str) for item in value["reviewArtifacts"]):
        raise PalmierError("native QC rejection details are malformed")
    return value


def _validate_reason(reason: dict, candidate: dict, receipt: dict) -> None:
    authority = receipt.get("authority") or {}
    request = authority.get("request") or {}
    source = reason["sourceCandidate"]
    original = reason["originalRequest"]
    text = original.get("text")
    text_hash = hashlib.sha256(str(text).encode("utf-8")).hexdigest()
    valid = (source == {key: candidate.get(key) for key in
                       ("timelineId", "fingerprint")}
             and isinstance(text, str) and original.get("hash") == text_hash
             and request == original and candidate.get("requestHash") == text_hash
             and reason.get("controllerLanes") == authority.get("lanes")
             and reason.get("controllerLanes") == candidate.get("lanes")
             and reason.get("inputAuthorityDigest") == authority.get("inputDigest"))
    if not valid:
        raise PalmierError("native QC rejection reason is stale or cross-candidate")


def _records(out_dir: str) -> tuple[dict, dict, dict]:
    parent, candidate = load_authority(out_dir), load_candidate(out_dir)
    receipt = load_qc(out_dir, {"prepared", "deterministic-passed",
                                "qc-approved", "qc-rejected"})
    if parent is None or candidate is None or candidate.get("status") \
            not in ("edited", "qc-approved", "qc-rejected"):
        raise PalmierError("native QC rejection has no current pending candidate")
    if candidate.get("base") != identity(parent):
        raise TimelineConflict("native QC rejection candidate parent is stale")
    return parent, candidate, receipt


def _finish(out_dir: str, candidate: dict, receipt: dict, reason: dict,
            archive_path: str, rejected_at: str) -> dict:
    rejection = {"reason": reason, "archivePath": archive_path,
                 "rejectedAt": rejected_at}
    updated = {**receipt, "status": "qc-rejected", "rejection": rejection,
               "archivePath": archive_path, "rejectedAt": rejected_at}
    save_qc(out_dir, updated)
    candidate.update({"status": "qc-rejected", "qc": {
        "status": "rejected", "approved": False,
        "archivePath": archive_path, "rejectedAt": rejected_at}})
    save_candidate(out_dir, candidate)
    return updated


def reject_for_repair(client: Any, out_dir: str, reason_path: str) -> dict:
    """Archive one failed candidate; a repair must create a new governed fork."""
    parent, candidate, receipt = _records(out_dir)
    reason = _load_reason(reason_path)
    _validate_reason(reason, candidate, receipt)
    _parent_now, candidate_now = read_candidate_restoring_parent(
        client, parent, candidate)
    if identity(receipt.get("candidate") or {}) != identity(candidate_now):
        raise TimelineConflict("native QC rejection receipt is stale")
    restore_parent(client, parent)
    existing = (receipt.get("rejection") or {}).get("archivePath")
    archive_path = existing if isinstance(existing, str) else \
        archive_rejected_candidate(out_dir, candidate, receipt, reason)
    if not os.path.isfile(os.path.join(archive_path, "archive.json")):
        raise PalmierError("native QC rejection archive is incomplete")
    rejected_at = receipt.get("rejectedAt") or now()
    return _finish(out_dir, candidate, receipt, reason, archive_path, rejected_at)
