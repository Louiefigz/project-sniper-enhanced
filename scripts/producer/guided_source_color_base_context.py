"""Internal longform source-identity lifetime, not a persisted base proof.

The actual completed V1 holder and its original opening clock are retained
through ordinary lossy picture commands. No renderer/registry/readback fence
is released, and short/manual-reframe transport remains unsupported here.
"""
from __future__ import annotations

from copy import deepcopy
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from audio.render_audio_authority import SOURCE_FLOAT_POLICY_V2
from audio.render_audio_bus import SourceAudioBus
from guided_opening_execution import OpeningExecutionClock
from guided_opening_frames import _profile
from guided_opening_inputs import OpeningInputs
from guided_media_profile import OPENING_PROFILE
from guided_presenter_read_fingerprint import hold_read_metadata, same_read_metadata
from guided_source_color_base import HeldBt709BaseIdentity, _unchanged as color_unchanged
from guided_source_color_consumption import SourceColorPictureConsumption
from guided_source_color_consumption_publication import publication_record
from guided_source_color_opening import _OpeningColorRead
from motion.recompose import requires_recompose


def _opening(context: SourceColorBaseContext) -> _OpeningColorRead:
    """Require the same original opening owner, not an equal fresh clock."""
    if type(context.inputs) is not OpeningInputs or type(context.clock) is not OpeningExecutionClock \
            or type(context.source_color) is not HeldBt709BaseIdentity:
        raise RuntimeError("source-color base requires actual inputs, clock and identity holder")
    preparation = context.source_color.batch.preparation
    callback = preparation.context.guard
    owner = getattr(callback, "__self__", None)
    if type(owner) is not _OpeningColorRead or getattr(callback, "__func__", None) is not _OpeningColorRead.persistent \
            or owner.clock is not context.clock or owner.context.inputs is not context.inputs \
            or context.source_color.inputs is not context.inputs or context.guard is not owner.callback:
        raise RuntimeError("source-color base requires the same original opening inputs/clock/guard")
    if set(vars(context.clock)) != {"end", "events"}:
        raise RuntimeError("source-color base original clock methods changed")
    return owner


def _arguments(context: SourceColorBaseContext) -> tuple:
    """Hold complete original metadata and identities before any caller callback."""
    inputs, clock = context.inputs, context.clock
    owner = _opening(context)
    return (id(context), id(inputs), str(inputs.path), inputs.sha256, id(inputs.value), inputs.value,
            id(inputs.documents), inputs.documents, id(inputs.verified_media), id(clock), clock.end,
            id(clock.events), id(context.source_color), id(context.source_color._origin),
            id(context.guard), id(owner), id(getattr(context, "_consumption", None)))


def assert_source_color_plan(inputs: OpeningInputs) -> None:
    """Pure early refusal before source observations; preserve existing profile/registry gates."""
    if type(inputs) is not OpeningInputs:
        raise RuntimeError("source-color plan requires original opening input metadata")
    plan = inputs.documents["candidatePlan"]
    if plan.get("target", {}).get("mode") != "longform" \
            or (plan.get("reframe") or {}) not in ({}, {"strategy": "none"}):
        raise RuntimeError("source-color base currently requires longform without reframe")
    _profile(plan, inputs.value.get("profile", OPENING_PROFILE))
    if any(requires_recompose(row) for row in plan.get("graphicsTrack") or []):
        raise RuntimeError("source-color base has not recorded graphic-derived rail recompose")


@dataclass(frozen=True)
class SourceColorBaseContext:
    """Actual internal source-only lifetime; no presenter owner is fabricated."""

    inputs: OpeningInputs
    clock: OpeningExecutionClock
    source_color: HeldBt709BaseIdentity
    guard: Callable[[], None]
    _binding: object = field(init=False, repr=False)
    _color_origin: tuple = field(init=False, repr=False)
    _consumption: SourceColorPictureConsumption = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Capture original arguments before profile checks or source callbacks."""
        original = hold_read_metadata(_arguments(self))
        consumption = SourceColorPictureConsumption(self.source_color, self.guard)
        if not same_read_metadata(_arguments(self), original):
            raise RuntimeError("source-color base original arguments changed during recorder capture")
        object.__setattr__(self, "_consumption", consumption)
        object.__setattr__(self, "_binding", hold_read_metadata(_arguments(self)))
        object.__setattr__(self, "_color_origin", self.source_color._origin)
        assert_source_color_plan(self.inputs)
        self.assert_current()

    def assert_current(self) -> None:
        """Use the actual persistent holder, then close original metadata and time."""
        SourceColorBaseContext.assert_metadata(self)
        HeldBt709BaseIdentity.assert_current(self.source_color)
        SourceColorBaseContext.assert_metadata(self)

    def assert_metadata(self) -> None:
        """Callback-free final comparison never refreshes source or clock identity."""
        if not same_read_metadata(_arguments(self), self._binding):
            raise RuntimeError("source-color base original arguments changed")
        color_unchanged(self.source_color, self._color_origin)
        SourceColorPictureConsumption.belongs_to(self._consumption, self.source_color, self.guard)
        OpeningExecutionClock.remaining(self.clock)

    @property
    def consumption(self) -> SourceColorPictureConsumption:
        """Expose the same private code capability without granting receipt authority."""
        SourceColorBaseContext.assert_metadata(self)
        return self._consumption

    def consumption_record(self) -> dict:
        """Require every actual encode/proof hook before a source-only preparation returns."""
        SourceColorBaseContext.assert_current(self)
        result = SourceColorPictureConsumption.record(self._consumption)
        result["basePublication"] = publication_record(self._consumption)
        SourceColorBaseContext.assert_metadata(self)
        return result


def _render_fields(ctx: Any) -> tuple:
    """Hold only original command inputs, not expected trace/audio stage updates."""
    return (id(ctx), id(ctx.plan), ctx.plan, id(ctx.manifest), ctx.manifest,
            id(ctx.source_color_base), id(ctx.presenter_base), ctx.plan_path, ctx.skip_graphics,
            ctx.resume, ctx.audio_clock_policy, ctx.out_dir, ctx.work_dir, ctx.producer_dir)


def require_source_color_base(ctx: Any) -> None:
    """Preserve the absent-context path and reject mismatched source-only commands."""
    context = getattr(ctx, "source_color_base", None)
    if context is None:
        return
    if type(context) is not SourceColorBaseContext or getattr(ctx, "presenter_base", None) is not None:
        raise RuntimeError("source-color base requires its actual separate source-only context")
    original = hold_read_metadata(_render_fields(ctx))
    SourceColorBaseContext.assert_current(context)
    refs, documents = context.inputs.value["documents"], context.inputs.documents
    manifest = deepcopy(documents["manifest"])
    manifest["_path"] = refs["manifest"]["path"]
    if ctx.skip_graphics is not True or ctx.resume is not False or ctx.audio_clock_policy != SOURCE_FLOAT_POLICY_V2 \
            or ctx.plan_path != refs["candidatePlan"]["path"] \
            or not same_read_metadata(ctx.plan, hold_read_metadata(documents["candidatePlan"])) \
            or not same_read_metadata(ctx.manifest, hold_read_metadata(manifest)):
        raise RuntimeError("source-color base differs from original fresh candidate/manifest command")
    if not same_read_metadata(_render_fields(ctx), original):
        raise RuntimeError("source-color base render arguments changed during callback")
    SourceColorBaseContext.assert_metadata(context)


def hold_source_color_base_guard(ctx: Any) -> Callable[[], None] | None:
    """Transport one immutable source-only command lifetime through actual encodes."""
    if getattr(ctx, "source_color_base", None) is None:
        return None
    original = hold_read_metadata(_render_fields(ctx))
    context = ctx.source_color_base

    def check() -> None:
        """Reject original command replacement before and after each lossy boundary."""
        if not same_read_metadata(_render_fields(ctx), original):
            raise RuntimeError("source-color base original render command changed")
        require_source_color_base(ctx)
        if not same_read_metadata(_render_fields(ctx), original):
            raise RuntimeError("source-color base original render command changed")
        SourceColorBaseContext.assert_metadata(context)

    check()
    return check


def source_color_stage(guard: Callable[[], None] | None, operation: Callable,
                       arguments: tuple) -> Any:
    """Retain one render-entry guard around stages; None preserves old arguments."""
    if guard is not None:
        guard()
    result = operation(*arguments)
    if guard is not None:
        guard()
    return result


def source_color_channels(ctx: Any, mezz: str) -> bool:
    """Use the already-built source float bus's exact source-channel correction.

    The ordinary bus derives stereo filters from the cut's original channel
    receipts. Its audio, not intermediate mezzanine AAC, reaches the master.
    """
    if getattr(ctx, "source_color_base", None) is None:
        return False
    bus = ctx.source_audio_bus
    if type(bus) is not SourceAudioBus or bus.admission is not ctx.audio_admission \
            or bus.admission.policy != SOURCE_FLOAT_POLICY_V2:
        raise RuntimeError("source-color channel handoff requires its actual original source-float bus")
    original = hold_read_metadata(bus)
    guard = hold_source_color_base_guard(ctx)
    guard()
    if ctx.source_audio_bus is not bus or ctx.audio_admission is not bus.admission \
            or not same_read_metadata(bus, original):
        raise RuntimeError("source-color original source-float channel bus changed")
    ctx.bootstrap_trace.append({"stage": "audio_channels", "executed": False,
        "status": "not-required", "input": mezz, "output": mezz,
        "reason": "source-float bus applies original source channel receipts"})
    return True
