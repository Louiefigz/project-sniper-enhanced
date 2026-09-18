"""Four explicit phases for Palmier-native candidate QC and CAS promotion."""
from __future__ import annotations

import json
import os
from typing import Any

from fingerprints import file_sha256
from palmier.candidate_receipt import load_candidate, save_candidate
from palmier.editable_parity_contract import validate_parity
from palmier.master import authority_hash as master_authority_hash
from palmier.mcp_client import PalmierError
from palmier.native_qc_audit import run_native_audit, structural_proof
from palmier.native_qc_authority import (
    PromotionProof, activate_and_read, fresh_promotion_pair, identity,
    read_candidate_restoring_parent)
from palmier.candidate_qc_contract import (authority_from_input,
                                           validate_current_authority)
from palmier.native_qc_contract import (
    approval_digest, audit_path, load_qc, now, save_qc, stable_hash,
    validate_export, validate_reviews)
from palmier.native_qc_export import export_candidate
from palmier.timeline_authority import (
    TimelineConflict, compare_authority, load_authority, promote_candidate,
    read_active)


def _records(out_dir: str, statuses: set[str]) -> tuple[dict, dict]:
    parent, candidate = load_authority(out_dir), load_candidate(out_dir)
    if parent is None or candidate is None:
        raise PalmierError("Palmier native QC requires saved parent and candidate records")
    if candidate.get("status") not in statuses:
        expected = ", ".join(sorted(statuses))
        raise PalmierError(f"Palmier candidate must be {expected}")
    if candidate.get("base") != identity(parent):
        raise TimelineConflict("Palmier candidate parent authority is stale")
    return parent, candidate


def _candidate_receipt(candidate: dict, found: Any,
                       structural: dict) -> dict:
    return {**identity(candidate), "fingerprint": found.fingerprint,
            "semanticFingerprint": found.semantic_fingerprint,
            "structuralDigest": structural["digest"],
            "readbackCoverage": found.coverage,
            "requestHash": candidate.get("requestHash"),
            "lanes": candidate.get("lanes"),
            "nativePlanHash": candidate.get("nativePlanHash"),
            "operations": candidate.get("operations")}


def _same_snapshot(left: Any, right: Any, label: str) -> None:
    if (left.project_id, left.timeline_id, left.fingerprint) != (
            right.project_id, right.timeline_id, right.fingerprint):
        raise TimelineConflict(f"Palmier {label} changed during candidate QC")


def prepare_qc(client: Any, out_dir: str, authority_path: str,
               timing: dict | None = None) -> dict:
    """Fresh-read, export, re-read, and stage evidence without approving it."""
    parent, candidate = _records(out_dir, {"edited"})
    parent_before, candidate_before = read_candidate_restoring_parent(
        client, parent, candidate)
    structural = structural_proof(candidate_before)
    if structural["status"] != "pass":
        raise PalmierError("Palmier candidate graph failed structural preflight")
    export = export_candidate(client, out_dir, candidate_before, timing)
    parent_after, candidate_after = read_candidate_restoring_parent(
        client, parent, candidate)
    _same_snapshot(parent_before, parent_after, "parent")
    _same_snapshot(candidate_before, candidate_after, "candidate")
    candidate_row = _candidate_receipt(candidate, candidate_after, structural)
    authority = authority_from_input(out_dir, authority_path,
                                     candidate_row, identity(parent_after))
    receipt = {
        "schemaVersion": 1, "status": "prepared", "outDir": out_dir,
        "projectId": parent_after.project_id,
        "parent": identity(parent_after), "candidate": candidate_row,
        "export": export, "authority": authority,
        "preparedAt": now(),
    }
    saved = save_qc(out_dir, receipt)
    candidate.update({"qc": {"status": "prepared", "approved": False,
                              "receiptPath": os.path.join(out_dir,
                                                          "palmier.native-qc.json")}})
    save_candidate(out_dir, candidate)
    return saved


def _audit_current(receipt: dict, found: Any) -> None:
    deterministic = receipt.get("deterministic")
    if not isinstance(deterministic, dict) or deterministic.get("status") != "pass":
        raise PalmierError("Palmier candidate deterministic Audit B is not passing")
    content = {key: deterministic[key] for key in (
        "schemaVersion", "stage", "candidateFingerprint", "exportHash",
        "inputAuthorityDigest", "checks", "frames")}
    if stable_hash(content) != deterministic.get("digest"):
        raise PalmierError("Palmier native deterministic audit digest is invalid")
    authority, export = (receipt.get("authority") or {},
                         receipt.get("export") or {})
    if deterministic.get("exportHash") != export.get("hash") \
            or deterministic.get("inputAuthorityDigest") \
            != authority.get("inputDigest"):
        raise PalmierError("Palmier native deterministic audit binding is stale")
    path = deterministic.get("auditPath")
    if path != audit_path(receipt["outDir"]) or not os.path.isfile(path) \
            or file_sha256(path) != deterministic.get("auditHash"):
        raise PalmierError("Palmier native deterministic audit artifact changed")
    if deterministic.get("candidateFingerprint") != found.fingerprint:
        raise PalmierError("Palmier native deterministic audit candidate is stale")
    if authority.get("kind") in {"live-build", "desktop-build"}:
        master_hash = master_authority_hash(
            receipt["outDir"], authority["planHash"])
        parity = validate_parity(
            receipt["outDir"], receipt["export"]["hash"], master_hash)
        parity_check = next((row for row in deterministic.get("checks") or []
                             if isinstance(row, dict)
                             and row.get("name") == "editable_master_parity"), None)
        evidence = parity_check.get("evidence") \
            if isinstance(parity_check, dict) else None
        if not isinstance(evidence, dict) or parity_check.get("measured") \
                != parity.get("digest") \
                or not os.path.isfile(str(evidence.get("path"))) \
                or file_sha256(evidence["path"]) != evidence.get("hash"):
            raise PalmierError("Palmier editable parity evidence is stale")
    for frame in deterministic.get("frames") or []:
        if not isinstance(frame, dict) or not os.path.isfile(str(frame.get("path"))) \
                or file_sha256(frame["path"]) != frame.get("hash"):
            raise PalmierError("Palmier native deterministic review frame changed")


def validate_current_audit(receipt: dict, found: Any) -> None:
    """Public shared validator for native and Desktop approval paths."""
    _audit_current(receipt, found)


def run_deterministic_qc(client: Any, out_dir: str) -> dict:
    receipt = load_qc(out_dir, {"prepared", "deterministic-passed"})
    parent, candidate = _records(out_dir, {"edited"})
    parent_before, candidate_before = read_candidate_restoring_parent(
        client, parent, candidate)
    validate_current_authority(receipt)
    validate_export(receipt)
    structural = structural_proof(candidate_before)
    if structural["digest"] != receipt["candidate"].get("structuralDigest"):
        raise TimelineConflict("Palmier candidate structure changed before Audit B")
    deterministic = run_native_audit(out_dir, receipt, candidate_before)
    parent_after, candidate_after = read_candidate_restoring_parent(
        client, parent, candidate)
    _same_snapshot(parent_before, parent_after, "parent")
    _same_snapshot(candidate_before, candidate_after, "candidate")
    updated = {**receipt, "status": "deterministic-passed",
               "deterministic": deterministic, "auditedAt": now()}
    return save_qc(out_dir, updated)


def _load_reviews(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise PalmierError(f"cannot read Palmier native rendered reviews: {exc}") from exc
    if not isinstance(value, dict):
        raise PalmierError("Palmier native rendered reviews are not an object")
    return value


def finalize_approval(client: Any, out_dir: str, reviews_path: str) -> dict:
    """Record explicit external review passes; never run or imply a critic."""
    receipt = load_qc(out_dir, {"deterministic-passed", "qc-approved"})
    parent, candidate = _records(out_dir, {"edited", "qc-approved"})
    _parent_now, candidate_now = read_candidate_restoring_parent(
        client, parent, candidate)
    validate_current_authority(receipt)
    validate_export(receipt)
    _audit_current(receipt, candidate_now)
    reviews = validate_reviews(_load_reviews(reviews_path), receipt)
    if receipt.get("status") == "qc-approved":
        return _repair_candidate_approval(out_dir, candidate, receipt)
    approved = {**receipt, "status": "qc-approved", "reviews": reviews,
                "approvedAt": now()}
    approved["approvalDigest"] = approval_digest(approved)
    save_qc(out_dir, approved)
    candidate.update({"status": "qc-approved", "fingerprint": candidate_now.fingerprint,
                      "qc": {"status": "approved", "approved": True,
                             "approvalDigest": approved["approvalDigest"]}})
    save_candidate(out_dir, candidate)
    return approved


def _repair_candidate_approval(out_dir: str, candidate: dict,
                               receipt: dict) -> dict:
    if approval_digest(receipt) != receipt.get("approvalDigest"):
        raise PalmierError("Palmier native QC approval digest is invalid")
    candidate.update({"status": "qc-approved", "qc": {
        "status": "approved", "approved": True,
        "approvalDigest": receipt["approvalDigest"]}})
    save_candidate(out_dir, candidate)
    return receipt


def _validate_approval(receipt: dict, candidate_now: Any) -> None:
    validate_current_authority(receipt)
    validate_export(receipt)
    _audit_current(receipt, candidate_now)
    if approval_digest(receipt) != receipt.get("approvalDigest"):
        raise PalmierError("Palmier native QC approval digest is invalid")
    validate_reviews({"schemaVersion": 1,
                      "reviews": list((receipt.get("reviews") or {}).values())}, receipt)


def validate_approved_candidate(receipt: dict, candidate_now: Any) -> None:
    """Public non-mutating revalidation used by the durable commit saga."""
    _validate_approval(receipt, candidate_now)


def _activate_and_publish(client: Any, out_dir: str, visible: Any,
                          candidate: dict, receipt: dict,
                          parent_now: Any, candidate_now: Any) -> dict:
    try:
        active = activate_and_read(client, candidate_now.project_id,
                                   candidate_now.timeline_id)
        _same_snapshot(candidate_now, active, "candidate")
        return promote_candidate(out_dir, PromotionProof(
            candidate, receipt, parent_now, active))
    except BaseException as failure:
        try:
            restored = activate_and_read(client, visible.project_id,
                                         visible.timeline_id)
            _same_snapshot(visible, restored, "previously visible timeline")
        except BaseException as restore_error:
            raise PalmierError(
                f"Palmier promotion failed and visible-head recovery failed: "
                f"{restore_error}") from failure
        raise


def promote_approved(client: Any, out_dir: str) -> dict:
    """Validate, final CAS, activate+verify, then atomically move both heads."""
    receipt = load_qc(out_dir, {"qc-approved", "promoted"})
    candidate = load_candidate(out_dir)
    canonical = load_authority(out_dir)
    if candidate is None or canonical is None:
        raise PalmierError("Palmier promotion state is incomplete")
    approved_head = canonical.get("approvedHead") or {}
    already = (canonical.get("timelineId") == candidate.get("timelineId")
               and approved_head.get("qcApprovalDigest")
               == receipt.get("approvalDigest"))
    if already:
        current = read_active(client, str(canonical.get("projectId")))
        if compare_authority(canonical, current) != "unchanged":
            raise TimelineConflict(
                "approved Palmier head is not the visible current timeline")
        _validate_approval(receipt, current)
        return _finish_promoted(out_dir, canonical, candidate, receipt)
    if candidate.get("status") != "qc-approved":
        raise PalmierError("Palmier candidate is not QC-approved")
    visible = read_active(client, str(canonical.get("projectId")))
    parent_before, candidate_before = fresh_promotion_pair(
        client, canonical, candidate)
    _validate_approval(receipt, candidate_before)
    parent_now, candidate_now = fresh_promotion_pair(
        client, canonical, candidate)
    _same_snapshot(parent_before, parent_now, "parent")
    _same_snapshot(candidate_before, candidate_now, "candidate")
    promoted = _activate_and_publish(
        client, out_dir, visible, candidate, receipt, parent_now, candidate_now)
    return _finish_promoted(out_dir, promoted, candidate, receipt)


def _finish_promoted(out_dir: str, authority: dict, candidate: dict,
                     receipt: dict) -> dict:
    candidate.update({"status": "promoted", "promotedAt": now()})
    save_candidate(out_dir, candidate)
    updated = {**receipt, "status": "promoted", "promotedAt": now(),
               "approvedHead": authority["approvedHead"]}
    save_qc(out_dir, updated)
    return updated
