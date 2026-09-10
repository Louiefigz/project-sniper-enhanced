"""Fail-closed admission for the first renderable picture-plan subset."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from edit.cut_repair_context_sources import to_sample
from edit.exact_timing import (
    FrameRange,
    PositiveRational,
    ProjectClock,
    SampleRange,
)
from edit.repair_fragment_contracts import validate_repair
from edit.repair_ranges import source_video_frame_range

_TARGET_KEYS = {
    "id", "sourceId", "start", "end", "speed", "generation", "version",
}


class PicturePlanError(ValueError):
    """A picture-changing operation cannot be expressed by the safe subset."""


@dataclass(frozen=True)
class PicturePlanGeometry:
    """Validated exact geometry for one single-row picture shift."""

    index: int
    edge: str
    parent_row: dict
    parent_segment: dict
    extension: SampleRange
    silence: SampleRange
    dirty: FrameRange


@dataclass(frozen=True)
class PicturePlanAdmissionInput:
    """All controller-owned inputs for picture-plan admission."""

    plan: dict
    context: dict
    operation: dict
    operation_hash: str
    clock: ProjectClock
    index: int


def sample_range(value: object, label: str) -> SampleRange:
    """Parse one closed exact sample range."""
    if not isinstance(value, dict) or set(value) != {
            "startSample", "endSampleExclusive"}:
        raise PicturePlanError(f"{label} is not a closed sample range")
    try:
        return SampleRange(value["startSample"], value["endSampleExclusive"])
    except (TypeError, ValueError) as exc:
        raise PicturePlanError(f"{label} is invalid") from exc


def frame_range(value: object, label: str) -> FrameRange:
    """Parse one closed exact frame range."""
    if not isinstance(value, dict) or set(value) != {
            "startFrame", "endFrameExclusive"}:
        raise PicturePlanError(f"{label} is not a closed frame range")
    try:
        return FrameRange(value["startFrame"], value["endFrameExclusive"])
    except (TypeError, ValueError) as exc:
        raise PicturePlanError(f"{label} is invalid") from exc


def element_version(row: dict) -> int:
    """Return the sole accepted cut-row version."""
    if "generation" in row and "version" in row:
        raise PicturePlanError("picture repair target has two version fields")
    value = row.get("generation", row.get("version", 1))
    if type(value) is not int or value < 1:
        raise PicturePlanError("picture repair target version is invalid")
    return value


def _one_frame_range(value: object, label: str) -> FrameRange:
    if not isinstance(value, list) or len(value) != 1:
        raise PicturePlanError(f"{label} must contain exactly one range")
    return frame_range(value[0], f"{label}[0]")


def _speed_one(value: object) -> bool:
    try:
        return Decimal(str(value)) == 1
    except Exception:
        return False


def _track_rows(value: PicturePlanAdmissionInput) -> tuple[list, list, dict, dict]:
    track = value.plan.get("cutTrack")
    context_rows = value.context.get("segments")
    if not isinstance(track, list) or not isinstance(context_rows, list) \
            or len(track) != len(context_rows) \
            or not 0 <= value.index < len(track):
        raise PicturePlanError("picture repair segment authority is malformed")
    row, segment = track[value.index], context_rows[value.index]
    if not isinstance(row, dict) or not isinstance(segment, dict) \
            or set(row) - _TARGET_KEYS:
        raise PicturePlanError(
            "PICTURE_PLAN_TARGET_ROW_VOCABULARY_UNSUPPORTED")
    return track, context_rows, row, segment


def _track_admission(
    value: PicturePlanAdmissionInput,
    track: list,
) -> None:
    source_ids = {
        item.get("sourceId") for item in track if isinstance(item, dict)
    }
    if len(source_ids) != 1 or None in source_ids:
        raise PicturePlanError("PICTURE_PLAN_MULTI_SOURCE_UNSUPPORTED")
    if any(not isinstance(item, dict)
           or not _speed_one(item.get("speed", 1)) for item in track):
        raise PicturePlanError("PICTURE_PLAN_RETIME_UNSUPPORTED")
    if value.context.get("existingAudioLeadSampleRanges") not in (None, []) \
            or any(item.get("audioLeadMs") is not None for item in track):
        raise PicturePlanError("PICTURE_PLAN_EXISTING_AUDIO_LEAD_UNSUPPORTED")


def _operation_geometry(
    value: PicturePlanAdmissionInput,
    row: dict,
    segment: dict,
) -> PicturePlanGeometry:
    extension = sample_range(
        value.operation.get("sourceExtension"), "sourceExtension")
    reclaimed = value.operation.get("reclaimedSilence")
    if not isinstance(reclaimed, dict):
        raise PicturePlanError("picture repair lacks reclaimed silence")
    silence = sample_range(
        reclaimed.get("sourceSampleRange"), "reclaimed source range")
    dirty = _one_frame_range(
        value.operation.get("pictureDirtyWindows"), "pictureDirtyWindows")
    if _one_frame_range(
            value.operation.get("audioDirtyWindows"),
            "audioDirtyWindows") != dirty:
        raise PicturePlanError("picture repair dirty windows differ")
    target = value.operation.get("segment")
    if not isinstance(target, dict) or target.get("edge") not in {
            "start", "end"}:
        raise PicturePlanError("picture repair target edge is invalid")
    return PicturePlanGeometry(
        value.index, target["edge"], row, segment,
        extension, silence, dirty)


def _target_binding(
    value: PicturePlanAdmissionInput,
    geometry: PicturePlanGeometry,
) -> None:
    row, segment = geometry.parent_row, geometry.parent_segment
    parent = sample_range(segment.get("sourceSamples"), "target source")
    expected_row = (
        to_sample(row.get("start"), 48_000, "target start"),
        to_sample(row.get("end"), 48_000, "target end"),
    )
    target = value.operation["segment"]
    if expected_row != (
            parent.start_sample, parent.end_sample_exclusive) \
            or row.get("id") != target.get("segmentId") \
            or element_version(row) != target.get("elementVersion") \
            or row.get("sourceId") != segment.get("sourceId"):
        raise PicturePlanError("picture repair target row is stale")


def _clock_admission(value: PicturePlanAdmissionInput) -> None:
    repair = validate_repair(
        value.operation, value.operation_hash, value.clock)
    fps = repair.source_fps
    exact_rate = {"numerator": "30", "denominator": "1"}
    if repair.method != "extend-and-reclaim-silence" \
            or value.clock.fps.to_dict() != exact_rate \
            or value.clock.sample_rate != 48_000 \
            or repair.source_rate != 48_000 \
            or fps is None or fps.to_dict() != exact_rate \
            or value.operation.get("speed") != {
                "numerator": "1", "denominator": "1"} \
            or repair.quantization_residual_samples != 0:
        raise PicturePlanError("PICTURE_PLAN_CLOCK_SUBSET_UNSUPPORTED")


def _expected_unchanged(total: int, dirty: FrameRange) -> list[dict]:
    rows = []
    if dirty.start_frame:
        rows.append(FrameRange(0, dirty.start_frame).to_dict())
    if dirty.end_frame_exclusive < total:
        rows.append(FrameRange(
            dirty.end_frame_exclusive, total).to_dict())
    return rows


def _silence_frames(
    geometry: PicturePlanGeometry,
    parent: SampleRange,
    output: FrameRange,
) -> FrameRange:
    frame_samples = 1_600
    start = geometry.silence.start_sample - parent.start_sample
    end = geometry.silence.end_sample_exclusive - parent.start_sample
    if start < 0 or end > parent.length \
            or start % frame_samples or end % frame_samples:
        raise PicturePlanError("PICTURE_PLAN_RECLAIMED_GEOMETRY_UNSUPPORTED")
    return FrameRange(
        output.start_frame + start // frame_samples,
        output.start_frame + end // frame_samples)


def _terminal_geometry(
    geometry: PicturePlanGeometry,
    parent: SampleRange,
) -> bool:
    return (
        geometry.edge == "start"
        and geometry.extension.end_sample_exclusive == parent.start_sample
        and geometry.silence.end_sample_exclusive
        == parent.end_sample_exclusive
    ) or (
        geometry.edge == "end"
        and geometry.extension.start_sample == parent.end_sample_exclusive
        and geometry.silence.start_sample == parent.start_sample
    )


def _geometry_admission(
    value: PicturePlanAdmissionInput,
    geometry: PicturePlanGeometry,
) -> None:
    parent = sample_range(
        geometry.parent_segment["sourceSamples"], "target source")
    output = frame_range(
        geometry.parent_segment["outputFrames"], "target output")
    silence_frames = _silence_frames(geometry, parent, output)
    reclaimed = value.operation["reclaimedSilence"]
    extension_video = frame_range(
        value.operation.get("sourceVideoFrameRange"), "sourceVideoFrameRange")
    expected_video = source_video_frame_range(
        geometry.extension, 48_000, PositiveRational(30, 1))
    lengths_match = (
        geometry.extension.length == geometry.silence.length
        == value.operation.get("extensionOutputSamples")
    )
    total = value.operation.get("totalOutputFramesBefore")
    unchanged = _expected_unchanged(total, geometry.dirty) \
        if type(total) is int else None
    if not lengths_match \
            or silence_frames.to_dict() != reclaimed.get("outputFrameRange") \
            or not _terminal_geometry(geometry, parent) \
            or geometry.dirty != output \
            or value.operation.get("unchangedPictureMappingRanges") != unchanged:
        raise PicturePlanError(
            "PICTURE_PLAN_INTERIOR_RECLAIM_CREATES_UNPROVED_SEAMS")
    if extension_video != expected_video \
            or extension_video.length != value.operation.get("extensionFrames"):
        raise PicturePlanError("PICTURE_PLAN_SOURCE_FRAME_RANGE_UNSUPPORTED")


def admit_picture_plan(
    value: PicturePlanAdmissionInput,
) -> PicturePlanGeometry:
    """Admit only a one-row, no-new-seam, exact-clock picture repair."""
    _clock_admission(value)
    track, _context_rows, row, segment = _track_rows(value)
    _track_admission(value, track)
    geometry = _operation_geometry(value, row, segment)
    _target_binding(value, geometry)
    _geometry_admission(value, geometry)
    return geometry
