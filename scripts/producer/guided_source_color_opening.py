"""Internal explicit opening source observations, not public rendering authority.

The caller authenticates the sidecar reference, original opening inputs/claim,
namespace, source/code guard and original clock. This composes existing readers
and the actual sequential owner; it acquires no lease, renews no budget, and
does not release the presenter registry/base-color or approval gates. Completed
data retains only the persistent caller lifetime, never the retired reservation.
"""
from __future__ import annotations

import math
import signal
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from color.deadline import require_time
from guided_opening_claim import HeldOpeningClaim
from guided_opening_execution import OpeningExecutionClock
from guided_opening_inputs import OpeningInputs
from guided_presenter_read_fingerprint import hold_read_metadata, same_read_metadata
from guided_source_color_batch import PreparedSourceColorBatch, SourceColorJobRef, prepare_source_color_batch
from guided_source_color_execution import (
    CompletedSourceColorBatch, SourceColorExecutionError, _unchanged as completed_unchanged, run_source_color_batch,
)
from guided_source_color_hold import HeldSourceColorPreparation, hold_source_color_preparation
from guided_source_color_preparation import SourceColorParentRefs, SourceColorPreparationContext
from guided_source_color_staging_files import check_staging_file, staging_path
from guided_source_color_staging_read import (
    HeldSourceColorStaging, SourceColorStagingReadContext, _held_current, _unchanged as staging_unchanged,
    read_source_color_staging,
)
from headless.grade_launch_files import HeldLaunchFile


@dataclass(frozen=True)
class SourceColorOpeningAuthority:
    """Borrow authenticated namespaces and persistent project/source/code checks."""

    producer_dir: Path
    resource_dir: Path
    guard: Callable[[], None]


@dataclass(frozen=True)
class SourceColorOpeningContext:
    """Retain actual original input, claim, clock and caller authority objects."""

    inputs: OpeningInputs
    opening: HeldOpeningClaim
    clock: OpeningExecutionClock
    authority: SourceColorOpeningAuthority


class SourceColorOpeningError(RuntimeError):
    """Keep setup/work diagnostics without exposing partial observation objects."""

    def __init__(self, cause: Exception, stage: str, elapsed_ms: int, timings: tuple = ()) -> None:
        """Preserve the actual batch failure timing tuple and exception cause."""
        super().__init__(f"opening source color {stage} failed: {type(cause).__name__}: {cause}"[:3000])
        self.stage, self.elapsed_ms = stage, elapsed_ms
        self.timings = cause.timings if type(cause) is SourceColorExecutionError else timings


def _arguments(context: SourceColorOpeningContext) -> tuple:
    """Capture exact caller fields before any callback, reader or phase timer."""
    if type(context) is not SourceColorOpeningContext or type(context.inputs) is not OpeningInputs \
            or type(context.opening) is not HeldOpeningClaim or type(context.clock) is not OpeningExecutionClock \
            or type(context.authority) is not SourceColorOpeningAuthority:
        raise ValueError("opening source color requires actual original context objects")
    authority, clock = context.authority, context.clock
    if not callable(authority.guard) or type(clock.end) not in (int, float) or not math.isfinite(clock.end) \
            or type(clock.events) is not list or set(vars(clock)) != {"end", "events"}:
        raise ValueError("opening source color original clock/guard is malformed")
    inputs, opening = context.inputs, context.opening
    return (id(context), id(inputs), str(inputs.path), inputs.sha256, id(inputs.value), inputs.value,
            id(inputs.documents), inputs.documents, id(inputs.verified_media), id(opening), str(opening.path),
            opening.sha256, id(opening.value), opening.value, id(clock), type(clock.end).__name__, clock.end,
            id(clock.events), id(authority), str(staging_path(authority.producer_dir)),
            str(staging_path(authority.resource_dir)), id(authority.guard))


class _OpeningColorRead:
    """Original persistent lifetime, separate from the transient active reservation."""

    def __init__(self, reference: tuple[Path, str], context: SourceColorOpeningContext) -> None:
        """Hold original metadata before the first external callback or new owner."""
        self.context, self.reference = context, reference
        self.original = hold_read_metadata(_arguments(context))
        self.clock, self.deadline = context.clock, context.clock.end
        self.callback, self.events = context.authority.guard, context.clock.events
        self.staging, self.staging_origin = None, None
        self.stage = "staging"
        if require_time(self.deadline) > 1500:
            raise ValueError("opening source color cannot exceed the original25-minute budget")
        if signal.getitimer(signal.ITIMER_REAL)[0] != 0:
            raise RuntimeError("opening source color must run outside another phase timer")

    def unchanged(self) -> None:
        """Do not rebaseline changed inputs, callbacks, clock fields or prior events."""
        if not same_read_metadata(_arguments(self.context), self.original) \
                or self.clock is not self.context.clock or self.deadline != self.context.clock.end \
                or self.callback is not self.context.authority.guard or self.events is not self.context.clock.events:
            raise RuntimeError("opening source color original input/claim/clock/guard/events changed")

    def persistent(self) -> None:
        """Guard retained data without consulting the transient resource reservation."""
        self.unchanged()
        require_time(self.deadline)
        self.callback()
        self.unchanged()
        require_time(self.deadline)

    def transient(self) -> None:
        """Check the live reservation only while entering existing grade work."""
        self.persistent()
        self.staging.assert_current()
        self.reservation_current()

    def reservation_current(self) -> None:
        """Finish with original raw-file/metadata checks, without another callback."""
        self.unchanged()
        held = self.staging
        _held_current(held, self.staging_origin)
        staging_unchanged(held._read)
        for row in (*held._read.files, *(item[0] for item in held._read.loaded)):
            check_staging_file(row)
        staging_unchanged(held._read)
        _held_current(held, self.staging_origin)
        self.unchanged()
        require_time(self.deadline)


def _event(read: _OpeningColorRead, operation: Callable[[], Any]) -> Any:
    """Record actual batch work without placing a timer over mandatory cleanup."""
    started, event = time.monotonic(), {"stage": "source-color-observation", "status": "failed"}
    try:
        result = operation()
        event["status"] = "complete"
        return result
    except Exception as error:
        event["error"] = str(error)
        raise
    finally:
        event["elapsedMs"] = round((time.monotonic() - started) * 1000)
        read.events.append(event)


def _phase(read: _OpeningColorRead, name: str, operation: Callable[[], Any]) -> Any:
    """Time metadata under the original hard cutoff; keep native batch unwrapped."""
    read.stage = name
    before = hold_read_metadata(read.events)

    def guarded() -> Any:
        """Let staging capture its four original files before the FIRST callback."""
        read.unchanged()
        require_time(read.deadline)
        if name != "staging":
            read.persistent()
        return operation()

    try:
        if name == "observation":
            return _event(read, guarded)
        return OpeningExecutionClock.phase(read.clock, f"source-color-{name}", guarded)
    finally:
        # Only the exact phase's final append is permitted, not an event rebaseline.
        if not same_read_metadata(read.events[:-1], before):
            raise RuntimeError("opening source color original event history changed")
        read.unchanged()


def _staging(read: _OpeningColorRead) -> HeldSourceColorStaging:
    """Read the explicit authenticated sidecar with the same original caller clock."""
    context, authority = read.context, read.context.authority
    value = read_source_color_staging(read.reference, SourceColorStagingReadContext(
        context.inputs, context.opening, authority.producer_dir, authority.resource_dir, read.deadline, read.persistent))
    read.staging, read.staging_origin = value, value._origin
    read.reservation_current()
    return value


def _prepare(read: _OpeningColorRead) -> HeldSourceColorPreparation:
    """Prepare the exact all-source declaration under a resource-independent guard."""
    value = read.staging.value
    parents = SourceColorParentRefs(read.context.authority.producer_dir, value["expected"])
    context = SourceColorPreparationContext(parents, read.deadline, read.persistent)
    return hold_source_color_preparation(read.context.inputs, value["sourceColor"]["declarations"], context)


def _refs(read: _OpeningColorRead) -> tuple[SourceColorJobRef, ...]:
    """Use only authenticated staged jobs and their original raw preclaim references."""
    from headless.grade_launch_intent import OwnedGradeLaunch

    guard = read.transient
    return tuple(SourceColorJobRef(row["sourceId"], Path(row["input"]["path"]), row["input"]["sha256"],
                 OwnedGradeLaunch(Path(row["launchClaim"]["path"]), row["launchClaim"]["sha256"], read.deadline, guard))
                 for row in read.staging.value["jobs"])


def _finish(read: _OpeningColorRead, result: CompletedSourceColorBatch, original: tuple) -> CompletedSourceColorBatch:
    """Close all final callbacks against the actual batch and original reservation."""
    read.transient()
    result.assert_current()
    read.reservation_current()
    completed_unchanged(result, original)
    require_time(read.deadline)
    return result


def _preflight(read: _OpeningColorRead, preparation: HeldSourceColorPreparation) -> PreparedSourceColorBatch:
    """Join every staged raw ref to already-held batch files without reading again."""
    batch = prepare_source_color_batch(preparation, _refs(read))
    held = {str(row.path): row for row, _expected in batch._read.retained if type(row) is HeldLaunchFile}
    refs = tuple(row[key] for row in read.staging.value["jobs"] for key in ("input", "implementation", "launchClaim"))
    for ref in refs:
        row = held.get(ref["path"])
        if row is None or not same_read_metadata(ref, hold_read_metadata(
                {"path": str(row.path), "sha256": row.sha256, "sizeBytes": len(row.raw)})):
            raise RuntimeError("opening source color staged raw job reference differs from actual preflight")
    read.reservation_current()
    batch.assert_current()
    return batch


def observe_opening_source_colors(reference: tuple[Path, str],
                                  context: SourceColorOpeningContext) -> CompletedSourceColorBatch:
    """Return the SAME completed batch; no CLI activation, base render or approval."""
    started = time.monotonic()
    read = _OpeningColorRead(reference, context)
    timings = ()
    try:
        _phase(read, "staging", lambda: _staging(read))
        preparation = _phase(read, "preparation", lambda: _prepare(read))
        batch = _phase(read, "preflight", lambda: _preflight(read, preparation))
        result = _phase(read, "observation", lambda: run_source_color_batch(batch))
        original, timings = result._origin, result.timings
        result = _phase(read, "completion", lambda: _finish(read, result, original))
        completed_unchanged(result, original)
        read.unchanged()
        require_time(read.deadline)
        return result
    except Exception as error:
        raise SourceColorOpeningError(error, read.stage, round((time.monotonic() - started) * 1000), timings) from error
