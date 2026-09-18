"""Adapt governed alternate-take authority to the visual QC oracle."""
from __future__ import annotations

from edit.cut_repair_candidate_qc_types import (
    CandidateQcContractError,
    QcRun,
)
from edit.cut_repair_context_sources import require_hash
from edit.cut_repair_visual_lip_sync import qualify_visual_lip_sync
from edit.cut_repair_visual_lip_sync_types import (
    FrameSpan,
    MediaAuthority,
    OracleRequest,
    OracleToolchain,
    RationalRate,
    RegionPpm,
    SampleSpan,
    SelectionAuthority,
    VisualLipSyncBlocker,
)


def _integer(value: object, minimum: int, label: str) -> int:
    if type(value) is not int or value < minimum:
        raise CandidateQcContractError(f"{label} is malformed")
    return value


def _frame_span(value: object, label: str) -> FrameSpan:
    if not isinstance(value, dict):
        raise CandidateQcContractError(f"{label} is absent")
    first = _integer(value.get("firstFrame"), 0, label)
    end = _integer(value.get("endFrameExclusive"), 1, label)
    if end <= first:
        raise CandidateQcContractError(f"{label} is empty")
    return FrameSpan(first, end)


def _rate(value: dict, label: str) -> RationalRate:
    numerator = _integer(value.get("fpsNumerator"), 1, label)
    denominator = _integer(value.get("fpsDenominator"), 1, label)
    return RationalRate(numerator, denominator)


def _sample_span(value: object) -> SampleSpan:
    if not isinstance(value, dict):
        raise CandidateQcContractError("selected source sample range is absent")
    start = _integer(value.get("startSample"), 0, "source sample range")
    end = _integer(
        value.get("endSampleExclusive"), 1, "source sample range")
    rate = _integer(value.get("sampleRate"), 1, "source sample rate")
    if end <= start:
        raise CandidateQcContractError("selected source sample range is empty")
    return SampleSpan(start, end, rate)


def _output_samples(run: QcRun, frames: FrameSpan) -> SampleSpan:
    window = run.authority.window
    numerator = window.fps_numerator
    denominator = window.fps_denominator
    rate = window.sample_rate
    start = frames.first * denominator * rate // numerator
    end = frames.end_exclusive * denominator * rate // numerator
    return SampleSpan(start, end, rate)


def _region(value: object) -> RegionPpm:
    if not isinstance(value, dict):
        raise CandidateQcContractError("visual speech region is absent")
    return RegionPpm(
        _integer(value.get("xPpm"), 0, "visual speech region x"),
        _integer(value.get("yPpm"), 0, "visual speech region y"),
        _integer(value.get("widthPpm"), 1, "visual speech region width"),
        _integer(value.get("heightPpm"), 1, "visual speech region height"),
    )


def _selection(run: QcRun) -> SelectionAuthority:
    authority = run.authority
    selected = authority.alternate_take_selection
    if not isinstance(selected, dict):
        raise CandidateQcContractError(
            "picture-changing QC has no alternate-take selection")
    receipt_hash = require_hash(
        authority.alternate_take_selection_hash,
        "alternate-take selection receipt")
    if selected.get("receiptHash") != receipt_hash:
        raise CandidateQcContractError(
            "alternate-take selection attachment is stale")
    source_frames = _frame_span(
        selected.get("sourceFrameRange"), "selected source frame range")
    output_frames = _frame_span(
        selected.get("outputFrameRange"), "selected output frame range")
    source_row = selected["sourceFrameRange"]
    window = authority.window
    return SelectionAuthority(
        authority.preparation_hash,
        authority.descriptor["operationHash"],
        receipt_hash,
        require_hash(selected.get("candidateSetHash"), "candidate set"),
        require_hash(selected.get("selectionHash"), "take selection"),
        selected["selectedCandidateId"],
        selected["sourceId"],
        selected["sourceMediaPath"],
        require_hash(selected.get("sourceMediaSha256"), "selected source"),
        source_frames,
        _sample_span(selected.get("sourceSampleRange")),
        _rate(source_row, "selected source frame rate"),
        output_frames,
        _output_samples(run, output_frames),
        RationalRate(window.fps_numerator, window.fps_denominator),
        _region(selected.get("visualSpeechRegion")),
    )


def _tools(run: QcRun) -> OracleToolchain:
    tool = run.tools.visual_oracle
    if tool is None:
        raise VisualLipSyncBlocker(
            "LIP_SYNC_ORACLE_UNAVAILABLE",
            "picture-changing repair requires the pinned visual oracle")
    return OracleToolchain(
        run.tools.ffmpeg.path,
        run.tools.ffmpeg.sha256,
        tool.runtime.path,
        tool.runtime.sha256,
        tool.implementation.path,
        tool.implementation.sha256,
        tool.implementation_scope,
        tool.implementation_nonclaims,
        tool.policy.path,
        tool.policy.sha256,
        tool.implementation_closure_hash,
        tuple(
            (item.role, item.file.path, item.file.sha256)
            for item in tool.implementation_files),
    )


def visual_observation(run: QcRun) -> dict:
    """Run visual proof only inside the governed picture-dirty QC path."""
    if not run.authority.picture_dirty:
        return {"status": "not-applicable"}
    try:
        request = OracleRequest(
            _selection(run),
            MediaAuthority(
                run.authority.candidate_path,
                run.authority.candidate_sha256),
            _tools(run),
            run.tools.manifest_hash,
        )
        return {
            "status": "bounded-pass",
            "receipt": qualify_visual_lip_sync(request),
        }
    except VisualLipSyncBlocker as blocker:
        return {
            "status": "blocked",
            "blocker": {
                "code": blocker.code,
                "message": blocker.message,
            },
        }
