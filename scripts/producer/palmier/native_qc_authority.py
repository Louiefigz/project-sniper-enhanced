"""Fresh-read CAS and working/approved-head authority for native candidates."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from palmier.mcp_client import PalmierError
from palmier.timeline_authority import (
    TimelineConflict, TimelineSnapshot, atomic_write_record, authority_path,
    compare_authority, load_authority, read_active)


@dataclass(frozen=True)
class PromotionProof:
    """Controller-owned fresh evidence for one promotion CAS."""

    candidate_record: dict
    qc_receipt: dict
    parent_now: TimelineSnapshot
    candidate_now: TimelineSnapshot


def identity(value: dict | TimelineSnapshot) -> dict:
    if isinstance(value, TimelineSnapshot):
        return {"projectId": value.project_id, "timelineId": value.timeline_id,
                "fingerprint": value.fingerprint}
    return {key: value.get(key) for key in
            ("projectId", "timelineId", "fingerprint")}


def activate_and_read(client: Any, project_id: str,
                      timeline_id: str) -> TimelineSnapshot:
    """Palmier get_timeline is active-only: activate, then verify exact id."""
    client.call_json("set_active_timeline", {"timelineId": timeline_id})
    found = read_active(client, project_id)
    if found.timeline_id != timeline_id:
        raise TimelineConflict(
            f"Palmier activated {found.timeline_id}, expected {timeline_id}")
    return found


def restore_parent(client: Any, parent: dict) -> TimelineSnapshot:
    project_id, timeline_id = parent.get("projectId"), parent.get("timelineId")
    if not isinstance(project_id, str) or not isinstance(timeline_id, str):
        raise TimelineConflict("Palmier QC parent identity is incomplete")
    restored = activate_and_read(client, project_id, timeline_id)
    if compare_authority(parent, restored) != "unchanged":
        raise TimelineConflict("Palmier QC parent changed while restoring it")
    return restored


def _visible_kind(found: TimelineSnapshot, parent: dict,
                  candidate: dict) -> str:
    """Classify without switching; visible manual drift must remain visible."""
    if found.timeline_id == parent.get("timelineId"):
        if compare_authority(parent, found) != "unchanged":
            raise TimelineConflict(
                "visible Palmier parent changed manually; nothing was switched")
        return "parent"
    if found.timeline_id == candidate.get("timelineId"):
        if compare_authority(candidate, found) != "unchanged":
            raise TimelineConflict(
                "visible Palmier candidate changed manually; rerun from manual truth")
        return "candidate"
    raise TimelineConflict(
        "Palmier is showing another managed timeline; nothing was switched")


def _restore_visible(client: Any, visible: TimelineSnapshot) -> TimelineSnapshot:
    expected = identity(visible)
    restored = activate_and_read(client, visible.project_id, visible.timeline_id)
    if compare_authority(expected, restored) != "unchanged":
        raise TimelineConflict("visible Palmier timeline changed during QC")
    return restored


def read_candidate_restoring_parent(client: Any, parent: dict,
                                    candidate: dict) -> tuple[TimelineSnapshot,
                                                               TimelineSnapshot]:
    """Fresh-read both heads, preserving the initially visible valid head."""
    project_id = parent.get("projectId")
    if not isinstance(project_id, str):
        raise TimelineConflict("Palmier QC parent identity is incomplete")
    visible = read_active(client, project_id)
    kind = _visible_kind(visible, parent, candidate)
    try:
        if kind == "parent":
            parent_now = visible
            candidate_now = activate_and_read(
                client, project_id, str(candidate.get("timelineId")))
        else:
            candidate_now = visible
            parent_now = activate_and_read(
                client, project_id, str(parent.get("timelineId")))
    finally:
        _restore_visible(client, visible)
    if compare_authority(parent, parent_now) != "unchanged":
        raise TimelineConflict("Palmier QC parent changed during fresh readback")
    if compare_authority(candidate, candidate_now) != "unchanged":
        raise TimelineConflict("Palmier candidate changed after it was staged")
    return parent_now, candidate_now


def fresh_promotion_pair(client: Any, parent: dict,
                         candidate: dict) -> tuple[TimelineSnapshot,
                                                   TimelineSnapshot]:
    """Fresh-read both identities without hiding the valid visible head."""
    return read_candidate_restoring_parent(client, parent, candidate)


def _approved_record(found: TimelineSnapshot, canonical: dict,
                     qc: dict) -> dict:
    approved_at = qc.get("approvedAt")
    approved = {
        **identity(found), "semanticFingerprint": found.semantic_fingerprint,
        "exportHash": (qc.get("export") or {}).get("hash"),
        "qcApprovalDigest": qc.get("approvalDigest"),
        "approvedAt": approved_at,
    }
    return {
        "schemaVersion": 1, "authority": "palmier",
        "origin": "sniper-promoted", **identity(found),
        "semanticFingerprint": found.semantic_fingerprint,
        "capturedAt": approved_at, "readbackCoverage": found.coverage,
        "timeline": found.timeline, "workingHead": {
            **identity(found), "semanticFingerprint": found.semantic_fingerprint},
        "approvedHead": approved, "approvalCurrent": True,
        "parent": {"timelineId": canonical.get("timelineId"),
                   "fingerprint": canonical.get("fingerprint")},
    }


def _already_promoted(canonical: dict, proof: PromotionProof) -> bool:
    approved = canonical.get("approvedHead")
    return (canonical.get("timelineId") == proof.candidate_now.timeline_id
            and isinstance(approved, dict)
            and approved.get("fingerprint") == proof.candidate_now.fingerprint
            and approved.get("qcApprovalDigest")
            == proof.qc_receipt.get("approvalDigest"))


def promote_qc_candidate(out_dir: str, proof: object) -> dict:
    """Persist heads only after the controller activated and verified candidate."""
    if not isinstance(proof, PromotionProof):
        raise PalmierError("candidate promotion requires controller-owned fresh proof")
    canonical = load_authority(out_dir)
    if canonical is None:
        raise TimelineConflict("candidate promotion has no canonical parent")
    if _already_promoted(canonical, proof):
        return canonical
    candidate, qc = proof.candidate_record, proof.qc_receipt
    if candidate.get("status") != "qc-approved" or qc.get("status") != "qc-approved":
        raise TimelineConflict("candidate promotion requires current QC approval")
    if compare_authority(canonical, proof.parent_now) != "unchanged":
        raise TimelineConflict("Palmier parent changed before candidate promotion")
    if candidate.get("base") != identity(canonical):
        raise TimelineConflict("QC candidate was not forked from the canonical parent")
    if compare_authority(candidate, proof.candidate_now) != "unchanged":
        raise TimelineConflict("QC candidate changed before promotion")
    receipt_candidate = qc.get("candidate") or {}
    if identity(receipt_candidate) != identity(proof.candidate_now) \
            or qc.get("approvalDigest") != candidate.get("qc", {}).get("approvalDigest"):
        raise TimelineConflict("candidate QC receipt is stale")
    record = _approved_record(proof.candidate_now, canonical, qc)
    atomic_write_record(authority_path(out_dir), record)
    return record
