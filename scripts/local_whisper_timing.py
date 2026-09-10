"""One bounded CPU retry when GPU Whisper returns collapsed word timings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from local_whisper_parser import WhisperParseError, parse_whisper_json
from transcript_timing_quality import timing_quality_report

Retry = Callable[[], tuple[Optional[dict], str]]
Emit = Optional[Callable[[dict], None]]


class WhisperTimingError(RuntimeError):
    """Whisper output remains unsafe for word-addressed editing."""


@dataclass(frozen=True)
class TimingContext:
    """Inputs required to parse and report one transcript attempt."""

    timeline_offset: float
    speaker: Optional[int]
    emit: Emit


def _parse(payload: dict, context: TimingContext) -> tuple[list[dict], dict]:
    try:
        transcript = parse_whisper_json(
            payload, context.timeline_offset, context.speaker)
    except WhisperParseError as exc:
        raise WhisperTimingError(str(exc)) from exc
    report = timing_quality_report({"transcript": transcript})
    return transcript, report


def accept_or_retry(
    payload: dict,
    cpu: bool,
    context: TimingContext,
    retry_cpu: Retry,
) -> tuple[dict, list[dict], bool, dict]:
    """Accept good timing or run exactly one CPU retry and fail closed."""
    transcript, report = _parse(payload, context)
    if report["status"] == "pass":
        return payload, transcript, cpu, report
    if cpu:
        codes = ",".join(v["code"] for v in report["violations"])
        raise WhisperTimingError(
            f"transcript timing quality failed after CPU retry: {codes}")
    if context.emit:
        context.emit({
            "status": "local_whisper_timing_retry", "quality": report})
    retried, error = retry_cpu()
    if retried is None:
        raise WhisperTimingError(
            f"timing-quality CPU retry failed: {error}")
    transcript, report = _parse(retried, context)
    if report["status"] != "pass":
        codes = ",".join(v["code"] for v in report["violations"])
        raise WhisperTimingError(
            f"transcript timing quality failed after CPU retry: {codes}")
    return retried, transcript, True, report
