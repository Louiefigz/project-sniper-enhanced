"""Sequential original-owner source observations, not color application or release.

The caller has already preflighted every used source and holds the real shared
color resource and project lease. This module acquires neither. It runs existing
owned observations in the SAME process, seals each real result immediately, and
retains failures and queue/work times without starting another overall clock.
There is deliberately no outer signal timer around protected native cleanup.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from color.deadline import require_time
from color.grade_project import run_project_observation_owned
from color.grade_project_completion import (
    CompletedProjectObservation, _binding as completed_binding, seal_completed_project_observation,
)
from color.grade_project_owned import (
    GradeProjectOwnedContext, OwnedProjectObservationError, _assert_held_files, _typed_fields, observation_binding,
)
from guided_source_color_batch import PreparedSourceColorBatch, _PreparedColorJob
from guided_source_color_hold import HeldSourceColorPreparation, _binding as preparation_binding


@dataclass(frozen=True)
class SourceColorJobTiming:
    """Milliseconds since batch execution entry, including earlier queued source work."""

    source_id: str
    started_ms: int
    elapsed_ms: int
    status: str
    cleanup_verified: bool | None


class SourceColorExecutionError(RuntimeError):
    """Retain bounded diagnostics only, never partial completion objects or release power."""

    def __init__(self, cause: Exception, timings: tuple[SourceColorJobTiming, ...]) -> None:
        """Keep every attempted source's elapsed/cleanup facts when the batch fails."""
        super().__init__(f"source color batch did not complete: {type(cause).__name__}: {cause}"[:3000])
        self.timings = timings


def _elapsed(started: float) -> int:
    """Measure elapsed work, including protected cleanup after a work deadline expires."""
    elapsed = time.monotonic() - started
    if elapsed < 0:
        raise RuntimeError("source color batch monotonic clock moved backwards")
    return round(elapsed * 1000)


def _binding(value: CompletedSourceColorBatch) -> tuple:
    """Retain the actual prepared lifetime and live-sealed result objects unchanged."""
    if type(value.preparation) is not HeldSourceColorPreparation or type(value.observations) is not tuple \
            or type(value.timings) is not tuple or not value.observations \
            or len(value.observations) != len(value.timings) \
            or type(value._preflight) is not PreparedSourceColorBatch \
            or value._preflight.preparation is not value.preparation:
        raise RuntimeError("completed source color batch lifetime is malformed")
    if any(type(row) is not CompletedProjectObservation for row in value.observations) \
            or any(type(row) is not SourceColorJobTiming for row in value.timings):
        raise RuntimeError("completed source color batch has replaced results or timings")
    preflight = value._preflight
    preflight._read.unchanged()
    return (id(value), preparation_binding(value.preparation), value.preparation._read.arguments(),
            id(preflight), id(preflight._origin), preflight.binding(), preflight._read.arguments(),
            id(value.observations), tuple((id(row), completed_binding(row), observation_binding(row.observation))
                                         for row in value.observations),
            id(value.timings), tuple((id(row), _typed_fields(row)) for row in value.timings),
            _typed_fields(value, ("preparation", "observations", "timings", "_preflight", "_origin")))


def _unchanged(value: CompletedSourceColorBatch, original: tuple) -> None:
    """Completed evidence cannot adopt replacement timing, preparation or approvals."""
    if value._origin is not original or _binding(value) != original:
        raise RuntimeError("completed source color batch original references or metadata changed")


@dataclass(frozen=True, init=False)
class CompletedSourceColorBatch:
    """Actual all-source observed data under the persistent original caller lifetime."""

    preparation: HeldSourceColorPreparation
    observations: tuple[CompletedProjectObservation, ...]
    timings: tuple[SourceColorJobTiming, ...]
    elapsed_ms: int
    executable: bool = field(default=False, init=False)
    grade_applicable: bool = field(default=False, init=False)
    delivery_approved: bool = field(default=False, init=False)
    _preflight: PreparedSourceColorBatch = field(repr=False)
    _origin: tuple = field(repr=False)

    def __init__(self) -> None:
        """Stored JSON cannot construct actual same-process source observation results."""
        raise TypeError("completed source color batch requires run_source_color_batch")

    def assert_current(self) -> None:
        """Check completed data without consulting retired transient launch/resource claims."""
        original = self._origin
        _unchanged(self, original)
        self._preflight.assert_current()
        for observed in self.observations:
            observed.assert_current()
        _unchanged(self, original)
        self._preflight.assert_current()
        for observed in self.observations:
            _assert_held_files(observed.files, self.preparation.context.deadline)
        _unchanged(self, original)
        require_time(self.preparation.context.deadline)


def _observe(batch: PreparedSourceColorBatch, job: _PreparedColorJob) -> CompletedProjectObservation:
    """Run one existing phase and seal before its original per-profile cutoff expires."""
    batch.assert_current()
    preparation = batch.preparation
    context = GradeProjectOwnedContext(preparation.context.deadline, preparation.assert_current, job.source)
    owned = run_project_observation_owned(job.value, job.directory, context, job.launch)
    completed = seal_completed_project_observation(owned)
    batch.assert_current()
    return completed


def _run_one(batch: PreparedSourceColorBatch, job: _PreparedColorJob,
             started: float, timings: list[SourceColorJobTiming]) -> CompletedProjectObservation:
    """Retain even a failed source's queue/work time without exposing partial success."""
    queued, phase = _elapsed(started), time.monotonic()
    source_id = job.source_id
    try:
        completed = _observe(batch, job)
    except Exception as error:
        cleanup = error.result.get("cleanupVerified") if type(error) is OwnedProjectObservationError else None
        cleanup = cleanup if type(cleanup) is bool else None
        timings.append(SourceColorJobTiming(source_id, queued, _elapsed(phase), "failed", cleanup))
        raise
    timings.append(SourceColorJobTiming(source_id, queued, _elapsed(phase), "complete", True))
    return completed


def _complete(batch: PreparedSourceColorBatch, observed: tuple,
              timings: tuple, started: float) -> CompletedSourceColorBatch:
    """Capture successful actual results before final original-lifetime checks."""
    value = object.__new__(CompletedSourceColorBatch)
    values = {"preparation": batch.preparation, "observations": observed, "timings": timings, "_preflight": batch,
              "elapsed_ms": _elapsed(started), "executable": False, "grade_applicable": False, "delivery_approved": False}
    for name, item in values.items():
        object.__setattr__(value, name, item)
    object.__setattr__(value, "_origin", _binding(value))
    original = value._origin
    value.assert_current()
    _unchanged(value, original)
    elapsed = _elapsed(started)
    timing_fields = tuple((name, (int, elapsed)) if name == "elapsed_ms" else (name, held)
                         for name, held in original[-1])
    expected = (*original[:-1], timing_fields)
    object.__setattr__(value, "elapsed_ms", elapsed)
    object.__setattr__(value, "_origin", expected)
    _unchanged(value, expected)
    require_time(value.preparation.context.deadline)
    return value


def run_source_color_batch(batch: PreparedSourceColorBatch) -> CompletedSourceColorBatch:
    """Observe the complete preflighted source set, sequentially under one original owner."""
    if type(batch) is not PreparedSourceColorBatch:
        raise ValueError("source color execution requires the actual all-source batch preflight")
    started, timings = time.monotonic(), []
    try:
        batch.assert_current()
        observed = tuple(_run_one(batch, job, started, timings) for job in batch.jobs)
        batch.assert_current()
        return _complete(batch, observed, tuple(timings), started)
    except Exception as error:
        raise SourceColorExecutionError(error, tuple(timings)) from error
