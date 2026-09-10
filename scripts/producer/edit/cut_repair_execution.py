"""Controller-owned P2 candidate execution across media, locks, and Palmier."""
from __future__ import annotations

from dataclasses import dataclass

from captions.caption_repair_revalidation import (
    CaptionRepairContexts,
    revalidate_caption_repair,
)
from edit.exact_timing import FrameRange, PositiveRational
from edit.picture_lock import (
    PictureLockInput,
    SupersessionInput,
    mint_picture_lock,
    mint_supersession,
)
from edit.picture_lock_common import PictureLockError, content_hash
from edit.picture_lock_mapping import MappingProofInput, merged_frame_ranges
from edit.repair_composite import (
    RepairCompositeRequest,
    render_repair_composite,
)
from edit.repair_fragment import render_repair_fragment
from edit.repair_fragment_contracts import RepairFragmentRequest
from palmier.cut_repair_projection import (
    PalmierRepairProjectionInput,
    project_cut_repair,
)


@dataclass(frozen=True)
class CutRepairExecutionInput:
    """All selected evidence needed to execute one private P2 candidate."""

    fragment: RepairFragmentRequest
    child_lock: PictureLockInput
    child_timeline_map_hash: str
    mapping_proof: MappingProofInput
    superseded_clause_ids: tuple[str, ...]
    successor_clause_ids: tuple[str, ...]
    revalidated_operation_ids: tuple[str, ...]
    child_cut_track: tuple[dict[str, object], ...]
    palmier_fps: PositiveRational
    palmier_selected: bool
    composite_output_path: str
    caption_contexts: CaptionRepairContexts


def _dirty_windows(operation: dict[str, object]) -> tuple[FrameRange, ...]:
    rows = operation.get("pictureDirtyWindows") or \
        operation.get("audioDirtyWindows")
    if not isinstance(rows, list) or not rows:
        raise PictureLockError("cut repair has no authorized dirty window")
    parsed = []
    for row in rows:
        if not isinstance(row, dict):
            raise PictureLockError("cut repair dirty window is malformed")
        parsed.append(FrameRange(
            row.get("startFrame"), row.get("endFrameExclusive")))
    return tuple(merged_frame_ranges(parsed))


def _mint_lock(item: CutRepairExecutionInput) -> tuple[dict, str]:
    operation = item.fragment.operation
    parent = operation.get("parentPictureLockHash")
    target = operation.get("target")
    transcript = target.get("transcriptTimingHash") \
        if isinstance(target, dict) else None
    lock = item.child_lock
    if lock.parent_picture_lock_hash != parent \
            or lock.timeline_map_hash != item.child_timeline_map_hash \
            or lock.transcript_timing_hash != transcript:
        raise PictureLockError(
            "child lock does not bind the selected repair authority")
    return mint_picture_lock(lock)


def _mint_supersession(
    item: CutRepairExecutionInput,
    child_lock_hash: str,
) -> tuple[dict, str]:
    operation = item.fragment.operation
    return mint_supersession(SupersessionInput(
        parent_picture_lock_hash=str(
            operation["parentPictureLockHash"]),
        child_picture_lock_hash=child_lock_hash,
        repair_operation_hash=item.fragment.operation_hash,
        parent_timeline_map_hash=str(
            operation["parentTimelineMapHash"]),
        child_timeline_map_hash=item.child_timeline_map_hash,
        dirty_windows=_dirty_windows(operation),
        mapping_proof=item.mapping_proof,
        superseded_clause_ids=item.superseded_clause_ids,
        successor_clause_ids=item.successor_clause_ids,
        revalidated_operation_ids=item.revalidated_operation_ids,
    ))


def _palmier_disposition(
    item: CutRepairExecutionInput,
    fragment: dict[str, object],
) -> dict[str, object]:
    return project_cut_repair(PalmierRepairProjectionInput(
        item.fragment.operation,
        item.fragment.operation_hash,
        item.child_cut_track,
        item.palmier_fps,
        item.palmier_selected,
        fragment["retime"],
    ))


def _composite_candidate(
    item: CutRepairExecutionInput,
    fragment: dict[str, object],
) -> dict[str, object]:
    output = item.composite_output_path
    if not isinstance(output, str) or not output:
        raise PictureLockError(
            "cut repair candidate requires a full composite destination")
    request = item.fragment
    return render_repair_composite(RepairCompositeRequest(
        request.parent_path,
        request.output_path,
        output,
        fragment,
        request.operation_hash,
        request.clock,
        request.tools,
    ))


def execute_cut_repair_candidate(
    item: CutRepairExecutionInput,
) -> dict[str, object]:
    """Build one proved private candidate; it does not advance authority."""
    child_lock, child_lock_hash = _mint_lock(item)
    supersession, supersession_hash = _mint_supersession(
        item, child_lock_hash)
    caption_revalidation = revalidate_caption_repair(
        item.caption_contexts, item.fragment.operation)
    fragment = render_repair_fragment(item.fragment)
    palmier = _palmier_disposition(item, fragment)
    composite = _composite_candidate(item, fragment)
    proof = {
        "schemaVersion": 1,
        "kind": "cut-repair-invariant-proof",
        "operationHash": item.fragment.operation_hash,
        "fragmentReceiptHash": content_hash(fragment),
        "childPictureLockHash": child_lock_hash,
        "supersessionHash": supersession_hash,
        "palmierDispositionHash": content_hash(palmier),
        "captionRevalidationHash":
            caption_revalidation["revalidationHash"],
        "terminalCompositeProved": True,
        "terminalCompositeReceiptHash": content_hash(composite),
        "totalOutputFramesPreserved":
            item.fragment.operation["totalOutputFramesBefore"]
            == item.fragment.operation["totalOutputFramesAfter"],
    }
    result = {
        "schemaVersion": 1,
        "kind": "cut-repair-candidate",
        "status": "candidate-proved",
        "operationHash": item.fragment.operation_hash,
        "fragmentReceipt": fragment,
        "childPictureLock": child_lock,
        "childPictureLockHash": child_lock_hash,
        "supersessionReceipt": supersession,
        "supersessionHash": supersession_hash,
        "palmierDisposition": palmier,
        "captionRevalidation": caption_revalidation,
        "compositeReceipt": composite,
        "invariantProof": proof,
        "invariantProofHash": content_hash(proof),
    }
    return result
