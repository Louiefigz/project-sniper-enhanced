"""Author the exact private review plan for one selected cut repair."""
from __future__ import annotations

import copy
import os
from dataclasses import dataclass

from captions.caption_plan_pipeline import has_explicit_caption_track
from captions.cut_repair_dialogue_authority import (
    PLAN_FIELD as CAPTION_PLAN_FIELD,
    CutRepairCaptionAuthorityInput,
    build_caption_authority_from_dialogue,
    build_cut_repair_caption_authority,
)
from edit.compatibility_projection import build_projection, stable_digest
from edit.cut_repair_context_sources import stable_json
from edit.cut_repair_dialogue_track import (
    build_primary_picture_dialogue_authority,
)
from edit.cut_repair_existing_leads import assert_new_repair_disjoint
from edit.cut_repair_picture_plan import (
    PictureReviewPlanInput,
    build_picture_review_plan,
)
from edit.exact_timing import ProjectClock
from edit.picture_lock_common import content_hash


class ReviewPlanError(ValueError):
    """A selected operation cannot become an exact private review plan."""


@dataclass(frozen=True)
class ReviewPlanResult:
    """Review plan/projection plus optional external picture mutation proof."""

    plan: dict
    projection: dict
    picture_plan_receipt: dict | None


@dataclass(frozen=True)
class _ReviewBuild:
    plan: dict
    plan_hash: str
    context: dict
    operation: dict
    clock: ProjectClock
    index: int


def segment_index(plan: dict, operation: dict, context: dict) -> int:
    """Resolve the selected immutable segment identity in the live plan."""
    track = plan.get("cutTrack")
    segments = context.get("segments")
    target = operation.get("segment")
    if not isinstance(track, list) or not isinstance(segments, list) \
            or len(track) != len(segments) or not isinstance(target, dict):
        raise ReviewPlanError("cut repair segment authority is malformed")
    matches = [
        index for index, row in enumerate(segments)
        if isinstance(row, dict)
        and row.get("segmentId") == target.get("segmentId")
        and row.get("elementVersion") == target.get("elementVersion")
    ]
    if len(matches) != 1 or not isinstance(track[matches[0]], dict):
        raise ReviewPlanError(
            "cut repair target segment is not unique in the live plan")
    return matches[0]


def _assert_source_span(operation: dict, sample_rate: int) -> None:
    source = operation.get("sourceExtension")
    speed = operation.get("speed")
    if not isinstance(source, dict) or not isinstance(speed, dict):
        raise ReviewPlanError("cut repair source-span clock is malformed")
    source_length = source.get("endSampleExclusive", 0) \
        - source.get("startSample", 0)
    source_rate = operation.get("sourceSampleRate")
    output = operation.get("extensionOutputSamples")
    numerator = int(speed.get("numerator", 0))
    denominator = int(speed.get("denominator", 0))
    values = (source_length, source_rate, output, numerator, denominator)
    if any(type(value) is not int or value <= 0 for value in values):
        raise ReviewPlanError("cut repair source-span clock is malformed")
    if source_length * sample_rate * denominator \
            != output * source_rate * numerator:
        raise ReviewPlanError(
            "PLAN_VOCABULARY_SAMPLE_EXACT_JCUT_UNAVAILABLE")


def lead_ms(operation: dict, sample_rate: int) -> int:
    """Return the exact released millisecond J-cut vocabulary value."""
    output = operation.get("extensionOutputSamples")
    if type(output) is not int or sample_rate % 1000 \
            or output % (sample_rate // 1000):
        raise ReviewPlanError(
            "PLAN_VOCABULARY_SAMPLE_EXACT_JCUT_UNAVAILABLE")
    _assert_source_span(operation, sample_rate)
    return output * 1000 // sample_rate


def _picture_map(projection: dict) -> list[dict]:
    timeline = projection.get("timelineMap")
    segments = timeline.get("segments") if isinstance(timeline, dict) else None
    if not isinstance(segments, list):
        raise ReviewPlanError("cut repair timeline projection is malformed")
    return [{
        key: row.get(key) for key in (
            "index", "source_id", "src_start", "src_end", "speed",
            "out_start", "out_end")
    } for row in segments if isinstance(row, dict)]


def _caption_input(
    value: _ReviewBuild,
    changed: dict,
    child_hash: str,
) -> CutRepairCaptionAuthorityInput:
    return CutRepairCaptionAuthorityInput(
        value.plan, changed, value.context, value.operation,
        child_hash, value.clock)


def _final_caption_projection(
    changed: dict,
    child: dict,
) -> dict:
    final = build_projection(changed, stable_digest(changed))
    if final["timelineMapHash"] != child["timelineMapHash"]:
        raise ReviewPlanError(
            "caption authority changed the child picture projection")
    return final


def _audio_review_plan(
    value: _ReviewBuild,
) -> ReviewPlanResult:
    if value.index == 0:
        raise ReviewPlanError("PLAN_VOCABULARY_JCUT_NEEDS_INCOMING_SEAM")
    row = value.plan["cutTrack"][value.index]
    if row.get("audioLeadMs") is not None:
        raise ReviewPlanError("cut repair target already has an audio lead")
    assert_new_repair_disjoint(
        value.plan, value.context, value.operation, value.clock)
    parent = build_projection(value.plan, value.plan_hash)
    if parent["timelineMapHash"] != value.context.get(
            "parentTimelineMapHash"):
        raise ReviewPlanError("PARENT_TIMELINE_PROJECTION_MISMATCH")
    changed = copy.deepcopy(value.plan)
    changed["cutTrack"][value.index]["audioLeadMs"] = lead_ms(
        value.operation, value.clock.sample_rate)
    child = build_projection(changed, stable_digest(changed))
    if _picture_map(parent) != _picture_map(child) \
            or child["timelineMapHash"] == parent["timelineMapHash"]:
        raise ReviewPlanError("cut repair changed picture timing")
    observed = child["timelineMap"]["segments"][
        value.index]["audio_lead_s"]
    if observed * value.clock.sample_rate \
            != value.operation["extensionOutputSamples"]:
        raise ReviewPlanError("cut repair projection changed the audio lead")
    if not has_explicit_caption_track(value.plan):
        return ReviewPlanResult(changed, child, None)
    changed[CAPTION_PLAN_FIELD] = build_cut_repair_caption_authority(
        _caption_input(value, changed, child["timelineMapHash"]))
    return ReviewPlanResult(
        changed, _final_caption_projection(changed, child), None)


def _picture_review_plan(
    value: _ReviewBuild,
) -> ReviewPlanResult:
    result = build_picture_review_plan(PictureReviewPlanInput(
        value.plan, value.plan_hash, value.context, value.operation,
        content_hash(value.operation), value.clock, value.index))
    changed, child = result.plan, result.projection
    if not has_explicit_caption_track(value.plan):
        return ReviewPlanResult(changed, child, result.authority)
    child_context = {**value.context, "segments": result.child_segments}
    dialogue = build_primary_picture_dialogue_authority(
        value.context, child_context, child["timelineMapHash"], value.clock)
    changed[CAPTION_PLAN_FIELD] = build_caption_authority_from_dialogue(
        _caption_input(value, changed, child["timelineMapHash"]), dialogue)
    return ReviewPlanResult(
        changed, _final_caption_projection(changed, child),
        result.authority)


def review_plan_result(
    producer_dir: str,
    context: dict,
    operation: dict,
    clock: ProjectClock,
) -> ReviewPlanResult:
    """Dispatch to the exact released audio or bounded picture vocabulary."""
    plan, plan_hash = stable_json(
        os.path.join(producer_dir, "edit_plan.json"), "edit plan")
    if "captionChapters" in plan and not has_explicit_caption_track(plan):
        raise ReviewPlanError("CAPTION_DIALOGUE_TRACK_REQUIRED")
    index = segment_index(plan, operation, context)
    value = _ReviewBuild(
        plan, plan_hash, context, operation, clock, index)
    if operation.get("method") == "audio-lj-overlap":
        return _audio_review_plan(value)
    if operation.get("method") == "extend-and-reclaim-silence":
        return _picture_review_plan(value)
    raise ReviewPlanError("PLAN_VOCABULARY_REPAIR_METHOD_UNAVAILABLE")


def review_plan(
    producer_dir: str,
    context: dict,
    operation: dict,
    clock: ProjectClock,
) -> tuple[dict, dict]:
    """Compatibility tuple view over the richer preparation result."""
    result = review_plan_result(producer_dir, context, operation, clock)
    return result.plan, result.projection
