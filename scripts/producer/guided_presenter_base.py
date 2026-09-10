"""Internal presenter base fences with optional actual all-source BT709 evidence.

Selected presentation observations never qualify talking-source color. The
default still refuses; only an actual separate V1 identity holder can satisfy
that one internal prerequisite. No public registry, native qualification, output
receipt, color conversion or approval is created, and no plan field is removed.
"""
from __future__ import annotations

from copy import deepcopy
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from audio.render_audio_authority import SOURCE_FLOAT_POLICY_V2
from guided_opening_inputs import OpeningInputs
from guided_presenter_execution import OwnedPresenterExecution
from guided_presenter_probe_identity import probe_deadline_remaining
from guided_presenter_read_fingerprint import hold_read_metadata, same_read_metadata

if TYPE_CHECKING:
    from guided_source_color_base import HeldBt709BaseIdentity

SOURCE_COLOR_UNRESOLVED = "presenter original source color before first lossy encode is not qualified"


@dataclass(frozen=True)
class PresenterBaseContext:
    """Actual caller-held inputs/owner, not independently authorized by type identity."""

    inputs: OpeningInputs
    presenter: OwnedPresenterExecution
    source_color: HeldBt709BaseIdentity | None = None
    _binding: object = field(init=False, repr=False)
    _owner_hold: tuple | None = field(init=False, repr=False)
    _origin: tuple = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Hold the original input value under the same live execution lifetime."""
        if type(self.inputs) is not OpeningInputs or type(self.presenter) is not OwnedPresenterExecution:
            raise RuntimeError("presenter base requires the actual inputs and live observation owner")
        object.__setattr__(self, "_binding", hold_read_metadata(_inputs(self.inputs)))
        held = None
        if self.source_color is not None:
            from guided_presenter_caption_body_picture import _hold_owner
            _color_clock(self)
            held = _hold_owner(self.presenter)
        object.__setattr__(self, "_owner_hold", held)
        object.__setattr__(self, "_origin", _references(self))
        self.assert_current()

    def assert_current(self) -> None:
        """Check full input/plan/clock without decoding or rehashing source media."""
        original = self._origin
        _original(self, original)
        OwnedPresenterExecution.assert_current(self.presenter)
        documents = self.inputs.documents
        OwnedPresenterExecution.assert_plan(self.presenter, documents["candidatePlan"])
        authority = documents["authority"]
        target = authority["target"]
        OwnedPresenterExecution.assert_clock(self.presenter, (target["width"], target["height"]),
                                             (authority["frameRate"], authority["totalFrames"]))
        _check_color(self)
        _original(self, original)
        _final_time(self)


def _inputs(inputs: OpeningInputs) -> tuple:
    """Retain exact input objects/scalar types before any original caller callback."""
    return (id(inputs), str(inputs.path), inputs.sha256, id(inputs.value), inputs.value,
            id(inputs.documents), inputs.documents, id(inputs.verified_media))


def _color_clock(value: PresenterBaseContext) -> tuple | None:
    """Require the actual original opening clock, not reconstructed remaining seconds."""
    if value.source_color is None:
        return None
    from guided_opening_execution import OpeningExecutionClock
    from guided_source_color_base import HeldBt709BaseIdentity
    color, clock = value.source_color, value.presenter.runtime.deadline
    if type(color) is not HeldBt709BaseIdentity or color.inputs is not value.inputs:
        raise RuntimeError("presenter base requires actual BT709 identity for the same original inputs")
    deadline = color.batch.preparation.context.deadline
    if type(clock) is not OpeningExecutionClock or set(vars(clock)) != {"end", "events"} \
            or type(clock.end) is not type(deadline) or clock.end != deadline or type(clock.events) is not list:
        raise RuntimeError("presenter base requires the exact original opening clock and source-color cutoff")
    return id(clock), type(clock.end), clock.end, id(clock.events), id(color._origin)


def _references(value: PresenterBaseContext) -> tuple:
    """Hold context/input/owner/evidence identities, not mutable success declarations."""
    return (id(value), id(value.inputs), id(value.presenter), id(value.source_color),
            id(value._binding), id(value._owner_hold), _color_clock(value))


def _original(value: PresenterBaseContext, original: tuple) -> None:
    """Check original bindings after callbacks without adopting current input values."""
    if value._origin is not original or _references(value) != original:
        raise RuntimeError("presenter base original context/owner/source-color changed")
    if not same_read_metadata(_inputs(value.inputs), value._binding):
        raise RuntimeError("presenter base original input changed")


def _check_color(value: PresenterBaseContext) -> None:
    """Close the last source callback against original presenter metadata/stats and time."""
    if value.source_color is None:
        probe_deadline_remaining(value.presenter.runtime)
        return
    from color.deadline import require_time
    from guided_presenter_caption_body_picture import _check_owner
    from guided_source_color_base import HeldBt709BaseIdentity, _unchanged
    original = value.source_color._origin
    HeldBt709BaseIdentity.assert_current(value.source_color)
    _check_owner(value._owner_hold)
    _unchanged(value.source_color, original)
    require_time(value.source_color.batch.preparation.context.deadline)


def _final_time(value: PresenterBaseContext) -> None:
    """Check the same original overall cutoff after final metadata bookkeeping."""
    if value.source_color is not None:
        from color.deadline import require_time
        require_time(value.source_color.batch.preparation.context.deadline)


def require_unowned_presenter_absent(plan: dict) -> None:
    """Reject property presence before a generic CLI can admit or rebuild media."""
    if type(plan) is dict and "presenterLayouts" in plan:
        raise RuntimeError("presenter plan cannot use an unowned render or base preparation path")


def _context(value: object) -> PresenterBaseContext:
    """Never accept a JSON record or duck-typed callback as the live context."""
    if type(value) is not PresenterBaseContext:
        raise RuntimeError("presenter base requires its actual live preparation context")
    PresenterBaseContext.assert_current(value)
    return value


def _require_original_source_color(context: PresenterBaseContext) -> None:
    """No admission/selected-asset/post-encode tag can substitute for source color.

    Only the separate completed all-used-source identity holder may satisfy
    this prerequisite. Its flags never claim an observed base or approval.
    """
    if context.source_color is None:
        raise RuntimeError(SOURCE_COLOR_UNRESOLVED)


def require_presenter_preparation(inputs: OpeningInputs, context: PresenterBaseContext | None) -> None:
    """Fail before dependencies/directories; legacy inputs retain their old path."""
    present = type(inputs.documents.get("candidatePlan")) is dict \
        and "presenterLayouts" in inputs.documents["candidatePlan"]
    if not present and context is None:
        return
    if not present:
        raise RuntimeError("presenter base context has no requested presenter layout")
    held = _context(context)
    if held.inputs is not inputs:
        raise RuntimeError("presenter base requires the exact original opening inputs")
    _require_original_source_color(held)


def require_presenter_base(ctx: Any) -> None:
    """Fence direct render and publication without relaxing ordinary base gates."""
    context = getattr(ctx, "presenter_base", None)
    present = type(ctx.plan) is dict and "presenterLayouts" in ctx.plan
    if not present and context is None:
        return
    if not present:
        raise RuntimeError("presenter base context has no requested presenter layout")
    original = hold_read_metadata(_render_fields(ctx))
    held = _context(context)
    if ctx.skip_graphics is not True or ctx.resume is not False or ctx.audio_clock_policy != SOURCE_FLOAT_POLICY_V2:
        raise RuntimeError("presenter base requires fresh owned skip-graphics source-float-v2 preparation")
    refs, documents = held.inputs.value["documents"], held.inputs.documents
    manifest = deepcopy(documents["manifest"])
    manifest["_path"] = refs["manifest"]["path"]
    if not same_read_metadata(ctx.plan, hold_read_metadata(documents["candidatePlan"])) \
            or not same_read_metadata(ctx.manifest, hold_read_metadata(manifest)) \
            or ctx.plan_path != refs["candidatePlan"]["path"]:
        raise RuntimeError("presenter base differs from the exact held candidate or manifest")
    require_presenter_preparation(held.inputs, held)
    if not same_read_metadata(_render_fields(ctx), original):
        raise RuntimeError("presenter base actual render context changed during its guard")
    _final_time(held)


def _render_fields(ctx: Any) -> tuple:
    """Hold actual command-building inputs while allowing normal trace/audio state updates."""
    return (id(ctx), id(ctx.plan), ctx.plan, id(ctx.manifest), ctx.manifest, id(ctx.presenter_base),
            ctx.plan_path, ctx.skip_graphics, ctx.resume, ctx.audio_clock_policy,
            getattr(ctx, "out_dir", None), getattr(ctx, "work_dir", None), getattr(ctx, "producer_dir", None))


def hold_presenter_base_guard(ctx: Any) -> Callable[[], None] | None:
    """Keep one original code-only guard across real pre/post-encode boundaries."""
    if not (type(ctx.plan) is dict and "presenterLayouts" in ctx.plan) and getattr(ctx, "presenter_base", None) is None:
        return None
    original = hold_read_metadata(_render_fields(ctx))

    def check() -> None:
        """Never rebaseline changed render command inputs between actual native calls."""
        if not same_read_metadata(_render_fields(ctx), original):
            raise RuntimeError("presenter base original render command inputs changed")
        require_presenter_base(ctx)
        if not same_read_metadata(_render_fields(ctx), original):
            raise RuntimeError("presenter base original render command inputs changed")
        _final_time(ctx.presenter_base)

    check()
    return check
