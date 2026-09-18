"""Internal split reservation cleanup after authenticated TS process settlement.

The caller MUST already prove original outer/nested workers and Docker launch
clients settled, and verify actual runtime controls. Typed records and JSON do
not prove either prerequisite. Prepare holds three metadata files; callers do
their graphics/control checks next, then explicitly reconcile grade names LAST.
No controller, timer allowance, config directory, lease or release is created.
"""
from __future__ import annotations

import math
import os
import stat
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from color.deadline import require_time
from guided_opening_claim import HeldOpeningClaim
from guided_opening_execution import OpeningExecutionClock
from guided_opening_inputs import hash_value
from guided_presenter_read_fingerprint import hold_read_metadata, same_read_metadata
from guided_source_color_reservation_read import (
    HeldSourceColorReservation, SourceColorReservationReadContext, read_source_color_reservation,
)
from guided_source_color_staging_files import staging_path
from headless.container_policy import DockerRuntime
from headless.grade_batch_cleanup import GradeBatchCleanupContext, reconcile_grade_batch
from headless.grade_launch_files import directory_identity


def _method(value: object) -> tuple:
    """Hold bound callback identities without unstable temporary bound-method IDs."""
    return (id(getattr(value, "__self__", None)), id(getattr(value, "__func__", value)))


def _context(value: SourceColorCleanupContext) -> tuple:
    """Read original fields directly; context methods never supply their own proof."""
    if type(value) is not SourceColorCleanupContext or type(value.opening) is not HeldOpeningClaim \
            or type(value.clock) is not OpeningExecutionClock or type(value.runtime) is not DockerRuntime \
            or type(value.clock.end) not in (int, float) or not math.isfinite(value.clock.end) \
            or type(value.clock.events) is not list or not callable(value.guard):
        raise ValueError("source color cleanup requires actual original caller controls")
    opening, clock, runtime = value.opening, value.clock, value.runtime
    if getattr(clock.phase, "__self__", None) is not clock or getattr(clock.phase, "__func__", None) is not OpeningExecutionClock.phase \
            or getattr(clock.remaining, "__self__", None) is not clock \
            or getattr(clock.remaining, "__func__", None) is not OpeningExecutionClock.remaining:
        raise ValueError("source color cleanup requires actual original clock methods")
    return (id(value), id(opening), str(staging_path(opening.path)), hash_value(opening.sha256), id(opening.value), opening.value,
            str(staging_path(value.producer_dir)), str(staging_path(value.resource_dir)), hash_value(value.source_color_hash),
            id(clock), clock.end, id(clock.events), _method(clock.phase), _method(clock.remaining),
            id(runtime), runtime, id(runtime.approval), str(staging_path(value.config_dir)), id(value.guard))


@dataclass(frozen=True)
class SourceColorCleanupContext:
    """Actual original protected cleanup clock and already-authenticated caller controls."""

    opening: HeldOpeningClaim
    producer_dir: Path
    resource_dir: Path
    source_color_hash: str
    clock: OpeningExecutionClock
    runtime: DockerRuntime
    config_dir: Path
    guard: Callable[[], None]
    _original: object = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Capture original metadata before any operation or caller callback."""
        object.__setattr__(self, "_original", hold_read_metadata(_context(self)))


def _runtime_matches(context: SourceColorCleanupContext) -> None:
    """Match actual four control strings, without discovering or admitting Docker."""
    expected, runtime = context.opening.value["runtime"], context.runtime
    for actual, key in ((runtime.docker, "dockerPath"), (runtime.socket, "dockerSocketPath"),
                        (runtime.image_id, "imageId"), (runtime.user_id, "userId")):
        if type(actual) is not str or type(expected[key]) is not str or actual != expected[key]:
            raise RuntimeError("source color cleanup runtime differs from original claim")


def _reservation(value: HeldSourceColorReservation | None) -> tuple | None:
    """Detach actual reader-return metadata before any later phase callback."""
    if value is None:
        return None
    if type(value) is not HeldSourceColorReservation:
        raise RuntimeError("source color cleanup requires the actual held reservation read")
    return (id(value), id(value.value), value.value, id(value.container_names), value.container_names, value.size_bytes)


class PreparedSourceColorCleanup:
    """One live explicit reconciliation, not reconstructible serialized cleanup authority."""

    def __init__(self) -> None:
        """Only the internal original-reference preparation function creates this object."""
        raise TypeError("source color cleanup requires prepare_opening_source_color_cleanup")

    def _pure(self) -> None:
        """Finish metadata/time checks without filesystem work or external callbacks."""
        if id(self) != self.identity or self.context._original is not self.context_origin \
                or not same_read_metadata(_context(self.context), self.context_origin) \
                or not same_read_metadata((id(self.reference), str(self.reference[0]), self.reference[1]), self.reference_binding):
            raise RuntimeError("source color cleanup original context/reference changed")
        if not same_read_metadata(_reservation(self.held), self.held_binding):
            raise RuntimeError("source color cleanup actual reservation return changed")
        execution = (self.end, id(self.events), _method(self.phase), id(self.runtime), str(self.config_dir), id(self.callback))
        if not same_read_metadata(execution, self.execution_binding) \
                or not same_read_metadata(self.config_identity, self.config_binding):
            raise RuntimeError("source color cleanup original execution/config changed")
        require_time(self.end)

    def _config(self) -> None:
        """Hold existing private config ancestry inside a caller-owned protected phase."""
        current = directory_identity(self.config_dir)
        if self.config_identity is None:
            info = self.config_dir.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
                raise RuntimeError("source color cleanup config is not existing private owned metadata")
            self.config_identity = current
            self.config_binding = hold_read_metadata(current)
        if current != self.config_identity:
            raise RuntimeError("source color cleanup original config ancestry changed")

    def _source_guard(self) -> None:
        """First called only after the cold reader captured all three metadata identities."""
        self._pure()
        self._config()
        self.callback()
        self._pure()
        self._config()
        self._pure()

    def _read(self) -> None:
        """Capture actual reader output inside the original protected read phase."""
        context = self.context
        reading = SourceColorReservationReadContext(context.opening, context.producer_dir, context.resource_dir,
                                                    context.source_color_hash, self.end, self._source_guard)
        self.held = read_source_color_reservation(self.reference, reading)
        self.held_binding = hold_read_metadata(_reservation(self.held))
        self._pure()

    def _batch_guard(self) -> None:
        """Reuse original context/reservation/config under the coordinator's own timer."""
        self._pure()
        self.held.assert_current()
        self._pure()

    def _reconcile(self) -> tuple[dict, object]:
        """Record actual coordinator failure/success without nesting a phase wall timer."""
        started = time.monotonic()
        event = {"stage": "reconcile-source-color-batch", "status": "failed"}
        try:
            self._pure()
            if self.started:
                raise RuntimeError("source color cleanup cannot repeat an original reconciliation")
            self.started = True
            controls = GradeBatchCleanupContext(self.runtime, self.config_dir, self.end, self._batch_guard)
            result = reconcile_grade_batch(self.held.container_names, controls)
            binding = hold_read_metadata((id(result), result))
            self._pure()
            if type(result) is not dict or result.get("cleanupVerified") is not True \
                    or tuple(row["containerName"] for row in result["jobs"]) != self.held.container_names:
                raise RuntimeError("source color cleanup actual batch result is not verified")
            event["status"] = "complete"
            return result, binding
        except Exception as error:
            event["error"] = str(error)[:2000]
            raise
        finally:
            event["elapsedMs"] = round((time.monotonic() - started) * 1000)
            self.events.append(event)

    def reconcile(self) -> dict:
        """Call only after original graphics/control checks and actual TS settlement."""
        batch, binding = self._reconcile()
        self.phase("source-color-reservation-after", self.held.assert_current)
        self._pure()
        if not same_read_metadata((id(batch), batch), binding):
            raise RuntimeError("source color cleanup actual batch result changed")
        return {"reservation": {"path": str(self.reference[0]), "sha256": self.reference[1], "sizeBytes": self.held.size_bytes},
                "sourceColorHash": self.context.source_color_hash, "batch": batch}


def prepare_opening_source_color_cleanup(reference: tuple[Path, str], context: SourceColorCleanupContext) -> PreparedSourceColorCleanup:
    """Hold original reservation first; caller performs graphics/controls before reconcile."""
    if type(context) is not SourceColorCleanupContext or not same_read_metadata(_context(context), context._original):
        raise ValueError("source color cleanup original context changed before preparation")
    if type(reference) is not tuple or len(reference) != 2:
        raise ValueError("source color cleanup requires one original raw reservation reference")
    staging_path(reference[0])
    hash_value(reference[1])
    _runtime_matches(context)
    value = object.__new__(PreparedSourceColorCleanup)
    value.identity, value.context, value.context_origin = id(value), context, context._original
    value.reference = reference
    value.reference_binding = hold_read_metadata((id(reference), str(reference[0]), reference[1]))
    value.end, value.events, value.phase = context.clock.end, context.clock.events, context.clock.phase
    value.runtime, value.config_dir, value.callback = context.runtime, context.config_dir, context.guard
    value.execution_binding = hold_read_metadata((value.end, id(value.events), _method(value.phase), id(value.runtime),
                                                   str(value.config_dir), id(value.callback)))
    value.config_identity, value.held, value.started = None, None, False
    value.config_binding = hold_read_metadata(None)
    value.held_binding = hold_read_metadata(None)
    value._pure()
    if require_time(value.end) > 300:
        raise ValueError("source color cleanup requires original protected remainder at most300 seconds")
    value.phase("source-color-reservation-read", value._read)
    value._pure()
    return value
