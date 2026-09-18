"""Derive exact parent/child DialogueTrackV1 authority for one J-cut repair."""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from edit.cut_repair_context_sources import digest, require_hash
from edit.dialogue_authority import (
    compile_dialogue_map,
    dialogue_map_hash,
    dialogue_track_hash,
    validate_dialogue_authority,
)
from edit.dialogue_contracts import segment_sort_key
from edit.exact_timing import ProjectClock

_MAX_CLOCK_DEVIATION = Fraction(1, 20)


class CutRepairDialogueError(ValueError):
    """The controller inputs cannot prove an exact dialogue projection."""


@dataclass(frozen=True)
class DialogueAuthorityPair:
    """Full parent/child dialogue tracks and their deterministic maps."""

    parent_track: dict
    parent_track_hash: str
    parent_map: dict
    parent_map_hash: str
    child_track: dict
    child_track_hash: str
    child_map: dict
    child_map_hash: str


def _dialogue_id(row: dict, role: str) -> str:
    seed = {
        "segmentId": row["segmentId"],
        "elementVersion": row["elementVersion"],
        "role": role,
    }
    return f"dlg-{digest(seed)[:24]}"


def _primary(row: object, clock: ProjectClock) -> dict:
    if not isinstance(row, dict):
        raise CutRepairDialogueError(
            "CAPTION_DIALOGUE_SEGMENT_AUTHORITY_REQUIRED")
    frames = row.get("outputFrames")
    source = row.get("sourceSamples")
    if not isinstance(frames, dict) or not isinstance(source, dict):
        raise CutRepairDialogueError(
            "CAPTION_DIALOGUE_SEGMENT_AUTHORITY_REQUIRED")
    return {
        "dialogueSegmentId": _dialogue_id(row, "primary"),
        "cutSegmentId": row.get("segmentId"),
        "elementVersion": row.get("elementVersion"),
        "sourceId": row.get("sourceId"),
        "sourceSampleRate": row.get("sourceRate"),
        "sourceSampleRange": dict(source),
        "outputSampleRange": {
            "startSample": clock.sample_at_frame(frames.get("startFrame")),
            "endSampleExclusive":
                clock.sample_at_frame(frames.get("endFrameExclusive")),
        },
        "speed": row.get("speed"),
        "role": "primary",
    }


def _target_index(rows: list[dict], operation: dict) -> int:
    target = operation.get("segment")
    if not isinstance(target, dict) or target.get("edge") != "start":
        raise CutRepairDialogueError(
            "CAPTION_DIALOGUE_JCUT_AUTHORITY_REQUIRED")
    matches = [
        index for index, row in enumerate(rows)
        if row["cutSegmentId"] == target.get("segmentId")
        and row["elementVersion"] == target.get("elementVersion")
    ]
    if len(matches) != 1 or matches[0] == 0:
        raise CutRepairDialogueError(
            "CAPTION_DIALOGUE_JCUT_AUTHORITY_REQUIRED")
    return matches[0]


def _j_handle(rows: list[dict], operation: dict) -> dict:
    index = _target_index(rows, operation)
    own, covered = rows[index], rows[index - 1]
    source = operation.get("sourceExtension")
    output_samples = operation.get("extensionOutputSamples")
    if not isinstance(source, dict) or type(output_samples) is not int \
            or output_samples <= 0:
        raise CutRepairDialogueError(
            "CAPTION_DIALOGUE_JCUT_AUTHORITY_REQUIRED")
    seam = own["outputSampleRange"]["startSample"]
    handle = {
        **{key: own[key] for key in (
            "cutSegmentId", "elementVersion", "sourceId",
            "sourceSampleRate", "speed")},
        "dialogueSegmentId": _dialogue_id({
            "segmentId": own["cutSegmentId"],
            "elementVersion": own["elementVersion"],
        }, "j-cut-handle"),
        "sourceSampleRange": dict(source),
        "outputSampleRange": {
            "startSample": seam - output_samples,
            "endSampleExclusive": seam,
        },
        "role": "j-cut-handle",
        "seamSample": seam,
        "coveredByCutSegmentId": covered["cutSegmentId"],
    }
    expected = (
        operation.get("sourceSampleRate"), operation.get("speed"),
        source.get("endSampleExclusive"),
    )
    actual = (
        own["sourceSampleRate"], own["speed"],
        own["sourceSampleRange"]["startSample"],
    )
    if expected != actual \
            or handle["outputSampleRange"]["startSample"] \
            < covered["outputSampleRange"]["startSample"]:
        raise CutRepairDialogueError(
            "CAPTION_DIALOGUE_JCUT_AUTHORITY_REQUIRED")
    return handle


def _speed(value: dict) -> Fraction:
    try:
        return Fraction(int(value["numerator"]), int(value["denominator"]))
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise CutRepairDialogueError(
            "CAPTION_DIALOGUE_SPEED_AUTHORITY_REQUIRED") from exc


def _deviation(row: dict, clock: ProjectClock) -> Fraction:
    source = row["sourceSampleRange"]
    normalized = (
        source["endSampleExclusive"] * clock.sample_rate
        // row["sourceSampleRate"]
        - source["startSample"] * clock.sample_rate
        // row["sourceSampleRate"]
    )
    output = row["outputSampleRange"]
    output_length = output["endSampleExclusive"] - output["startSample"]
    if normalized <= 0 or output_length <= 0:
        raise CutRepairDialogueError(
            "CAPTION_DIALOGUE_SAMPLE_RANGE_REQUIRED")
    return abs(Fraction(normalized, output_length) - _speed(row["speed"]))


def _tolerance(rows: list[dict], clock: ProjectClock) -> dict[str, str]:
    observed = max((_deviation(row, clock) for row in rows), default=Fraction())
    if observed > _MAX_CLOCK_DEVIATION:
        raise CutRepairDialogueError(
            "CAPTION_DIALOGUE_CLOCK_TOLERANCE_EXCEEDED")
    value = max(observed, Fraction(1, clock.sample_rate))
    return {"numerator": str(value.numerator), "denominator": str(value.denominator)}


def _track(
    rows: list[dict],
    context: dict,
    picture_hash: str,
    clock: ProjectClock,
) -> dict:
    ordered = sorted(rows, key=segment_sort_key)
    return {
        "schemaVersion": 1,
        "kind": "dialogue-track",
        "sourceSnapshotSetHash": require_hash(
            context.get("sourceSnapshotSetHash"),
            "caption dialogue source snapshot set"),
        "pictureTimelineMapHash": require_hash(
            picture_hash, "caption dialogue picture timeline map"),
        "projectFps": clock.fps.to_dict(),
        "projectSampleRate": clock.sample_rate,
        "totalOutputFrames": context.get("totalFrames"),
        "totalOutputSamples":
            clock.sample_at_frame(context.get("totalFrames")),
        "maxAbsoluteSpeedDeviation": _tolerance(ordered, clock),
        "segments": ordered,
    }


def _authority(track: dict) -> tuple[dict, str, dict, str]:
    track_hash = dialogue_track_hash(track)
    dialogue_map = compile_dialogue_map(track)
    return track, track_hash, dialogue_map, dialogue_map_hash(dialogue_map)


def _parent_track(
    context: dict,
    primaries: list[dict],
    clock: ProjectClock,
) -> dict:
    expected = _track(
        primaries, context, context.get("parentTimelineMapHash"), clock)
    raw_track = context.get("_existingDialogueTrack")
    raw_map = context.get("_existingDialogueMap")
    if raw_track is None and raw_map is None:
        return expected
    if raw_track is None or raw_map is None:
        raise CutRepairDialogueError(
            "CAPTION_DIALOGUE_EXISTING_JCUT_AUTHORITY_REQUIRED")
    track, _ = validate_dialogue_authority(raw_track, raw_map)
    header = (
        "sourceSnapshotSetHash", "pictureTimelineMapHash",
        "projectFps", "projectSampleRate", "totalOutputFrames",
        "totalOutputSamples",
    )
    if any(track[key] != expected[key] for key in header):
        raise CutRepairDialogueError(
            "CAPTION_DIALOGUE_EXISTING_JCUT_AUTHORITY_STALE")
    existing_primaries = [
        row for row in track["segments"] if row["role"] == "primary"
    ]
    if existing_primaries != expected["segments"]:
        raise CutRepairDialogueError(
            "CAPTION_DIALOGUE_EXISTING_JCUT_AUTHORITY_STALE")
    return track


def build_cut_repair_dialogue_authority(
    context: dict,
    operation: dict,
    child_timeline_map_hash: str,
    clock: ProjectClock,
) -> DialogueAuthorityPair:
    """Build and validate exact dialogue authority before and after a J-cut."""
    values = context.get("segments")
    if not isinstance(values, list) or not values:
        raise CutRepairDialogueError(
            "CAPTION_DIALOGUE_SEGMENT_AUTHORITY_REQUIRED")
    primaries = [_primary(row, clock) for row in values]
    parent_track = _parent_track(context, primaries, clock)
    child_rows = [
        *parent_track["segments"],
        _j_handle(parent_track["segments"], operation),
    ]
    parent = _authority(parent_track)
    child = _authority(_track(
        child_rows, context, child_timeline_map_hash, clock))
    return DialogueAuthorityPair(*parent, *child)


def build_primary_picture_dialogue_authority(
    parent_context: dict,
    child_context: dict,
    child_timeline_map_hash: str,
    clock: ProjectClock,
) -> DialogueAuthorityPair:
    """Build parent/child primary tracks for a picture cut with no L/J handles."""
    parent_values = parent_context.get("segments")
    child_values = child_context.get("segments")
    if not isinstance(parent_values, list) or not parent_values \
            or not isinstance(child_values, list) or not child_values:
        raise CutRepairDialogueError(
            "CAPTION_DIALOGUE_SEGMENT_AUTHORITY_REQUIRED")
    parent_track = _track(
        [_primary(row, clock) for row in parent_values],
        parent_context, parent_context.get("parentTimelineMapHash"), clock)
    child_track = _track(
        [_primary(row, clock) for row in child_values],
        child_context, child_timeline_map_hash, clock)
    return DialogueAuthorityPair(
        *_authority(parent_track), *_authority(child_track))
