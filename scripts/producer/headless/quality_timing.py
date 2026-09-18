"""Complete monotonic timing receipts for one headless MP4 quality pass."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable

REQUIRED_STAGES = (
    "admission_import",
    "repair",
    "deterministic_gates",
    "resource_wait",
    "overlay_render",
    "composite_audio_proxy",
    "deterministic_qc",
    "model_queue",
    "model_run",
    "rendered_critics",
    "proof_sealing",
)
_STATUSES = {"completed", "failed", "skipped"}


class QualityTimingError(RuntimeError):
    """A stage timing is duplicate, incomplete, or not monotonic."""


@dataclass(frozen=True)
class TimingSpanV1:
    """One terminal monotonic stage observation."""

    name: str
    status: str
    started_ns: int
    ended_ns: int
    duration_ns: int
    detail: str | None


@dataclass(frozen=True)
class TimingReceiptV1:
    """Closed timing set and its domain-separated identity."""

    spans: tuple[TimingSpanV1, ...]
    total_duration_ns: int
    digest: str


@dataclass(frozen=True)
class _SpanSpec:
    name: str
    status: str
    start: int
    end: int
    detail: str | None


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"),
                      sort_keys=True, allow_nan=False).encode("ascii")


def _span(spec: _SpanSpec) -> TimingSpanV1:
    valid = (spec.name in REQUIRED_STAGES and spec.status in _STATUSES
             and type(spec.start) is int and type(spec.end) is int
             and 0 <= spec.start <= spec.end
             and (spec.detail is None or isinstance(spec.detail, str)))
    if not valid:
        raise QualityTimingError("quality timing span is invalid")
    return TimingSpanV1(spec.name, spec.status, spec.start, spec.end,
                        spec.end - spec.start, spec.detail)


class TimingRecorder:
    """Measure each required stage once and persist terminal spans immediately."""

    def __init__(self, clock_ns: Callable[[], int] = time.monotonic_ns,
                 sink: Callable[[TimingSpanV1], None] | None = None):
        self._clock = clock_ns
        self._sink = sink or (lambda _span_value: None)
        self._spans: dict[str, TimingSpanV1] = {}
        self._first_ns = self._now()

    def _now(self) -> int:
        value = self._clock()
        if type(value) is not int or value < 0:
            raise QualityTimingError("monotonic timing clock is invalid")
        return value

    def _validate_next(self, name: str) -> None:
        if name in self._spans:
            raise QualityTimingError(f"duplicate quality timing stage: {name}")
        if name not in REQUIRED_STAGES:
            raise QualityTimingError(f"unknown quality timing stage: {name}")
        index = len(self._spans)
        if index == len(REQUIRED_STAGES):
            raise QualityTimingError("quality timing stages are already complete")
        expected = REQUIRED_STAGES[index]
        if name != expected:
            raise QualityTimingError(
                f"quality timing stage out of order: expected {expected}")

    def _validate_chronology(self, span: TimingSpanV1) -> None:
        self._validate_start(span.started_ns)

    def _validate_start(self, value: int) -> None:
        if value < self._first_ns:
            raise QualityTimingError("quality timing clock predates recorder")
        if not self._spans:
            return
        previous = next(reversed(self._spans.values()))
        if value < previous.ended_ns:
            raise QualityTimingError("quality timing chronology regressed")

    def _record(self, span: TimingSpanV1) -> None:
        self._validate_next(span.name)
        self._validate_chronology(span)
        self._sink(span)
        self._spans[span.name] = span

    def measure(self, name: str, operation: Callable[[], Any]) -> Any:
        """Measure a terminal stage, persisting failure before re-raising."""
        self._validate_next(name)
        start = self._now()
        self._validate_start(start)
        try:
            result = operation()
        except BaseException as exc:
            end = self._now()
            self._record(_span(_SpanSpec(
                name, "failed", start, end, type(exc).__name__)))
            raise
        end = self._now()
        self._record(_span(_SpanSpec(name, "completed", start, end, None)))
        return result

    def skip(self, name: str, reason: str) -> None:
        """Record an intentionally absent stage instead of losing it."""
        if not isinstance(reason, str) or not reason:
            raise QualityTimingError("skipped timing stage needs a reason")
        self._validate_next(name)
        instant = self._now()
        self._validate_start(instant)
        self._record(_span(_SpanSpec(
            name, "skipped", instant, instant, reason)))

    def receipt(self) -> TimingReceiptV1:
        """Close the exact required stage set into one immutable receipt."""
        missing = [name for name in REQUIRED_STAGES if name not in self._spans]
        if missing:
            raise QualityTimingError(
                f"quality timing stages are incomplete: {','.join(missing)}")
        ordered = tuple(self._spans[name] for name in REQUIRED_STAGES)
        total = ordered[-1].ended_ns - self._first_ns
        if total < 0:
            raise QualityTimingError("quality timing total duration is negative")
        payload = {"schemaVersion": 1, "clock": "CLOCK_MONOTONIC",
                   "spans": [asdict(span) for span in ordered],
                   "totalDurationNs": total}
        digest = hashlib.sha256(
            b"sniper-quality-timing-v1\0" + _canonical(payload)).hexdigest()
        return TimingReceiptV1(ordered, total, digest)
