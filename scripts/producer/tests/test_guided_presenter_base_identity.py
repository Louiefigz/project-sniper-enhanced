"""Actual internal source-color/base guards with TEST native and admission leaves.

No base pixels, decoder, public presenter intake or approved source color is
claimed. Faults mutate only in-memory TEST objects, never dependency files.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from unittest.mock import patch
import unittest

from _source_color_base_fixture import SourceColorBaseFixture
from _source_color_batch_fixture import current_batch_test_pins
from guided_opening_execution import OpeningExecutionClock
from guided_opening_prepare import prepare_full_program
from guided_presenter_base import PresenterBaseContext, hold_presenter_base_guard, require_presenter_base
from guided_presenter_execution import OwnedPresenterExecution
from render import render
import guided_presenter_base as base


class PresenterBaseIdentityTests(unittest.TestCase):
    """Exercise real evidence objects up to, but not through, the existing renderer."""

    @classmethod
    def setUpClass(cls) -> None:
        """Capture current implementation once for a source-stable metadata cohort."""
        cls.pins = current_batch_test_pins()

    def fixture(self) -> tuple[SourceColorBaseFixture, object]:
        """Create exact owned TEST files and preserve all original source/clock objects."""
        value = SourceColorBaseFixture(self.pins)
        self.addCleanup(value.cleanup)
        return value, value.identity()

    def test_internal_positive_reaches_existing_audio_and_preparation_gates_only(self) -> None:
        """Genuine all-used identity removes only its own prerequisite, not other gates."""
        fixture, identity = self.fixture()
        ctx = fixture.render_context(identity)
        check = hold_presenter_base_guard(ctx)
        check()
        with patch("render.admit_audio", side_effect=RuntimeError("TEST existing audio gate")) as audio:
            self.assertRaisesRegex(RuntimeError, "existing audio gate", render, ctx)
        audio.assert_called_once_with(ctx.plan, ctx.manifest, (ctx.audio_clock_policy, ctx.resume))
        path = fixture.root / "TEST-unstarted-preparation"
        with patch("guided_opening_prepare._validate_preparation", side_effect=RuntimeError("TEST old preparation")):
            self.assertRaisesRegex(RuntimeError, "old preparation", prepare_full_program,
                                   fixture.inputs, path, fixture.guard, ctx.presenter_base)
        self.assertFalse(path.exists())
        self.assertIs(ctx.presenter_base.inputs, identity.inputs)
        self.assertFalse(identity.base_picture_observed)

    def test_guard_never_rebaselines_original_command_inputs(self) -> None:
        """Even equal plan replacement or late path/numeric changes fail before encode."""
        fixture, identity = self.fixture()
        ctx = fixture.render_context(identity)
        check = hold_presenter_base_guard(ctx)
        changes = (("plan", deepcopy(ctx.plan)), ("manifest", deepcopy(ctx.manifest)),
                   ("out_dir", ctx.out_dir + "-changed"), ("skip_graphics", 1),
                   ("resume", True), ("audio_clock_policy", "legacy-v1"))
        for name, changed in changes:
            old = getattr(ctx, name)
            setattr(ctx, name, changed)
            self.assertRaisesRegex(RuntimeError, "original render command", check)
            setattr(ctx, name, old)
        ctx.plan["target"]["width"] = 64.0
        self.assertRaisesRegex(RuntimeError, "original render command", check)

    def test_constructor_captures_original_input_before_first_owner_callback(self) -> None:
        """A callback cannot mutate unrelated candidate fields then adopt a new baseline."""
        fixture, identity = self.fixture()
        actual = OwnedPresenterExecution.assert_current
        changed = [False]

        def current(owner: OwnedPresenterExecution) -> None:
            """Mutate an in-memory TEST input only at the first live owner callback."""
            actual(owner)
            if not changed[0]:
                changed[0] = True
                fixture.inputs.documents["candidatePlan"]["TEST-late"] = True

        with patch.object(OwnedPresenterExecution, "assert_current", new=current):
            self.assertRaisesRegex(RuntimeError, "input changed|inputs changed|metadata changed|original arguments changed",
                                   PresenterBaseContext, fixture.inputs, fixture.presenter, identity)
        self.assertTrue(changed[0])

    def test_final_source_callback_cannot_change_selected_observation(self) -> None:
        """Source holds do not replace the final independent presenter metadata sweep."""
        fixture, identity = self.fixture()
        ctx = fixture.render_context(identity)
        asset = fixture.presenter.observed[0].graph_asset
        fixture.guard.side_effect = lambda: object.__setattr__(asset, "width", 66)
        self.assertRaisesRegex(RuntimeError, "owner/runtime/observation changed", require_presenter_base, ctx)

    def test_original_clock_replacement_and_same_clock_expiry_refuse(self) -> None:
        """Equal seconds do not replace the actual clock; final source time may not renew."""
        fixture, identity = self.fixture()
        ctx = fixture.render_context(identity)
        runtime = fixture.presenter.runtime
        object.__setattr__(runtime, "deadline", OpeningExecutionClock(fixture.clock.end))
        self.assertRaisesRegex(RuntimeError, "context/owner/source-color changed", require_presenter_base, ctx)
        object.__setattr__(runtime, "deadline", fixture.clock)
        fixture.guard.side_effect = lambda: setattr(fixture, "now", fixture.clock.end)
        self.assertRaisesRegex(RuntimeError, "deadline|time budget", require_presenter_base, ctx)

    def test_original_inputs_and_false_evidence_flags_cannot_be_replaced(self) -> None:
        """Type-compatible data copies and modified claims cannot acquire live source color."""
        fixture, identity = self.fixture()
        self.assertRaisesRegex(RuntimeError, "same original inputs", PresenterBaseContext,
                               replace(fixture.inputs), fixture.presenter, identity)
        ctx = fixture.render_context(identity)
        object.__setattr__(identity, "grade_applicable", True)
        self.assertRaisesRegex(RuntimeError, "identity evidence changed", require_presenter_base, ctx)

    def test_final_bookkeeping_expiry_uses_the_same_original_cutoff(self) -> None:
        """A final pure comparison cannot publish success after consuming remaining time."""
        fixture, identity = self.fixture()
        ctx = fixture.render_context(identity)
        check = hold_presenter_base_guard(ctx)
        original, compare, armed = base.require_presenter_base, base.same_read_metadata, [False]

        def required(value: object) -> None:
            """Arm only after the real complete source/presenter guard has returned."""
            original(value)
            armed[0] = True

        def comparison(value: object, expected: object) -> bool:
            """Consume only virtual TEST time in the last actual command-input comparison."""
            result = compare(value, expected)
            if armed[0] and type(value) is tuple and value[0] == id(ctx):
                fixture.now = fixture.clock.end
            return result

        with patch.object(base, "require_presenter_base", side_effect=required), \
                patch.object(base, "same_read_metadata", side_effect=comparison):
            self.assertRaisesRegex(RuntimeError, "deadline", check)


if __name__ == "__main__":
    unittest.main()
