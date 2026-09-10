"""Controller-derived closed candidate sets for alternate-take repair."""
from __future__ import annotations

from dataclasses import dataclass

from edit.alternate_take_scan_authority import load_retake_scan_authority
from edit.alternate_take_types import (
    AlternateTakeAuthorityError,
    CandidateSetInput,
    RetakeScanAuthority,
    ScanAuthorityInput,
)
from edit.cut_repair_context_sources import (
    ContextMaterializationError,
    digest,
    require_hash,
    stable_file_digest,
)
from edit.exact_timing import (
    FrameRange,
    PositiveRational,
    SampleRange,
    TimingContractError,
)
from edit.repair_impact import frame_window_at_seam
from edit.repair_ranges import source_video_frame_range
from edit.target_resolver import (
    TargetResolutionError,
)


@dataclass(frozen=True)
class _Bindings:
    """Validated source, transcript, and output-clock bindings."""

    source_id: str
    source_path: str
    source_hash: str
    timing_hash: str
    sample_rate: int
    source_fps: PositiveRational
    output_range: dict
    context_hash: str
    operation_hash: str
    snapshot_hash: str


def _integer(value: object, label: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise AlternateTakeAuthorityError(f"{label} is malformed")
    return value


def _picture_range(operation: dict) -> FrameRange:
    rows = operation.get("pictureDirtyWindows")
    if not isinstance(rows, list) or len(rows) != 1:
        raise AlternateTakeAuthorityError(
            "alternate take requires one exact picture dirty window")
    row = rows[0]
    if not isinstance(row, dict) or set(row) != {
            "startFrame", "endFrameExclusive"}:
        raise AlternateTakeAuthorityError("picture dirty window is malformed")
    start = _integer(row["startFrame"], "picture dirty start")
    end = _integer(row["endFrameExclusive"], "picture dirty end", 1)
    if end <= start:
        raise AlternateTakeAuthorityError("picture dirty window is empty")
    return FrameRange(start, end)


def alternate_take_output_range(context: dict, operation: dict) -> dict:
    """Derive the inserted extension inside the target segment output."""
    selected = operation.get("segment")
    segments = context.get("segments")
    if not isinstance(selected, dict) or not isinstance(segments, list):
        raise AlternateTakeAuthorityError(
            "alternate-take target segment is absent")
    matches = [row for row in segments if isinstance(row, dict)
               and row.get("segmentId") == selected.get("segmentId")
               and row.get("elementVersion") == selected.get("elementVersion")]
    if len(matches) != 1 or selected.get("edge") not in {"start", "end"}:
        raise AlternateTakeAuthorityError(
            "alternate-take target segment is ambiguous")
    frames = matches[0].get("outputFrames")
    if not isinstance(frames, dict):
        raise AlternateTakeAuthorityError(
            "alternate-take segment frame range is absent")
    edge = selected["edge"]
    start = _integer(
        frames.get("startFrame"), "alternate-take segment start")
    end = _integer(
        frames.get("endFrameExclusive"), "alternate-take segment end", 1)
    extension = _integer(
        operation.get("extensionFrames"), "extension frames", 1)
    seam = start if edge == "start" else end
    inserted = frame_window_at_seam(
        end, seam, extension, edge == "end")
    dirty = _picture_range(operation)
    if inserted is None or inserted.start_frame < dirty.start_frame \
            or inserted.end_frame_exclusive > dirty.end_frame_exclusive:
        raise AlternateTakeAuthorityError(
            "inserted take window escapes picture dirty authority")
    return {
        "firstFrame": inserted.start_frame,
        "endFrameExclusive": inserted.end_frame_exclusive,
    }


def _bindings(value: CandidateSetInput) -> _Bindings:
    context, operation = value.context, value.operation
    core = {key: item for key, item in context.items()
            if key != "authorityHash"}
    context_hash = require_hash(
        context.get("authorityHash"), "alternate-take context authority")
    if digest(core) != context_hash:
        raise AlternateTakeAuthorityError(
            "alternate-take context authority is stale")
    media, transcript = context.get("sourceMedia"), context.get("transcript")
    if not isinstance(media, dict) or not isinstance(transcript, dict):
        raise AlternateTakeAuthorityError(
            "alternate-take source authority is absent")
    source_id = media.get("sourceId")
    source_path = media.get("path")
    source_hash = require_hash(
        media.get("sha256"), "alternate-take source media")
    timing_hash = require_hash(
        transcript.get("timingHash"), "alternate-take transcript timing")
    target = operation.get("target")
    if not isinstance(source_id, str) or not source_id \
            or not isinstance(source_path, str) \
            or transcript.get("sourceId") != source_id \
            or not isinstance(target, dict) \
            or target.get("sourceId") != source_id:
        raise AlternateTakeAuthorityError(
            "alternate-take source identities do not agree")
    if stable_file_digest(source_path, "alternate-take source") != source_hash:
        raise AlternateTakeAuthorityError(
            "alternate-take source media bytes are stale")
    rate = _integer(
        operation.get("sourceSampleRate"), "source sample rate", 1)
    source_fps = PositiveRational.from_value(operation.get("sourceFrameRate"))
    operation_hash = digest(operation)
    snapshot_hash = digest({
        "schemaVersion": 1, "kind": "alternate-take-source-snapshot-set",
        "sources": [media],
    })
    return _Bindings(
        source_id, source_path, source_hash, timing_hash, rate, source_fps,
        alternate_take_output_range(context, operation),
        context_hash, operation_hash, snapshot_hash)


def _candidate(
    role: str,
    indexes: list[int],
    scan: RetakeScanAuthority,
    binding: _Bindings,
) -> dict:
    selected = [ref for index in indexes for ref in scan.refs[
        scan.layout[index][0]:scan.layout[index][1]]]
    if not selected:
        raise AlternateTakeAuthorityError("retake candidate has no timed words")
    samples = SampleRange(
        selected[0].samples.start_sample,
        selected[-1].samples.end_sample_exclusive)
    frames = source_video_frame_range(
        samples, binding.sample_rate, binding.source_fps)
    core = {
        "role": role, "sourceId": binding.source_id,
        "sourceMediaPath": binding.source_path,
        "sourceMediaSha256": binding.source_hash,
        "transcriptTimingHash": binding.timing_hash,
        "wordIds": [word.word_id for word in selected],
        "sourceSampleRange": {
            **samples.to_dict(), "sampleRate": binding.sample_rate},
        "sourceFrameRange": {
            "firstFrame": frames.start_frame,
            "endFrameExclusive": frames.end_frame_exclusive,
            "fpsNumerator": binding.source_fps.numerator,
            "fpsDenominator": binding.source_fps.denominator,
        },
        "outputFrameRange": dict(binding.output_range),
        "spokenTextHash": digest([word.text for word in selected]),
        "provenance": {
            "kind": "deterministic-retake-scan-v1",
            "retakeReportHash": scan.report_hash,
            "retakePolicyHash": scan.policy_hash,
            "retakeId": scan.retake_id,
            "utteranceIndexes": indexes,
        },
    }
    candidate_hash = digest(core)
    return {
        "candidateId": f"take-{candidate_hash[:24]}",
        "candidateHash": candidate_hash, **core,
    }


def _build(value: CandidateSetInput) -> dict:
    binding = _bindings(value)
    scan = load_retake_scan_authority(ScanAuthorityInput(
        value.context, binding.source_id, binding.sample_rate,
        binding.timing_hash, value.transcript_path, value.retake_id))
    candidates = [
        _candidate("earlier", scan.earlier_indexes, scan, binding),
        _candidate("later", scan.later_indexes, scan, binding),
    ]
    candidates.sort(key=lambda item: item["candidateId"])
    if len({item["candidateHash"] for item in candidates}) != 2:
        raise AlternateTakeAuthorityError(
            "retake candidate set is not uniquely closed")
    core = {
        "schemaVersion": 1,
        "kind": "cut-repair-alternate-take-candidate-set",
        "operationHash": binding.operation_hash,
        "contextAuthorityHash": binding.context_hash,
        "sourceSnapshotSetHash": binding.snapshot_hash,
        "sourceId": binding.source_id,
        "sourceMediaPath": binding.source_path,
        "sourceMediaSha256": binding.source_hash,
        "transcriptPath": value.transcript_path,
        "transcriptSha256": scan.transcript_hash,
        "transcriptTimingHash": binding.timing_hash,
        "detectorToolClosure": scan.detector_closure,
        "detectorToolClosureHash": scan.detector_closure_hash,
        "retakePolicyHash": scan.policy_hash,
        "retakeReportHash": scan.report_hash,
        "retakeId": value.retake_id,
        "candidates": candidates,
    }
    return {**core, "candidateSetHash": digest(core)}


def build_alternate_take_candidate_set(value: CandidateSetInput) -> dict:
    """Derive IDs and exact ranges; callers cannot supply candidate identity."""
    try:
        return _build(value)
    except AlternateTakeAuthorityError:
        raise
    except (
            ContextMaterializationError, TargetResolutionError,
            TimingContractError, KeyError, TypeError, ValueError,
            OSError,
    ) as exc:
        raise AlternateTakeAuthorityError(
            "alternate-take candidate authority is malformed") from exc
