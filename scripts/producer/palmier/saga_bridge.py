#!/usr/bin/env python3
"""Closed Palmier observations for the Producer local/external commit saga."""
from __future__ import annotations

from datetime import datetime, timezone

from palmier.candidate_receipt import load_candidate
from palmier.mcp_client import PalmierError
from palmier.native_qc import validate_approved_candidate
from palmier.native_qc_authority import (
    fresh_promotion_pair, identity)
from palmier.native_qc_contract import load_qc
from palmier.quality_hash import stable_hash
from palmier.timeline_authority import read_active


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _object(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise PalmierError(f"Palmier saga {label} is not an object")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise PalmierError(f"Palmier saga {label} is missing")
    return value


def _records(out_dir: str) -> tuple[dict, dict]:
    candidate = load_candidate(out_dir)
    receipt = load_qc(out_dir, {"qc-approved", "promoted"})
    if candidate is None or candidate.get("status") not in {
            "qc-approved", "promoted"}:
        raise PalmierError("Palmier saga requires one approved candidate")
    qc_candidate = _object(receipt.get("candidate"), "QC candidate")
    if identity(candidate) != identity(qc_candidate):
        raise PalmierError("Palmier saga candidate and QC identities differ")
    return candidate, receipt


def _stable_fields(receipt: dict, candidate_now) -> dict:
    authority = _object(receipt.get("authority"), "QC authority")
    summary = _object(authority.get("summary"), "QC authority summary")
    parent = _object(receipt.get("parent"), "QC parent")
    candidate = _object(receipt.get("candidate"), "QC candidate")
    canvas = {
        key: candidate_now.timeline.get(key)
        for key in ("fps", "width", "height")
    }
    return {
        "schemaVersion": 1,
        "projectId": _string(candidate.get("projectId"), "candidate projectId"),
        "expectedParentId": _string(
            parent.get("timelineId"), "parent timelineId"),
        "expectedParentTimelineHash": _string(
            parent.get("fingerprint"), "parent fingerprint"),
        "candidateId": _string(
            candidate.get("timelineId"), "candidate timelineId"),
        "timelineHash": candidate_now.fingerprint,
        "approvalDigest": _string(
            receipt.get("approvalDigest"), "approval digest"),
        "manifestHash": _string(
            authority.get("manifestHash"), "manifest hash"),
        "inputAuthorityDigest": _string(
            authority.get("inputDigest"), "input authority digest"),
        "transcriptTimingHash": _string(
            summary.get("transcriptDigest"), "transcript digest"),
        "nativePlanHash": _string(
            authority.get("nativePlanHash"), "native plan hash"),
        "canvasProfileHash": stable_hash(canvas),
    }


def _proof(receipt: dict, candidate_now) -> dict:
    stable = _stable_fields(receipt, candidate_now)
    return {
        **stable,
        "ok": True,
        "status": "saga-candidate-proved",
        "candidateHash": stable_hash(stable),
        "provedAt": _now(),
    }


def prove_candidate(client, out_dir: str) -> dict:
    """Fresh-read both reserved heads and return immutable reservation fields."""
    candidate, receipt = _records(out_dir)
    parent = _object(receipt.get("parent"), "QC parent")
    if candidate.get("base") != identity(parent):
        raise PalmierError("Palmier saga candidate parent binding is stale")
    parent_now, candidate_now = fresh_promotion_pair(
        client, parent, candidate)
    if identity(parent_now) != identity(parent):
        raise PalmierError("Palmier saga observed a foreign parent")
    validate_approved_candidate(receipt, candidate_now)
    return _proof(receipt, candidate_now)


def observe_head(client, out_dir: str) -> dict:
    """Observe without switching; exact candidate hashes are all-or-nothing."""
    candidate, receipt = _records(out_dir)
    project_id = _string(candidate.get("projectId"), "candidate projectId")
    found = read_active(client, project_id)
    candidate_hash = None
    timeline_hash = None
    if identity(found) == identity(candidate):
        validate_approved_candidate(receipt, found)
        proof = _proof(receipt, found)
        candidate_hash = proof["candidateHash"]
        timeline_hash = proof["timelineHash"]
    return {
        "schemaVersion": 1,
        "ok": True,
        "status": "saga-head-observed",
        "headId": found.timeline_id,
        "candidateHash": candidate_hash,
        "timelineHash": timeline_hash,
        "observedAt": _now(),
    }
