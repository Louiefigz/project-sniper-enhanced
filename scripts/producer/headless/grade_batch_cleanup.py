"""Bounded exact-name grade cleanup, never reservation or process-stop authority.

The caller must authenticate the complete reservation and prove all original
outer/nested workers and Docker launch clients settled BEFORE calling. Names
share one observed-absence interval under the SAME protected cutoff. This owns
one wall timer and must not run inside another work/cleanup timer. No source
bytes, decoder, resource discovery, lease release or work authorization occurs.
"""
from __future__ import annotations

import math
import os
import signal
import stat
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from color.deadline import require_time, wall_budget
from guided_presenter_read_fingerprint import hold_read_metadata, same_read_metadata
from headless.container_policy import (
    DockerRuntime, _ABORT_POLL_SECONDS, _ABORT_STABLE_SECONDS, _force_remove, _is_absent,
)
from headless.grade_launch_files import directory_identity


def _context_binding(context: GradeBatchCleanupContext) -> tuple:
    """Read fields directly; instance methods never provide validation authority."""
    fields = {"runtime", "config_dir", "deadline", "guard", "_original"}
    return (id(context), id(context.runtime), context.runtime, type(context.config_dir).__name__, str(context.config_dir),
            type(context.deadline).__name__, context.deadline, id(context.guard), tuple(sorted(set(vars(context)) - fields)))


@dataclass(frozen=True)
class GradeBatchCleanupContext:
    """Actual caller cleanup controls, not a deserialized claim or new work clock."""

    runtime: DockerRuntime
    config_dir: Path
    deadline: float
    guard: Callable[[], None]
    _original: object = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Bind original controls before any callback; filesystem checks happen at entry."""
        if type(self.runtime) is not DockerRuntime or type(self.config_dir) is not type(Path()) \
                or self.config_dir.anchor != "/" or ".." in self.config_dir.parts \
                or type(self.deadline) not in (int, float) or not math.isfinite(self.deadline) \
                or not callable(self.guard):
            raise ValueError("grade batch cleanup requires exact caller controls")
        object.__setattr__(self, "_original", hold_read_metadata(_context_binding(self)))

    def binding(self) -> tuple:
        """Expose metadata for inspection only; validation never dispatches this method."""
        return _context_binding(self)


class GradeBatchCleanupError(RuntimeError):
    """Detached partial diagnostics, never aggregate cleanup success or release power."""

    def __init__(self, cause: Exception, diagnostics: dict) -> None:
        """Keep original observations when a guard, daemon operation or cutoff fails."""
        super().__init__(f"grade batch cleanup remains unverified: {type(cause).__name__}: {cause}"[:2000])
        self.diagnostics = diagnostics


def _names(value: tuple[str, ...]) -> None:
    """Only complete caller-selected UUIDv4 grade names; never patterns or discovery."""
    if type(value) is not tuple or not 1 <= len(value) <= 128 or len(set(value)) != len(value):
        raise ValueError("grade batch cleanup requires 1..128 ordered unique names")
    prefix = "sniper-grade-observation-"
    for name in value:
        if type(name) is not str or len(name) != len(prefix) + 32 or not name.startswith(prefix):
            raise ValueError("grade batch cleanup name is not an exact grade reservation")
        token = name[len(prefix):]
        job = UUID(hex=token)
        if job.version != 4 or job.hex != token:
            raise ValueError("grade batch cleanup name is not canonical UUIDv4")


def _state_binding(state: _Cleanup) -> tuple:
    """Read private state and original context without replaceable binding dispatch."""
    return (id(state.names), state.names, id(state.context), _context_binding(state.context),
            type(state.deadline).__name__, state.deadline)


def _controls_unchanged(state: _Cleanup) -> None:
    """Reject original-control substitutions without filesystem work or callbacks."""
    if state.context._original is not state.context_origin or not same_read_metadata(_state_binding(state), state.original):
        raise RuntimeError("grade batch cleanup original controls changed")


class _Cleanup:
    """One private original context, complete inventory and partial observation ledger."""

    def __init__(self, names: tuple[str, ...], context: GradeBatchCleanupContext) -> None:
        """Validate pure entry fields and prepare diagnostics before protected setup."""
        _names(names)
        if type(context) is not GradeBatchCleanupContext or not same_read_metadata(_context_binding(context), context._original):
            raise ValueError("grade batch cleanup original context changed")
        if signal.getitimer(signal.ITIMER_REAL)[0] != 0:
            raise RuntimeError("grade batch cleanup cannot replace an active wall timer")
        self.started = time.monotonic()
        if not 0 < context.deadline - self.started <= 300:
            raise ValueError("grade batch cleanup requires the original protected remainder at most300 seconds")
        self.names, self.context, self.deadline = names, context, context.deadline
        self.original, self.context_origin = hold_read_metadata(_state_binding(self)), context._original
        self.directories = None
        self.rows = [{"containerName": name, "inspections": 0, "removalAttempts": 0, "successfulRemovalResponses": 0,
                      "lastObservation": "not-observed", "canonicalAbsenceProved": False} for name in names]
        self.passes, self.stable_since = 0, None

    def prepare(self) -> None:
        """Capture actual config ancestry inside the one original protected timer."""
        _controls_unchanged(self)
        require_time(self.deadline)
        self.directories = directory_identity(self.context.config_dir)
        info = self.context.config_dir.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise RuntimeError("grade batch cleanup config must be private and owned")
        self.unchanged()

    def unchanged(self) -> None:
        """Check metadata after the final callback without adopting a replacement."""
        _controls_unchanged(self)
        if directory_identity(self.context.config_dir) != self.directories:
            raise RuntimeError("grade batch cleanup original config ancestry changed")
        _controls_unchanged(self)
        require_time(self.deadline)

    def check(self) -> None:
        """Use only the caller's cleanup guard under its unchanged protected cutoff."""
        self.unchanged()
        self.context.guard()
        self.unchanged()

    def inspect(self, row: dict) -> bool | None:
        """Reuse canonical same-daemon absence semantics with exact original names."""
        self.check()
        row["inspections"] += 1
        result = _is_absent(self.context.runtime, str(self.context.config_dir), row["containerName"])
        row["lastObservation"] = "absent" if result is True else "present" if result is False else "unknown"
        self.check()
        if result is not True and result is not False and result is not None:
            raise RuntimeError("grade batch cleanup absence primitive returned malformed evidence")
        return result

    def remove(self, row: dict) -> bool:
        """A removal response alone is never canonical absence proof."""
        self.check()
        row["removalAttempts"] += 1
        result = _force_remove(self.context.runtime, str(self.context.config_dir), row["containerName"])
        if type(result) is not bool:
            raise RuntimeError("grade batch cleanup removal primitive returned malformed evidence")
        row["successfulRemovalResponses"] += int(result)
        self.check()
        return result

    def sweep(self) -> tuple[bool, bool]:
        """Every pass checks and removes every reserved name, including absent attempts."""
        absent, activity = True, False
        for row in self.rows:
            before = self.inspect(row)
            self.remove(row)
            after = self.inspect(row)
            absent = absent and after is True
            activity = activity or before is not True or after is not True
        self.passes += 1
        self.check()
        return absent, activity

    def report(self, complete: bool) -> dict:
        """Copy bounded per-name observations; failure never proves the complete set absent."""
        now = time.monotonic()
        stable = 0 if self.stable_since is None else max(0, round((now - self.stable_since) * 1000))
        return {"schemaVersion": 1, "kind": "grade-batch-cleanup-result",
                "scope": "reserved-name-cleanup-not-process-settlement-work-or-approval", "cleanupVerified": complete,
                "elapsedMs": max(0, round((now - self.started) * 1000)), "stableAbsenceMs": stable,
                "passes": self.passes, "jobs": [{**row, "canonicalAbsenceProved": complete} for row in self.rows]}


def _complete_pass(state: _Cleanup) -> bool:
    """Reset one shared interval on any uncertainty and require an extra complete sweep."""
    absent, activity = state.sweep()
    now = time.monotonic()
    if not absent:
        state.stable_since = None
    elif activity or state.stable_since is None:
        state.stable_since = now
    if state.stable_since is not None and now - state.stable_since >= _ABORT_STABLE_SECONDS:
        final_absent, final_activity = state.sweep()
        if final_absent and not final_activity:
            return True
        state.stable_since = time.monotonic() if final_absent else None
    return False


def _reconcile(state: _Cleanup) -> None:
    """All names share the caller's single interval and absolute protected deadline."""
    while not _complete_pass(state):
        state.check()
        time.sleep(min(_ABORT_POLL_SECONDS, require_time(state.deadline)))


def _protected_reconcile(state: _Cleanup) -> None:
    """Defer only the existing USR1 cancellation through actual resource reconciliation."""
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGUSR1})
    try:
        state.prepare()
        state.check()
        _reconcile(state)
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)


def reconcile_grade_batch(names: tuple[str, ...], context: GradeBatchCleanupContext) -> dict:
    """Reconcile authenticated reserved names only after actual worker/client settlement."""
    state = _Cleanup(names, context)
    try:
        with wall_budget(state.deadline):
            _protected_reconcile(state)
            state.unchanged()
            result = state.report(True)
            state.unchanged()
        _controls_unchanged(state)
        require_time(state.deadline)
        return result
    except Exception as error:
        raise GradeBatchCleanupError(error, state.report(False)) from error
