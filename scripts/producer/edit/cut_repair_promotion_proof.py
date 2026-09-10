#!/usr/bin/env python3
"""Mint non-media P2 promotion proof from controller-verified authority."""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass

from captions.caption_fingerprints import canonical_digest
from captions.cut_repair_dialogue_authority import (
    parse_cut_repair_caption_authority,
)
from edit.exact_timing import FrameRange, PositiveRational, SampleRange
from edit.picture_lock import (
    PictureLockInput,
    SelectedApproval,
    SupersessionInput,
    mint_picture_lock,
    mint_supersession,
)
from edit.picture_lock_common import (
    PictureLockError,
    canonical_json,
    content_hash,
    require_hash,
)
from edit.picture_lock_mapping import MappingProofInput, MappingSpan
from palmier.cut_repair_projection import (
    PalmierRepairProjectionInput,
    project_cut_repair,
)

_INPUT_KEYS = {
    "schemaVersion", "kind", "operation", "operationHash",
    "fragmentReceipt", "compositeReceipt", "reviewRevision",
    "reviewRevisionHash", "reviewReceiptHash", "promotionEvidenceHash",
    "selectedApproval", "workflowPolicy", "contextSegments",
    "childCutTrack", "projectFps", "palmierSelected",
    "captionDialogueAuthority",
}


@dataclass(frozen=True)
class PromotionProofInput:
    """Verified controller values required to mint one diagnostic proof."""

    value: dict
    operation: dict
    operation_hash: str
    revision: dict
    revision_hash: str


def _object(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise PictureLockError(f"{label} must be an object")
    return value


def _input(value: object) -> PromotionProofInput:
    row = _object(value, "promotion proof input")
    if set(row) != _INPUT_KEYS or row.get("schemaVersion") != 1 \
            or row.get("kind") != "cut-repair-promotion-proof-input":
        raise PictureLockError("promotion proof input is not closed")
    operation = _object(row["operation"], "repair operation")
    operation_hash = require_hash(
        row["operationHash"], "repair operation hash")
    revision = _object(row["reviewRevision"], "review revision")
    revision_hash = require_hash(
        row["reviewRevisionHash"], "review revision hash")
    if content_hash(operation) != operation_hash \
            or content_hash(revision) != revision_hash \
            or revision.get("workflowState") != "CUT_REVIEW":
        raise PictureLockError(
            "promotion proof input does not bind the CUT_REVIEW revision")
    return PromotionProofInput(
        row, operation, operation_hash, revision, revision_hash)


def _approval(row: dict) -> SelectedApproval:
    value = _object(row["selectedApproval"], "selected approval")
    if set(value) != {
            "approver", "approvalPolicyHash", "approvalReceiptHash"}:
        raise PictureLockError("selected approval is not closed")
    return SelectedApproval(
        str(value["approver"]),
        require_hash(value["approvalPolicyHash"], "approval policy"),
        require_hash(value["approvalReceiptHash"], "approval receipt"),
    )


def _picture_lock(item: PromotionProofInput) -> tuple[dict, str]:
    row, revision = item.value, item.revision
    selected = _approval(row)
    return mint_picture_lock(PictureLockInput(
        approved_cut_revision_hash=item.revision_hash,
        plan_content_hash=require_hash(
            revision["planContentHash"], "review plan content"),
        timeline_map_hash=require_hash(
            revision["timelineMapHash"], "review timeline map"),
        source_snapshot_set_hash=require_hash(
            revision["sourceSnapshotSetHash"], "source snapshot set"),
        transcript_timing_hash=require_hash(
            revision["transcriptTimingHash"], "transcript timing"),
        cut_approval_receipt_hash=require_hash(
            row["promotionEvidenceHash"], "promotion evidence"),
        cut_review_approval_receipt_hash=selected.approval_receipt_hash,
        workflow_policy=str(row["workflowPolicy"]),
        selected_approval=selected,
        parent_picture_lock_hash=str(
            item.operation["parentPictureLockHash"]),
    ))


def _span(value: object, position: int) -> MappingSpan:
    row = _object(value, f"context segment {position}")
    frames = _object(row.get("outputFrames"), "segment output frames")
    samples = _object(row.get("sourceSamples"), "segment source samples")
    source_id = row.get("sourceId")
    if not isinstance(source_id, str) or not source_id:
        raise PictureLockError("context segment source identity is empty")
    return MappingSpan(
        FrameRange(
            frames.get("startFrame"), frames.get("endFrameExclusive")),
        source_id,
        SampleRange(
            samples.get("startSample"), samples.get("endSampleExclusive")),
    )


def _dirty(operation: dict) -> tuple[FrameRange, ...]:
    rows = operation.get("pictureDirtyWindows") or \
        operation.get("audioDirtyWindows")
    if not isinstance(rows, list) or not rows:
        raise PictureLockError("repair operation has no dirty window")
    return tuple(FrameRange(
        _object(row, "dirty window").get("startFrame"),
        _object(row, "dirty window").get("endFrameExclusive"),
    ) for row in rows)


def _supersession(
    item: PromotionProofInput,
    child_lock_hash: str,
) -> tuple[dict, str]:
    segments = item.value["contextSegments"]
    if not isinstance(segments, list) or not segments:
        raise PictureLockError("promotion proof has no context segments")
    spans = tuple(_span(row, index) for index, row in enumerate(segments))
    operation = item.operation
    dirty = _dirty(operation)
    mapping = MappingProofInput(
        str(operation["parentTimelineMapHash"]),
        str(item.revision["timelineMapHash"]),
        spans, spans, dirty, int(operation["totalOutputFramesAfter"]),
    )
    revalidated = operation.get("revalidatedDependentIds")
    if not isinstance(revalidated, list):
        raise PictureLockError("repair dependency revalidation is absent")
    return mint_supersession(SupersessionInput(
        str(operation["parentPictureLockHash"]), child_lock_hash,
        item.operation_hash, str(operation["parentTimelineMapHash"]),
        str(item.revision["timelineMapHash"]), dirty, mapping, (), (),
        tuple(str(value) for value in revalidated),
    ))


def _caption(item: PromotionProofInput) -> dict:
    authority = item.value["captionDialogueAuthority"]
    if authority is not None:
        parsed = parse_cut_repair_caption_authority(authority)
        if parsed["operationHash"] != item.operation_hash:
            raise PictureLockError(
                "caption dialogue authority binds another repair operation")
        return parsed["captionRevalidation"]
    windows = [
        [row.start_frame, row.end_frame_exclusive]
        for row in _dirty(item.operation)
    ]
    payload = {
        "schemaVersion": 1,
        "kind": "caption-repair-revalidation",
        "operationHash": item.operation_hash,
        "authorizedDirtyWindows": windows,
        "status": "not-present",
    }
    return {
        **payload,
        "revalidationHash": canonical_digest(
            "sniper-caption-repair-revalidation-v1", payload),
    }


def _palmier(
    item: PromotionProofInput,
    fragment: dict,
) -> dict:
    track = item.value["childCutTrack"]
    selected = item.value["palmierSelected"]
    if not isinstance(track, list) or type(selected) is not bool:
        raise PictureLockError("Palmier promotion inputs are malformed")
    return project_cut_repair(PalmierRepairProjectionInput(
        item.operation, item.operation_hash, tuple(track),
        PositiveRational.from_value(item.value["projectFps"]), selected,
        fragment["retime"],
    ))


def build_promotion_proof(value: object) -> dict:
    """Mint the lock/lineage/caption/Palmier proof without rerendering media."""
    item = _input(value)
    child_lock, child_lock_hash = _picture_lock(item)
    supersession, supersession_hash = _supersession(item, child_lock_hash)
    caption = _caption(item)
    fragment = _object(item.value["fragmentReceipt"], "fragment receipt")
    palmier = _palmier(item, fragment)
    composite = _object(item.value["compositeReceipt"], "composite receipt")
    proof = {
        "schemaVersion": 1, "kind": "cut-repair-invariant-proof",
        "operationHash": item.operation_hash,
        "fragmentReceiptHash": content_hash(fragment),
        "childPictureLockHash": child_lock_hash,
        "supersessionHash": supersession_hash,
        "palmierDispositionHash": content_hash(palmier),
        "captionRevalidationHash": caption["revalidationHash"],
        "terminalCompositeProved": True,
        "terminalCompositeReceiptHash": content_hash(composite),
        "totalOutputFramesPreserved":
            item.operation["totalOutputFramesBefore"]
            == item.operation["totalOutputFramesAfter"],
    }
    return {
        "schemaVersion": 1, "kind": "cut-repair-candidate",
        "status": "candidate-proved", "operationHash": item.operation_hash,
        "fragmentReceipt": fragment,
        "childPictureLock": child_lock,
        "childPictureLockHash": child_lock_hash,
        "supersessionReceipt": supersession,
        "supersessionHash": supersession_hash,
        "palmierDisposition": palmier,
        "captionRevalidation": caption,
        "compositeReceipt": composite,
        "invariantProof": proof,
        "invariantProofHash": content_hash(proof),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    args = parser.parse_args()
    try:
        with open(args.input, encoding="utf-8") as handle:
            result = build_promotion_proof(json.load(handle))
        print(canonical_json(result))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(canonical_json({"ok": False, "error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
