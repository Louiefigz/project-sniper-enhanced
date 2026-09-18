"""Execute and prove one real, frame/sample-bounded P2 repair fragment."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from fractions import Fraction

from edit.exact_timing import PositiveRational
from edit.picture_lock_common import canonical_json, content_hash
from edit.repair_channel_authority import (
    RepairChannelRequest,
    observe_repair_channel_pair,
)
from edit.repair_fragment_contracts import (
    RepairFragmentRequest,
    RepairRenderError,
    validate_repair,
    validate_snapshot,
)
from edit.repair_fragment_media import (
    RepairMediaJob,
    probe_fragment,
    render_staged_media,
)
from fingerprints import file_sha256


def _probe(path: str, tools: object) -> dict:
    from edit.repair_fragment_media import _run
    ffprobe = getattr(tools, "ffprobe_path")
    raw = _run([
        ffprobe, "-v", "error", "-count_packets",
        "-show_streams", "-of", "json", path])
    streams = json.loads(str(raw)).get("streams") or []
    video = next((row for row in streams
                  if row.get("codec_type") == "video"), None)
    audio = next((row for row in streams
                  if row.get("codec_type") == "audio"), None)
    if not isinstance(video, dict) or not isinstance(audio, dict):
        raise RepairRenderError("repair input requires video and audio streams")
    return {"video": video, "audio": audio}


def _fraction(value: object, label: str) -> Fraction:
    if not isinstance(value, str):
        raise RepairRenderError(f"{label} is not a rational rate")
    try:
        result = Fraction(value)
    except (ValueError, ZeroDivisionError) as exc:
        raise RepairRenderError(f"{label} is not a rational rate") from exc
    if result <= 0:
        raise RepairRenderError(f"{label} is not positive")
    return result


def _input_evidence(request: RepairFragmentRequest,
                    parent: str, source: str,
                    tools: object) -> dict[str, object]:
    parent_probe = _probe(parent, tools)
    source_probe = _probe(source, tools)
    project_fps = request.clock.fps.fraction
    parent_rate = _fraction(
        parent_probe["video"].get("avg_frame_rate"), "parent frame rate")
    source_avg = _fraction(
        source_probe["video"].get("avg_frame_rate"), "source average rate")
    source_nominal = _fraction(
        source_probe["video"].get("r_frame_rate"), "source nominal rate")
    parent_audio_rate = int(parent_probe["audio"].get("sample_rate", 0))
    source_audio_rate = int(source_probe["audio"].get("sample_rate", 0))
    if parent_rate != project_fps \
            or parent_audio_rate != request.clock.sample_rate:
        raise RepairRenderError("parent is not normalized to the project clock")
    return {
        "parent": {
            "sha256": file_sha256(parent),
            "averageFrameRate": str(parent_rate),
            "videoFrames": int(parent_probe["video"]["nb_read_packets"]),
            "audioSampleRate": parent_audio_rate,
        },
        "source": {
            "sha256": file_sha256(source),
            "averageFrameRate": str(source_avg),
            "nominalFrameRate": str(source_nominal),
            "timingClass": ("cfr" if source_avg == source_nominal else
                            "normalized-from-vfr-source"),
            "audioSampleRate": source_audio_rate,
        },
    }


def _assert_inputs(repair: object, evidence: dict[str, object]) -> None:
    parent = evidence["parent"]
    source = evidence["source"]
    picture_fps = getattr(repair, "source_fps")
    source_average = Fraction(str(source.get("averageFrameRate"))) \
        if isinstance(source, dict) else None
    source_nominal = Fraction(str(source.get("nominalFrameRate"))) \
        if isinstance(source, dict) else None
    picture_mismatch = picture_fps is not None and (
        source_average != picture_fps.fraction
        or source_nominal != picture_fps.fraction)
    if not isinstance(parent, dict) or not isinstance(source, dict) \
            or parent.get("videoFrames") != getattr(repair, "total_frames") \
            or source.get("audioSampleRate") != getattr(repair, "source_rate") \
            or picture_mismatch:
        raise RepairRenderError(
            "repair inputs do not match selected source/timeline authority")


def _assert_proof(request: RepairFragmentRequest, repair: object,
                  proof: dict[str, object]) -> None:
    expected_frames = getattr(repair, "dirty_frames").length
    expected_samples = request.clock.samples_for_frames(
        getattr(repair, "dirty_frames")).length
    expected_rate = request.clock.fps.fraction
    actual_rate = _fraction(
        proof.get("averageFrameRate"), "fragment frame rate")
    if proof.get("videoFrames") != expected_frames \
            or proof.get("audioSamplesPerChannel") != expected_samples \
            or actual_rate != expected_rate:
        raise RepairRenderError(
            "fragment decode does not match exact frame/sample authority")


@dataclass(frozen=True)
class _ReceiptInput:
    request: RepairFragmentRequest
    repair: object
    evidence: dict[str, object]
    proof: dict[str, object]
    output_hash: str


def _receipt(item: _ReceiptInput) -> dict[str, object]:
    request = item.request
    repair = item.repair
    dirty = getattr(repair, "dirty_frames")
    samples = request.clock.samples_for_frames(dirty)
    reclaimed = getattr(repair, "reclaimed_frames")
    boundary_residual = 0
    if reclaimed is not None:
        extension = (dirty.end_frame_exclusive
                     - getattr(repair, "extension_frames")
                     if getattr(repair, "edge") == "end"
                     else dirty.start_frame)
        extension_range = type(dirty)(
            extension, extension + getattr(repair, "extension_frames"))
        removed = request.clock.samples_for_frames(reclaimed).length
        inserted = request.clock.samples_for_frames(extension_range).length
        boundary_residual = removed - inserted
    return {
        "schemaVersion": 1,
        "kind": "cut-repair-fragment",
        "operationHash": request.operation_hash,
        "method": getattr(repair, "method"),
        "edge": getattr(repair, "edge"),
        "exactOutputDurationPreserved": True,
        "dirtyFrameRange": dirty.to_dict(),
        "dirtySampleRange": samples.to_dict(),
        "frameBoundaryResidualSamples": boundary_residual,
        "retime": _retime_receipt(request, repair),
        "inputs": item.evidence,
        "output": {"path": request.output_path, "sha256": item.output_hash,
                   **item.proof},
        "tools": {
            "ffmpegSha256": request.tools.ffmpeg_sha256,
            "ffprobeSha256": request.tools.ffprobe_sha256,
        },
        "unchangedPictureMappingRanges":
            request.operation["unchangedPictureMappingRanges"],
        "evidencePolicy":
            "alignment-and-vad-are-bounded-evidence-not-sole-audibility-proof",
    }


def _retime_receipt(request: RepairFragmentRequest,
                    repair: object) -> dict[str, object]:
    source = getattr(repair, "source_extension")
    source_rate = getattr(repair, "source_rate")
    start = request.clock.normalize_source_sample(
        source.start_sample, source_rate)
    end = request.clock.normalize_source_sample(
        source.end_sample_exclusive, source_rate)
    output = getattr(repair, "extension_output_samples")
    effective = Fraction(end - start, output)
    return {
        "requestedSpeed": PositiveRational.from_value(
            request.operation["speed"]).to_dict(),
        "sourceSampleRange": source.to_dict(),
        "sourceSampleRate": source_rate,
        "normalizedSourceSampleRange": {
            "startSample": start,
            "endSampleExclusive": end,
        },
        "outputSamples": output,
        "effectiveRatio": PositiveRational(
            effective.numerator, effective.denominator).to_dict(),
    }


def _publish(staged: str, destination: str) -> None:
    if os.path.lexists(destination):
        raise RepairRenderError("repair fragment destination already exists")
    os.replace(staged, destination)
    descriptor = os.open(destination, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    parent = os.open(os.path.dirname(destination), os.O_RDONLY)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)


def render_repair_fragment(request: RepairFragmentRequest) -> dict[str, object]:
    """Render, fully decode, atomically publish, and receipt one dirty unit."""
    tools = request.tools.validate()
    parent = validate_snapshot(request.parent_path, "parent media")
    source = validate_snapshot(request.source_path, "source media")
    output = os.path.abspath(request.output_path)
    if output != request.output_path or not output.endswith(".mov"):
        raise RepairRenderError("repair output must be an absolute .mov path")
    repair = validate_repair(
        request.operation, request.operation_hash, request.clock)
    evidence = _input_evidence(request, parent, source, tools)
    _assert_inputs(repair, evidence)
    channels = observe_repair_channel_pair(RepairChannelRequest(
        "parent", parent, evidence["parent"]["sha256"],
        "source", source, evidence["source"]["sha256"],
        tools, True))
    evidence["parent"]["channelNormalization"] = channels.first.receipt
    evidence["source"]["channelNormalization"] = channels.second.receipt
    directory = os.path.dirname(output)
    if os.path.realpath(directory) != directory:
        raise RepairRenderError("repair output directory must be canonical")
    work = tempfile.mkdtemp(prefix=".sniper-repair-", dir=directory)
    try:
        job = RepairMediaJob(
            parent, source, os.path.join(work, "video.mp4"),
            os.path.join(work, "audio.wav"),
            os.path.join(work, "fragment.mov"), request.clock, tools,
            channels.first.filter_for("stereo"),
            channels.second.filter_for("stereo"))
        render_staged_media(repair, job)
        channels.assert_stable()
        proof = probe_fragment(job.staged_output_path, job)
        _assert_proof(request, repair, proof)
        output_hash = file_sha256(job.staged_output_path)
        _publish(job.staged_output_path, output)
        receipt = _receipt(_ReceiptInput(
            request, repair, evidence, proof, output_hash))
        if content_hash(receipt) != content_hash(
                json.loads(canonical_json(receipt))):
            raise RepairRenderError("repair receipt is not canonical")
        return receipt
    finally:
        shutil.rmtree(work, ignore_errors=True)
