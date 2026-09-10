"""Closed inputs for the real P2 dirty-window fragment renderer."""
from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

from edit.exact_timing import (
    FrameRange,
    PositiveRational,
    ProjectClock,
    SampleRange,
    source_span_project_samples,
)
from fingerprints import file_sha256


class RepairRenderError(RuntimeError):
    """A repair fragment cannot be rendered or proved safely."""


def _hash(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise RepairRenderError(f"{label} is not a lowercase SHA-256")
    return value


def _regular(path: str, label: str) -> str:
    if not os.path.isabs(path) or os.path.islink(path):
        raise RepairRenderError(f"{label} must be an absolute regular file")
    try:
        stat = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise RepairRenderError(f"{label} is unreadable: {exc}") from exc
    if not os.path.isfile(path) or stat.st_nlink != 1:
        raise RepairRenderError(
            f"{label} must be a single-link regular snapshot")
    return os.path.realpath(path)


def validate_snapshot(path: str, label: str) -> str:
    """Resolve one no-follow, single-link immutable media snapshot."""
    return _regular(path, label)


@dataclass(frozen=True)
class RepairMediaTools:
    """Pinned media executables used by one repair render."""

    ffmpeg_path: str
    ffmpeg_sha256: str
    ffprobe_path: str
    ffprobe_sha256: str

    def validate(self) -> "RepairMediaTools":
        """Reobserve exact executable bytes immediately before use."""
        ffmpeg = _regular(self.ffmpeg_path, "ffmpeg")
        ffprobe = _regular(self.ffprobe_path, "ffprobe")
        expected_ffmpeg = _hash(self.ffmpeg_sha256, "ffmpeg hash")
        expected_ffprobe = _hash(self.ffprobe_sha256, "ffprobe hash")
        if file_sha256(ffmpeg) != expected_ffmpeg \
                or file_sha256(ffprobe) != expected_ffprobe:
            raise RepairRenderError("repair media executable bytes drifted")
        return RepairMediaTools(
            ffmpeg, expected_ffmpeg, ffprobe, expected_ffprobe)


@dataclass(frozen=True)
class RepairFragmentRequest:
    """One immutable local repair render request."""

    operation: dict[str, object]
    operation_hash: str
    parent_path: str
    source_path: str
    output_path: str
    clock: ProjectClock
    tools: RepairMediaTools


@dataclass(frozen=True)
class ValidatedRepair:
    """Renderer-ready operation projection."""

    operation: dict[str, object]
    operation_hash: str
    method: str
    edge: str
    dirty_frames: FrameRange
    dirty_samples: SampleRange
    source_extension: SampleRange
    source_rate: int
    source_video_frames: FrameRange | None
    source_fps: PositiveRational | None
    extension_frames: int
    extension_output_samples: int
    total_frames: int
    reclaimed_frames: FrameRange | None
    quantization_residual_samples: int


def _frame_range(value: object, label: str) -> FrameRange:
    if not isinstance(value, dict):
        raise RepairRenderError(f"{label} must be a frame range")
    try:
        return FrameRange(
            value["startFrame"], value["endFrameExclusive"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RepairRenderError(f"{label} is invalid") from exc


def _sample_range(value: object, label: str) -> SampleRange:
    if not isinstance(value, dict):
        raise RepairRenderError(f"{label} must be a sample range")
    try:
        return SampleRange(
            value["startSample"], value["endSampleExclusive"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RepairRenderError(f"{label} is invalid") from exc


def _one_range(value: object, label: str,
               parser: Callable[
                   [object, str], FrameRange | SampleRange],
               ) -> FrameRange | SampleRange:
    if not isinstance(value, list) or len(value) != 1:
        raise RepairRenderError(f"{label} must contain exactly one range")
    return parser(value[0], f"{label}[0]")


def _integer(value: object, label: str, minimum: int = 1) -> int:
    if type(value) is not int or value < minimum:
        raise RepairRenderError(f"{label} must be an integer >= {minimum}")
    return value


def _common(operation: dict[str, object],
            operation_hash: str) -> dict[str, object]:
    segment = operation.get("segment")
    if not isinstance(segment, dict) or segment.get("edge") not in {
            "start", "end"}:
        raise RepairRenderError("repair segment edge is invalid")
    before = _integer(
        operation.get("totalOutputFramesBefore"), "total frames before")
    after = _integer(
        operation.get("totalOutputFramesAfter"), "total frames after")
    if before != after or operation.get("preserveUnrelated") is not True:
        raise RepairRenderError("fragment renderer accepts only non-ripple repair")
    return {
        "operation": operation,
        "operation_hash": operation_hash,
        "edge": segment["edge"],
        "source_extension": _sample_range(
            operation.get("sourceExtension"), "sourceExtension"),
        "source_rate": _integer(
            operation.get("sourceSampleRate"), "sourceSampleRate"),
        "extension_frames": _integer(
            operation.get("extensionFrames"), "extensionFrames"),
        "extension_output_samples": _integer(
            operation.get("extensionOutputSamples"),
            "extensionOutputSamples"),
        "total_frames": before,
    }


def validate_repair(operation: object, operation_hash: str,
                    clock: ProjectClock) -> ValidatedRepair:
    """Validate one selected enumerator candidate for media execution."""
    from edit.picture_lock_common import content_hash
    if not isinstance(operation, dict) \
            or operation.get("schemaVersion") != 1 \
            or operation.get("operation") != "cut.restoreSpeech":
        raise RepairRenderError("repair operation is unsupported")
    if content_hash(operation) != _hash(operation_hash, "operation hash"):
        raise RepairRenderError("repair operation hash does not match")
    method = operation.get("method")
    if method not in {"audio-lj-overlap", "extend-and-reclaim-silence"}:
        raise RepairRenderError("repair method is unsupported")
    dirty = _one_range(
        operation.get("audioDirtyWindows"),
        "audioDirtyWindows", _frame_range)
    samples = _one_range(
        operation.get("audioDirtySampleRanges"),
        "audioDirtySampleRanges", _sample_range)
    if not isinstance(dirty, FrameRange) \
            or not isinstance(samples, SampleRange):
        raise RepairRenderError("repair dirty ranges have the wrong units")
    common = _common(operation, operation_hash)
    reclaimed = _reclaimed(operation, method)
    source_video, source_fps = _source_video(operation, method)
    _method_evidence(operation, method, samples)
    expected = clock.samples_for_frames(dirty)
    if samples.start_sample < expected.start_sample \
            or samples.end_sample_exclusive > expected.end_sample_exclusive:
        raise RepairRenderError("audio repair exceeds its dirty frame envelope")
    repair = ValidatedRepair(
        method=method, dirty_frames=dirty, dirty_samples=samples,
        reclaimed_frames=reclaimed,
        source_video_frames=source_video,
        source_fps=source_fps,
        quantization_residual_samples=_integer(
            operation.get("quantizationResidualSamples", 0),
            "quantizationResidualSamples", 0),
        **common)
    _validate_geometry(repair, clock)
    return repair


def _reclaimed(operation: dict, method: str) -> FrameRange | None:
    if method == "audio-lj-overlap":
        if operation.get("pictureDirtyWindows") != []:
            raise RepairRenderError("audio-only repair dirties picture")
        return None
    picture = _one_range(
        operation.get("pictureDirtyWindows"),
        "pictureDirtyWindows", _frame_range)
    reclaimed = operation.get("reclaimedSilence")
    if not isinstance(reclaimed, dict):
        raise RepairRenderError("picture repair lacks reclaimed silence")
    silence = _frame_range(
        reclaimed.get("outputFrameRange"), "reclaimed outputFrameRange")
    if not isinstance(picture, FrameRange) \
            or picture != _one_range(
                operation.get("audioDirtyWindows"),
                "audioDirtyWindows", _frame_range):
        raise RepairRenderError("picture/audio dirty windows differ")
    return silence


def _source_video(
    operation: dict,
    method: str,
) -> tuple[FrameRange | None, PositiveRational | None]:
    if method == "audio-lj-overlap":
        if operation.get("sourceVideoFrameRange") is not None \
                or operation.get("sourceFrameRate") is not None:
            raise RepairRenderError("audio-only repair claims picture handles")
        return None, None
    frames = _frame_range(
        operation.get("sourceVideoFrameRange"), "sourceVideoFrameRange")
    try:
        fps = PositiveRational.from_value(operation.get("sourceFrameRate"))
    except ValueError as exc:
        raise RepairRenderError("sourceFrameRate is invalid") from exc
    return frames, fps


def _method_evidence(operation: dict, method: str,
                     samples: SampleRange) -> None:
    if method == "audio-lj-overlap":
        replaced = _one_range(
            operation.get("replacedAudioSampleRanges"),
            "replacedAudioSampleRanges", _sample_range)
        _hash(operation.get("replaceableAudioEvidenceHash"),
              "replaceable-audio evidence hash")
        if replaced != samples:
            raise RepairRenderError("audio replacement evidence range drifted")
        return
    if operation.get("residualPolicy") != "reclaimed-proved-silence":
        raise RepairRenderError("picture repair has no proved residual policy")


def _validate_geometry(repair: ValidatedRepair,
                       clock: ProjectClock) -> None:
    try:
        speed = PositiveRational.from_value(repair.operation.get("speed"))
    except ValueError as exc:
        raise RepairRenderError("speed is invalid") from exc
    expected_extension = source_span_project_samples(
        repair.source_extension.length, repair.source_rate, speed, clock)
    if expected_extension != repair.extension_output_samples:
        raise RepairRenderError("repair extension sample count drifted")
    if repair.method == "audio-lj-overlap":
        if repair.dirty_samples.length != repair.extension_output_samples:
            raise RepairRenderError("audio replacement length is not exact")
        return
    silence = repair.reclaimed_frames
    if silence is None or repair.source_video_frames is None \
            or repair.source_fps is None \
            or silence.length != repair.extension_frames \
            or silence.start_frame < repair.dirty_frames.start_frame \
            or silence.end_frame_exclusive \
            > repair.dirty_frames.end_frame_exclusive:
        raise RepairRenderError("reclaimed silence geometry is invalid")
    removed = clock.samples_for_frames(silence).length
    if removed != repair.extension_output_samples \
            + repair.quantization_residual_samples:
        raise RepairRenderError("reclaimed silence sample allocation drifted")
    if repair.dirty_samples != clock.samples_for_frames(repair.dirty_frames):
        raise RepairRenderError("picture repair audio window is not exact")
