"""First-class P2 picture-lock and supersession contracts."""
from __future__ import annotations

from dataclasses import dataclass

from edit.exact_timing import FrameRange
from edit.picture_lock_common import (
    PictureLockError,
    canonical_json,
    content_hash,
    require_hash,
)
from edit.picture_lock_mapping import (
    MappingProofInput,
    MappingSpan,
    merged_frame_ranges,
    prove_unchanged_mapping,
)

_WORKFLOW_POLICIES = {"cut-first", "autopilot"}
_APPROVERS = {"operator", "system-policy"}


@dataclass(frozen=True)
class SelectedApproval:
    """The workflow-selected approval that turns an approved cut into a lock."""

    approver: str
    approval_policy_hash: str
    approval_receipt_hash: str

    def to_dict(self) -> dict[str, str]:
        """Validate and serialize selected approval authority."""
        if self.approver not in _APPROVERS:
            raise PictureLockError("picture-lock approver is unsupported")
        return {
            "approver": self.approver,
            "approvalPolicyHash": require_hash(
                self.approval_policy_hash, "approval policy hash"),
            "approvalReceiptHash": require_hash(
                self.approval_receipt_hash, "approval receipt hash"),
        }


@dataclass(frozen=True)
class CompatibilityLockEvidence:
    """Read-only evidence required to migrate a P1 compatibility lock."""

    lock_hash: str
    approved_cut_revision_hash: str
    plan_content_hash: str
    timeline_map_hash: str
    source_snapshot_set_hash: str
    transcript_timing_hash: str
    cut_approval_receipt_hash: str
    cut_review_approval_receipt_hash: str


@dataclass(frozen=True)
class PictureLockInput:
    """All immutable inputs to one first-class ``PictureLockV1``."""

    approved_cut_revision_hash: str
    plan_content_hash: str
    timeline_map_hash: str
    source_snapshot_set_hash: str
    transcript_timing_hash: str
    cut_approval_receipt_hash: str
    cut_review_approval_receipt_hash: str
    workflow_policy: str
    selected_approval: SelectedApproval
    compatibility_ancestor: CompatibilityLockEvidence | None = None
    parent_picture_lock_hash: str | None = None


def _assert_compatibility_unchanged(item: PictureLockInput) -> None:
    ancestor = item.compatibility_ancestor
    if ancestor is None:
        return
    comparisons = (
        ("approved cut", item.approved_cut_revision_hash,
         ancestor.approved_cut_revision_hash),
        ("plan content", item.plan_content_hash, ancestor.plan_content_hash),
        ("timeline map", item.timeline_map_hash, ancestor.timeline_map_hash),
        ("source snapshot", item.source_snapshot_set_hash,
         ancestor.source_snapshot_set_hash),
        ("transcript timing", item.transcript_timing_hash,
         ancestor.transcript_timing_hash),
        ("cut approval", item.cut_approval_receipt_hash,
         ancestor.cut_approval_receipt_hash),
        ("cut review approval", item.cut_review_approval_receipt_hash,
         ancestor.cut_review_approval_receipt_hash),
    )
    changed = [label for label, current, previous in comparisons
               if current != previous]
    if changed:
        raise PictureLockError(
            "compatibility lock cut changed before selected-policy approval: "
            + ", ".join(changed))


def mint_picture_lock(item: PictureLockInput) -> tuple[dict[str, object], str]:
    """Mint a deterministic first-class lock; never reinterpret P1 authority."""
    if item.workflow_policy not in _WORKFLOW_POLICIES:
        raise PictureLockError("workflow policy is unsupported")
    _assert_compatibility_unchanged(item)
    payload: dict[str, object] = {
        "schemaVersion": 1,
        "approvedCutRevisionHash": require_hash(
            item.approved_cut_revision_hash, "approved cut revision hash"),
        "planContentHash": require_hash(item.plan_content_hash, "plan content hash"),
        "timelineMapHash": require_hash(item.timeline_map_hash, "timeline map hash"),
        "sourceSnapshotSetHash": require_hash(
            item.source_snapshot_set_hash, "source snapshot set hash"),
        "transcriptTimingHash": require_hash(
            item.transcript_timing_hash, "transcript timing hash"),
        "cutApprovalReceiptHash": require_hash(
            item.cut_approval_receipt_hash, "cut approval receipt hash"),
        "cutReviewApprovalReceiptHash": require_hash(
            item.cut_review_approval_receipt_hash,
            "cut review approval receipt hash"),
        "requiredCleanReviews": 2,
        "workflowPolicy": item.workflow_policy,
        "selectedApproval": item.selected_approval.to_dict(),
    }
    if item.compatibility_ancestor is not None:
        payload["compatibilityAncestorHash"] = require_hash(
            item.compatibility_ancestor.lock_hash,
            "compatibility ancestor hash")
    if item.parent_picture_lock_hash is not None:
        payload["parentPictureLockHash"] = require_hash(
            item.parent_picture_lock_hash, "parent picture-lock hash")
    return payload, content_hash(payload)


@dataclass(frozen=True)
class SupersessionInput:
    """Inputs to one parent→child non-ripple lock transition."""

    parent_picture_lock_hash: str
    child_picture_lock_hash: str
    repair_operation_hash: str
    parent_timeline_map_hash: str
    child_timeline_map_hash: str
    dirty_windows: tuple[FrameRange, ...]
    mapping_proof: MappingProofInput
    superseded_clause_ids: tuple[str, ...]
    successor_clause_ids: tuple[str, ...]
    revalidated_operation_ids: tuple[str, ...]


def _mapping_proof_hash(item: SupersessionInput) -> str:
    proof = item.mapping_proof
    if proof.parent_timeline_map_hash != item.parent_timeline_map_hash \
            or proof.child_timeline_map_hash != item.child_timeline_map_hash:
        raise PictureLockError(
            "mapping proof timeline hashes do not match supersession")
    expected = [row.to_dict() for row in merged_frame_ranges(
        item.dirty_windows)]
    actual = [row.to_dict() for row in merged_frame_ranges(
        proof.dirty_windows)]
    if expected != actual:
        raise PictureLockError(
            "mapping proof dirty windows do not match supersession")
    _, proof_hash = prove_unchanged_mapping(proof)
    return proof_hash


def mint_supersession(item: SupersessionInput) -> tuple[dict, str]:
    """Mint lineage only when every superseded clause has one successor."""
    if item.parent_picture_lock_hash == item.child_picture_lock_hash:
        raise PictureLockError("supersession child must differ from its parent")
    if len(item.superseded_clause_ids) != len(item.successor_clause_ids):
        raise PictureLockError(
            "every superseded clause requires one explicit successor")
    if not item.dirty_windows:
        raise PictureLockError("supersession requires an authorized dirty window")
    identifier_lists = (
        item.superseded_clause_ids, item.successor_clause_ids,
        item.revalidated_operation_ids,
    )
    if any(any(not isinstance(value, str) or not value for value in rows)
           or len(set(rows)) != len(rows) for rows in identifier_lists):
        raise PictureLockError("supersession identifiers must be non-empty and unique")
    payload = {
        "schemaVersion": 1,
        "parentPictureLockHash": require_hash(
            item.parent_picture_lock_hash, "parent picture-lock hash"),
        "childPictureLockHash": require_hash(
            item.child_picture_lock_hash, "child picture-lock hash"),
        "repairOperationHash": require_hash(
            item.repair_operation_hash, "repair operation hash"),
        "parentTimelineMapHash": require_hash(
            item.parent_timeline_map_hash, "parent timeline map hash"),
        "childTimelineMapHash": require_hash(
            item.child_timeline_map_hash, "child timeline map hash"),
        "authorizedDirtyWindows": [
            row.to_dict() for row in merged_frame_ranges(item.dirty_windows)],
        "unchangedMappingProofHash": _mapping_proof_hash(item),
        "supersededClauseIds": list(item.superseded_clause_ids),
        "successorClauseIds": list(item.successor_clause_ids),
        "revalidatedCommittedOperationIds": list(
            item.revalidated_operation_ids),
    }
    return payload, content_hash(payload)
