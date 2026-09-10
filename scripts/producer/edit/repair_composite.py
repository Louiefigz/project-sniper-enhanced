"""Build and prove one terminal full-media P2 repair candidate."""
from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from fractions import Fraction

from edit.exact_timing import FrameRange, ProjectClock, SampleRange
from edit.picture_lock_common import content_hash
from edit.repair_channel_authority import (
    RepairChannelPair,
    RepairChannelRequest,
    observe_repair_channel_pair,
)
from edit.repair_composite_media import (
    RepairCompositeMediaJob,
    outside_dirty_oracle,
    probe_full_media,
    render_composite,
)
from edit.repair_fragment_contracts import (
    RepairMediaTools,
    RepairRenderError,
    validate_snapshot,
)
from fingerprints import file_sha256


@dataclass(frozen=True)
class RepairCompositeRequest:
    """Immutable inputs for one parent + fragment full-media candidate."""

    parent_path: str
    fragment_path: str
    output_path: str
    fragment_receipt: dict[str, object]
    operation_hash: str
    clock: ProjectClock
    tools: RepairMediaTools


@dataclass(frozen=True)
class _ValidatedComposite:
    parent_path: str
    fragment_path: str
    output_path: str
    total_frames: int
    dirty_frames: FrameRange
    dirty_samples: SampleRange
    picture_dirty: bool
    receipt_hash: str
    channels: RepairChannelPair


def _frame_range(value: object) -> FrameRange:
    if not isinstance(value, dict) or set(value) != {
            "startFrame", "endFrameExclusive"}:
        raise RepairRenderError("fragment receipt dirtyFrameRange is invalid")
    try:
        return FrameRange(
            value["startFrame"], value["endFrameExclusive"])
    except (TypeError, ValueError) as exc:
        raise RepairRenderError(
            "fragment receipt dirtyFrameRange is invalid") from exc


def _sample_range(value: object) -> SampleRange:
    if not isinstance(value, dict) or set(value) != {
            "startSample", "endSampleExclusive"}:
        raise RepairRenderError("fragment receipt dirtySampleRange is invalid")
    try:
        return SampleRange(
            value["startSample"], value["endSampleExclusive"])
    except (TypeError, ValueError) as exc:
        raise RepairRenderError(
            "fragment receipt dirtySampleRange is invalid") from exc


def _receipt_rows(receipt: dict[str, object]) -> tuple[dict, dict, dict]:
    inputs = receipt.get("inputs")
    output = receipt.get("output")
    if not isinstance(inputs, dict) or not isinstance(output, dict):
        raise RepairRenderError("fragment receipt media evidence is malformed")
    parent = inputs.get("parent")
    if not isinstance(parent, dict):
        raise RepairRenderError("fragment receipt parent evidence is malformed")
    return inputs, parent, output


def _sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 \
        and all(char in "0123456789abcdef" for char in value)


def _composite_channels(
    request: RepairCompositeRequest,
    paths: tuple[str, str],
    proofs: tuple[dict, dict],
) -> RepairChannelPair:
    parent_path, fragment_path = paths
    parent, fragment = proofs
    return observe_repair_channel_pair(RepairChannelRequest(
        "parent", parent_path, parent["sha256"],
        "fragment", fragment_path, fragment["sha256"],
        request.tools, False))


def _validate_parent_rate(value: object, expected: Fraction) -> None:
    """Require the fragment parent to retain the exact project frame rate."""
    try:
        observed = Fraction(str(value))
    except (ValueError, ZeroDivisionError) as exc:
        raise RepairRenderError("fragment parent rate is invalid") from exc
    if observed != expected:
        raise RepairRenderError("fragment parent rate differs from project FPS")


def _validate_receipt(request: RepairCompositeRequest,
                      parent_path: str,
                      fragment_path: str) -> _ValidatedComposite:
    receipt = request.fragment_receipt
    expected_keys = {
        "schemaVersion", "kind", "operationHash", "method", "edge",
        "exactOutputDurationPreserved", "dirtyFrameRange",
        "dirtySampleRange", "frameBoundaryResidualSamples", "retime",
        "inputs", "output", "tools", "unchangedPictureMappingRanges",
        "evidencePolicy",
    }
    if not isinstance(receipt, dict) or set(receipt) != expected_keys \
            or receipt.get("schemaVersion") != 1 \
            or receipt.get("kind") != "cut-repair-fragment" \
            or not _sha256(request.operation_hash) \
            or receipt.get("operationHash") != request.operation_hash:
        raise RepairRenderError("unsupported fragment receipt")
    _inputs, parent, fragment = _receipt_rows(receipt)
    receipt_tools = receipt.get("tools")
    tools_match = isinstance(receipt_tools, dict) \
        and receipt_tools.get("ffmpegSha256") == request.tools.ffmpeg_sha256 \
        and receipt_tools.get("ffprobeSha256") == request.tools.ffprobe_sha256
    if parent.get("sha256") != file_sha256(parent_path) \
            or fragment.get("sha256") != file_sha256(fragment_path) \
            or fragment.get("path") != request.fragment_path \
            or not tools_match:
        raise RepairRenderError("fragment receipt does not bind media bytes")
    frames = _frame_range(receipt.get("dirtyFrameRange"))
    samples = _sample_range(receipt.get("dirtySampleRange"))
    total = parent.get("videoFrames")
    if type(total) is not int \
            or total < frames.end_frame_exclusive \
            or frames.start_frame == 0 \
            and frames.end_frame_exclusive == total:
        raise RepairRenderError("fragment receipt total frame count is invalid")
    if fragment.get("videoFrames") != frames.length \
            or fragment.get("audioSamplesPerChannel") != samples.length \
            or samples != request.clock.samples_for_frames(frames):
        raise RepairRenderError("fragment receipt clocks are inconsistent")
    _validate_parent_rate(
        parent.get("averageFrameRate"), request.clock.fps.fraction)
    channels = _composite_channels(
        request, (parent_path, fragment_path), (parent, fragment))
    return _ValidatedComposite(
        parent_path, fragment_path, request.output_path, total,
        frames, samples, receipt.get("method")
        == "extend-and-reclaim-silence", content_hash(receipt), channels)


def _validate_request(request: RepairCompositeRequest) -> _ValidatedComposite:
    request.tools.validate()
    parent = validate_snapshot(request.parent_path, "composite parent")
    fragment = validate_snapshot(request.fragment_path, "repair fragment")
    output = os.path.abspath(request.output_path)
    if output != request.output_path or not output.endswith(".mov"):
        raise RepairRenderError(
            "repair composite output must be an absolute .mov path")
    directory = os.path.dirname(output)
    if os.path.realpath(directory) != directory:
        raise RepairRenderError("repair composite directory must be canonical")
    if os.path.lexists(output):
        raise RepairRenderError("repair composite destination already exists")
    return _validate_receipt(request, parent, fragment)


def _job(value: _ValidatedComposite, request: RepairCompositeRequest,
         work: str) -> RepairCompositeMediaJob:
    return RepairCompositeMediaJob(
        value.parent_path,
        value.fragment_path,
        os.path.join(work, "picture.mp4"),
        os.path.join(work, "dialogue.wav"),
        os.path.join(work, "candidate.mov"),
        value.total_frames,
        value.dirty_frames,
        value.picture_dirty,
        request.clock,
        request.tools,
        value.channels.first.filter_for("stereo"),
        value.channels.second.filter_for("stereo"),
    )


def _assert_full_probe(proof: dict[str, object],
                       value: _ValidatedComposite,
                       clock: ProjectClock) -> None:
    expected_samples = clock.sample_at_frame(value.total_frames)
    try:
        actual_rate = Fraction(str(proof.get("averageFrameRate")))
    except (ValueError, ZeroDivisionError) as exc:
        raise RepairRenderError("candidate frame rate is invalid") from exc
    if proof.get("videoFrames") != value.total_frames \
            or proof.get("audioSamplesPerChannel") != expected_samples \
            or actual_rate != clock.fps.fraction:
        raise RepairRenderError(
            "candidate does not match terminal frame/sample authority")


def _publish(staged: str, destination: str) -> None:
    if os.path.lexists(destination):
        raise RepairRenderError("repair composite destination already exists")
    os.replace(staged, destination)
    descriptor = os.open(destination, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory = os.open(os.path.dirname(destination), os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _receipt(request: RepairCompositeRequest,
             value: _ValidatedComposite,
             proof: dict[str, object],
             oracle: dict[str, object]) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "kind": "cut-repair-composite",
        "operationHash": request.operation_hash,
        "fragmentReceiptHash": value.receipt_hash,
        "clock": {
            "fps": request.clock.fps.to_dict(),
            "sampleRate": request.clock.sample_rate,
        },
        "dirtyFrameRange": value.dirty_frames.to_dict(),
        "dirtySampleRange": value.dirty_samples.to_dict(),
        "terminalExpectedSamples":
            request.clock.sample_at_frame(value.total_frames),
        "exactOutputDurationPreserved": True,
        "inputs": {
            "parentSha256": file_sha256(value.parent_path),
            "fragmentSha256": file_sha256(value.fragment_path),
            "channelNormalization": value.channels.receipts(),
        },
        "output": {
            "path": value.output_path,
            "sha256": file_sha256(value.output_path),
            **proof,
        },
        "outsideDirtyOracle": oracle,
        "tools": {
            "ffmpegSha256": request.tools.ffmpeg_sha256,
            "ffprobeSha256": request.tools.ffprobe_sha256,
        },
    }


def render_repair_composite(
    request: RepairCompositeRequest,
) -> dict[str, object]:
    """Render, fully decode, oracle-check, and publish a repaired candidate."""
    value = _validate_request(request)
    work = tempfile.mkdtemp(
        prefix=".sniper-repair-composite-",
        dir=os.path.dirname(value.output_path))
    try:
        job = _job(value, request, work)
        parent_proof = probe_full_media(value.parent_path, job)
        _assert_full_probe(parent_proof, value, request.clock)
        render_composite(job)
        value.channels.assert_stable()
        proof = probe_full_media(job.staged_output_path, job)
        _assert_full_probe(proof, value, request.clock)
        oracle = outside_dirty_oracle(
            value.parent_path, job.staged_output_path, job)
        if oracle["pictureMatches"] is not True \
                or oracle["pcmMatches"] is not True:
            raise RepairRenderError(
                "candidate changed decoded media outside dirty closure")
        _publish(job.staged_output_path, value.output_path)
        return _receipt(request, value, proof, oracle)
    finally:
        shutil.rmtree(work, ignore_errors=True)
