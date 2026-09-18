"""Live selected-picture acquisition under an existing opening/body owner.

This context does not enable a profile, render, publish an execution receipt or
grant source/rights/quality approval. It consumes the original source owner's
ephemeral same-hash identities and keeps the separately pinned probe alive.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

from cut_preview_io import digest, real_directory
from guided_opening_inputs import OpeningInputs, closed, hash_value
from guided_presenter_capture_inputs import admit_observed_capture, capture_input_binding, capture_selection
from guided_presenter_execution import OwnedPresenterExecution
from guided_presenter_observation import observe_presenter_asset
from guided_presenter_probe_identity import (
    HeldPresenterProbeFile, PresenterObservationRuntime, PresenterProbeDeadline, PresenterProbePin,
)
from headless.external_media_verification import (
    SourceVerificationRuntime, VerifiedSnapshotIdentity, assert_verified_snapshots,
)
from headless.runtime_executable_pins import (
    PinnedExecutableV1, _recheck_path, close_pins, pin_executable, snapshot_for_pin, verify_pins,
)
from opening_prefix_contract import HeldPrefixInput, verify_held_input


@dataclass(frozen=True)
class PresenterCaptureContext:
    """Borrow declared tools, existing work directory, original clock and cheap guard."""

    tools: dict
    working_directory: str
    deadline: PresenterProbeDeadline
    guard: Callable[[], None]


def _tool_reference(pin: PinnedExecutableV1) -> HeldPresenterProbeFile:
    """Map named verified tool fields explicitly; tool wire order is not source order."""
    row = snapshot_for_pin(pin)
    identity = (row.device, row.inode, row.mode, row.uid, row.gid,
                row.link_count, row.size_bytes, row.mtime_ns, row.ctime_ns)
    return HeldPresenterProbeFile(row.path, row.sha256, row.size_bytes, identity)


class _CaptureLifetime:
    """Private live fence; neither a saved record nor a later context can renew it."""

    def __init__(self, inputs: OpeningInputs, context: PresenterCaptureContext) -> None:
        """Hold original arguments before any caller callback can modify them."""
        if (type(context) is not PresenterCaptureContext or not callable(context.guard)
                or not callable(getattr(context.deadline, "remaining", None))):
            raise RuntimeError("Presenter capture requires its original owner context")
        self.inputs, self.context = inputs, context
        self.binding = capture_input_binding(inputs)
        self.deadline, self.callback = context.deadline, context.guard
        self.directory, self.tools_binding = context.working_directory, digest(context.tools)
        self.captured = inputs.verified_media
        self.active, self.pin = True, None
        self.sources: tuple[VerifiedSnapshotIdentity, ...] = ()
        self.clock = SourceVerificationRuntime(self.deadline.remaining)

    def check(self) -> None:
        """Check original callbacks first, then exact metadata and final time, without source hashes."""
        if not self.active:
            raise RuntimeError("Presenter acquisition lifetime is closed")
        self.clock.check()
        self.callback()
        if (self.context.deadline is not self.deadline or self.context.guard is not self.callback
                or self.context.working_directory != self.directory
                or digest(self.context.tools) != self.tools_binding
                or capture_input_binding(self.inputs) != self.binding
                or self.inputs.verified_media is not self.captured):
            raise RuntimeError("Presenter original input/context changed during acquisition")
        parents = {Path(row.path).parent for row in self.sources}
        for parent in parents:
            real_directory(parent)
        assert_verified_snapshots(self.sources, self.clock)
        for parent in parents:
            real_directory(parent)
        if self.pin is not None:
            # Existing held-directory/FD recheck, deliberately not its full tool hash loop.
            _recheck_path(self.pin)
        self.clock.check()

    def acquire_tool(self, stack: ExitStack) -> HeldPresenterProbeFile:
        """Register cleanup immediately, then verify actual declared tool bytes once."""
        self.check()
        row = closed(self.context.tools.get("ffprobe"), {"path", "sha256"}, "presenter ffprobe")
        pin = pin_executable(row["path"], "presenter ffprobe", hash_value(row["sha256"]))
        stack.callback(close_pins, (pin,))
        self.pin = pin
        verify_pins((pin,))
        self.check()
        return _tool_reference(pin)

    def finish(self) -> None:
        """Recheck final tool bytes then original inputs and time before normal return."""
        self.check()
        if self.pin is not None:
            verify_pins((self.pin,))
        self.check()


def _acquire(lifetime: _CaptureLifetime, stack: ExitStack) -> OwnedPresenterExecution | None:
    """Reject invalid selections before tools; reuse one actual observation per unique asset."""
    lifetime.check()
    selection = capture_selection(lifetime.inputs)
    lifetime.check()
    if selection is None:
        return None
    # Retain all original source identities, including the base, without another hash.
    lifetime.sources = lifetime.captured.snapshots
    lifetime.check()
    tool = lifetime.acquire_tool(stack)
    runtime = PresenterObservationRuntime(tool, lifetime.directory, lifetime.deadline, lifetime.check)
    # These descriptor guards span the whole live owner, not merely each probe call.
    pins = [stack.enter_context(PresenterProbePin(row, runtime)) for row in selection.sources]
    stack.enter_context(PresenterProbePin(tool, runtime, True))
    first = {row.admission.snapshot_path: row for row in reversed(selection.selected)}
    observed = tuple(observe_presenter_asset(first[pin.value.path], pin.value,
                     selection.frame_rate, runtime) for pin in pins)
    admit_observed_capture(lifetime.inputs, selection.selected, observed)
    owner = OwnedPresenterExecution(selection.selected, observed, selection.frame_rate, runtime)
    owner.assert_plan(lifetime.inputs.documents["candidatePlan"])
    lifetime.check()
    return owner


@contextmanager
def acquire_presenter_execution(inputs: OpeningInputs,
                                context: PresenterCaptureContext) -> Iterator[OwnedPresenterExecution | None]:
    """Fence returned owners at exit and close all pins on success, failure or cancellation."""
    lifetime = _CaptureLifetime(inputs, context)
    with ExitStack() as stack:
        try:
            owner = _acquire(lifetime, stack)
            yield owner
            lifetime.finish()
        finally:
            lifetime.active = False
    lifetime.clock.check()  # Closing pins cannot turn an expired context into success.


@contextmanager
def acquire_presenter_read_context(inputs: OpeningInputs, base: HeldPrefixInput,
                                   context: PresenterCaptureContext) -> Iterator:
    """Hold source/tool/base identities for data-only receipt reading; never decode.

    The base's supplied SHA has no same-read stat, so one original-budget full
    base hash supplies that identity. Source snapshots reuse initial admission;
    the actual probe is independently pinned and checked at both boundaries.
    """
    from guided_presenter_probe_identity import presenter_stat_identity
    from guided_presenter_read import PresenterReadContext

    lifetime = _CaptureLifetime(inputs, context)
    if capture_selection(inputs) is None:
        raise RuntimeError("presenter read acquisition requires an actual selected presenter class")
    lifetime.sources = lifetime.captured.snapshots
    with ExitStack() as stack:
        try:
            tool = lifetime.acquire_tool(stack)
            identity = verify_held_input(base, lifetime.deadline)

            def check() -> None:
                """Check original owner/time first, then the actual same-read base stat."""
                lifetime.check()
                real_directory(Path(base.path).parent)
                if presenter_stat_identity(Path(base.path).lstat()) != identity:
                    raise RuntimeError("presenter reader original held base changed")

            check()
            yield PresenterReadContext(inputs, base, tool, check)
            lifetime.finish()
            check()
        finally:
            lifetime.active = False
    lifetime.clock.check()
