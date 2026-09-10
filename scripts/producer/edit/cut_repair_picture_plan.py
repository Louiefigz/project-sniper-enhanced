"""Closed review-plan authoring for the first supportable picture repair."""
from __future__ import annotations

import copy
from dataclasses import dataclass
from decimal import Decimal

from edit.compatibility_projection import build_projection, stable_digest
from edit.cut_repair_context_timeline import segments
from edit.cut_repair_picture_plan_admission import (
    PicturePlanAdmissionInput,
    PicturePlanError,
    PicturePlanGeometry,
    admit_picture_plan,
    element_version,
    frame_range,
    sample_range,
)
from edit.cut_repair_picture_plan_authority import (
    PLAN_FIELD,
    PicturePlanAuthorityInput,
    build_picture_plan_authority,
)
from edit.exact_timing import ProjectClock
from edit.picture_lock_mapping import (
    MappingProofInput,
    MappingSpan,
    prove_unchanged_mapping,
)


@dataclass(frozen=True)
class PictureReviewPlanInput:
    """All controller-owned inputs for one picture review-plan build."""

    plan: dict
    parent_plan_hash: str
    context: dict
    operation: dict
    operation_hash: str
    clock: ProjectClock
    index: int


@dataclass(frozen=True)
class PicturePlanResult:
    """Authored plan plus exact child inputs used by caption recompilation."""

    plan: dict
    projection: dict
    child_segments: list[dict]
    authority: dict


@dataclass(frozen=True)
class _ChildState:
    row: dict
    segments: list[dict]
    total_frames: int
    projection: dict


@dataclass(frozen=True)
class _ProofState:
    parent: dict
    child: _ChildState
    proof: tuple[dict, str]


def _seconds(samples: int) -> int | float:
    if samples % 4_800:
        raise PicturePlanError("PICTURE_PLAN_DECIMAL_FRAME_GRID_UNSUPPORTED")
    if samples % 48_000 == 0:
        return samples // 48_000
    return float(Decimal(samples) / Decimal(48_000))


def _child_row(value: PicturePlanGeometry) -> dict:
    parent = sample_range(
        value.parent_segment["sourceSamples"], "target source")
    start, end = (
        (value.extension.start_sample, value.silence.start_sample)
        if value.edge == "start"
        else (value.silence.end_sample_exclusive,
              value.extension.end_sample_exclusive)
    )
    if end - start != parent.length:
        raise PicturePlanError("picture repair changed target duration")
    child = copy.deepcopy(value.parent_row)
    child["start"], child["end"] = _seconds(start), _seconds(end)
    version = element_version(value.parent_row) + 1
    if "version" in child:
        child["version"] = version
    else:
        child["generation"] = version
    return child


def _child_state(
    value: PictureReviewPlanInput,
    changed: dict,
    geometry: PicturePlanGeometry,
) -> _ChildState:
    row = _child_row(geometry)
    changed["cutTrack"][value.index] = row
    source_id = row["sourceId"]
    source = {source_id: {
        "audio": {"sampleRate": 48_000}, "fps": 30, "vfr": False,
    }}
    child_rows, total = segments(changed, source, (30, 1))
    if total != value.context.get("totalFrames"):
        raise PicturePlanError("picture review plan changed program duration")
    projection = build_projection(changed, stable_digest(changed))
    return _ChildState(row, child_rows, total, projection)


def _spans(rows: list[dict]) -> tuple[MappingSpan, ...]:
    return tuple(MappingSpan(
        frame_range(row["outputFrames"], "mapping output"),
        row["sourceId"],
        sample_range(row["sourceSamples"], "mapping source"),
    ) for row in rows)


def _mapping_proof(
    value: PictureReviewPlanInput,
    geometry: PicturePlanGeometry,
    parent: dict,
    child: _ChildState,
) -> tuple[dict, str]:
    return prove_unchanged_mapping(MappingProofInput(
        parent["timelineMapHash"], child.projection["timelineMapHash"],
        _spans(value.context["segments"]), _spans(child.segments),
        (geometry.dirty,), child.total_frames,
    ))


def _authority_input(
    value: PictureReviewPlanInput,
    geometry: PicturePlanGeometry,
    state: _ProofState,
) -> PicturePlanAuthorityInput:
    mapping, mapping_hash = state.proof
    child = state.child
    return PicturePlanAuthorityInput(
        value.operation_hash, value.parent_plan_hash, value.index,
        geometry.parent_row, element_version(geometry.parent_row),
        child.row, element_version(child.row),
        geometry.extension.to_dict(), geometry.silence.to_dict(),
        geometry.dirty.to_dict(), state.parent["timelineMapHash"],
        child.projection["timelineMapHash"], mapping, mapping_hash)


def _parent_projection(value: PictureReviewPlanInput) -> dict:
    projection = build_projection(value.plan, value.parent_plan_hash)
    if projection["timelineMapHash"] \
            != value.context.get("parentTimelineMapHash"):
        raise PicturePlanError("PARENT_TIMELINE_PROJECTION_MISMATCH")
    return projection


def build_picture_review_plan(
    value: PictureReviewPlanInput,
) -> PicturePlanResult:
    """Author one duration-neutral single-row shift and prove its mapping."""
    admission = PicturePlanAdmissionInput(
        value.plan, value.context, value.operation, value.operation_hash,
        value.clock, value.index)
    geometry = admit_picture_plan(admission)
    parent = _parent_projection(value)
    changed = copy.deepcopy(value.plan)
    child = _child_state(value, changed, geometry)
    proof = _mapping_proof(value, geometry, parent, child)
    state = _ProofState(parent, child, proof)
    authority = build_picture_plan_authority(
        _authority_input(value, geometry, state))
    changed[PLAN_FIELD] = authority
    final = build_projection(changed, stable_digest(changed))
    if final["timelineMapHash"] != child.projection["timelineMapHash"]:
        raise PicturePlanError("picture plan authority changed the timeline")
    return PicturePlanResult(changed, final, child.segments, authority)
