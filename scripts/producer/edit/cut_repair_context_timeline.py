"""Adapt the current timeline compiler to P2 exact frame/sample authority."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

from compile_timeline import Segment, compile_plan
from edit.cut_repair_context_sources import (
    ContextMaterializationError,
    digest,
    rational_rate,
    to_sample,
)


def _frame(value: Decimal, rate: tuple[int, int]) -> int:
    frames = Fraction(value) * Fraction(*rate)
    return (2 * frames.numerator + frames.denominator) \
        // (2 * frames.denominator)


@dataclass(frozen=True)
class _SegmentInput:
    plan_row: dict
    index: int
    source: dict
    compiled: Segment
    project_rate: tuple[int, int]


def _identity(value: _SegmentInput) -> tuple[str, int]:
    raw_id = value.plan_row.get("id")
    segment_id = raw_id if isinstance(raw_id, str) and raw_id else (
        f"legacy-cut-{value.index:06d}-{digest(value.plan_row)[:12]}")
    version = value.plan_row.get(
        "generation", value.plan_row.get("version", 1))
    if type(version) is not int or version < 1:
        raise ContextMaterializationError(
            f"cutTrack[{value.index}] element version is invalid")
    return segment_id, version


def _segment_row(value: _SegmentInput) -> dict:
    audio = value.source.get("audio")
    if not isinstance(audio, dict) or not isinstance(audio.get(
            "sampleRate"), int):
        raise ContextMaterializationError("source sample rate is absent")
    start = Decimal(str(value.compiled.src_start))
    end = Decimal(str(value.compiled.src_end))
    out_start = Decimal(str(value.compiled.out_start))
    out_end = Decimal(str(value.compiled.out_end))
    speed = Fraction(Decimal(str(value.compiled.speed)))
    segment_id, version = _identity(value)
    source_fps = None if value.source.get("vfr") is True else rational_rate(
        value.source.get("fps"), "source fps")
    row = {
        "segmentId": segment_id, "elementVersion": version,
        "sourceId": value.compiled.source_id,
        "sourceRate": audio["sampleRate"],
        "sourceSamples": {
            "startSample": to_sample(start, audio["sampleRate"], "segment start"),
            "endSampleExclusive": to_sample(
                end, audio["sampleRate"], "segment end"),
        },
        "outputFrames": {
            "startFrame": _frame(out_start, value.project_rate),
            "endFrameExclusive": _frame(out_end, value.project_rate),
        },
        "speed": {
            "numerator": str(speed.numerator),
            "denominator": str(speed.denominator),
        },
        **({"sourceFps": {
            "numerator": str(source_fps[0]),
            "denominator": str(source_fps[1]),
        }} if source_fps else {}),
    }
    if row["sourceSamples"]["endSampleExclusive"] \
            <= row["sourceSamples"]["startSample"] \
            or row["outputFrames"]["endFrameExclusive"] \
            <= row["outputFrames"]["startFrame"]:
        raise ContextMaterializationError(
            f"cutTrack[{value.index}] collapses on exact clocks")
    return row


def segments(plan: dict, sources: dict[str, dict],
             project_rate: tuple[int, int]) -> tuple[list[dict], int]:
    """Use the live compiler, then quantize its emitted map exactly."""
    track = plan.get("cutTrack")
    if not isinstance(track, list) or not track:
        raise ContextMaterializationError("plan has no cutTrack")
    try:
        timeline = compile_plan(plan)
    except (KeyError, TypeError, ValueError) as exc:
        raise ContextMaterializationError(
            f"live timeline compiler rejected the cut: {exc}") from exc
    if len(track) != len(timeline.segments):
        raise ContextMaterializationError("live timeline compiler lost a cut")
    result = []
    for index, (row, compiled) in enumerate(zip(
            track, timeline.segments, strict=True)):
        source_id = row.get("sourceId") if isinstance(row, dict) else None
        if source_id not in sources or compiled.source_id != source_id:
            raise ContextMaterializationError(f"cutTrack[{index}] is malformed")
        result.append(_segment_row(_SegmentInput(
            row, index, sources[source_id], compiled, project_rate)))
    total = _frame(Decimal(str(timeline.output_duration)), project_rate)
    if result[-1]["outputFrames"]["endFrameExclusive"] != total:
        raise ContextMaterializationError(
            "live timeline compiler terminal clock drifted")
    return result, total
