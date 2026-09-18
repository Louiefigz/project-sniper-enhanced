"""Metadata-only actual source context and preparation transport regressions."""
from __future__ import annotations

from copy import deepcopy
from contextlib import ExitStack
from dataclasses import replace
from unittest.mock import Mock, patch
from types import SimpleNamespace
import unittest

from _source_color_base_context_fixture import SourceOnlyBaseFixture
from _source_color_batch_fixture import current_batch_test_pins
from guided_opening_execution import OpeningExecutionClock
from guided_opening_prepare import prepare_full_program, prepare_source_color_full_program
from guided_source_color_base_context import (
    SourceColorBaseContext, hold_source_color_base_guard, require_source_color_base, source_color_stage,
)
import render


class SourceColorBaseContextTests(unittest.TestCase):
    """Real held metadata/clock objects; no renderer or source decoder runs."""

    @classmethod
    def setUpClass(cls) -> None:
        """Capture the current bounded implementation once for this stable cohort."""
        cls.pins = current_batch_test_pins()

    def fixture(self, change: dict | None = None) -> tuple:
        """Retain only exact disposable TEST paths from the original fixture."""
        fixture = SourceOnlyBaseFixture(self.pins, change)
        self.addCleanup(fixture.cleanup)
        return fixture, fixture.identity()

    def test_actual_source_only_context_retains_original_objects_and_false_flags(self) -> None:
        """No presenter is constructed or persisted source-color proof inferred."""
        fixture, identity = self.fixture()
        context = fixture.base_context(identity)
        ctx = fixture.render_context(context)
        hold_source_color_base_guard(ctx)()
        self.assertIs(context.inputs, identity.inputs)
        self.assertIs(context.clock, fixture.clock)
        self.assertIs(context.source_color, identity)
        self.assertIsNone(ctx.presenter_base)
        self.assertFalse(identity.base_picture_observed)
        self.assertFalse(identity.grade_applicable)

    def test_equal_replacement_clock_guard_and_inputs_refuse(self) -> None:
        """Equal end seconds or input values do not recreate the original opening owner."""
        fixture, identity = self.fixture()
        cases = ((fixture.inputs, OpeningExecutionClock(fixture.clock.end), identity, fixture.guard),
                 (replace(fixture.inputs), fixture.clock, identity, fixture.guard),
                 (fixture.inputs, fixture.clock, identity, lambda: None))
        for arguments in cases:
            self.assertRaisesRegex(RuntimeError, "same original", SourceColorBaseContext, *arguments)
        self.assertRaisesRegex(RuntimeError, "actual inputs", SourceColorBaseContext,
                               fixture.inputs, fixture.clock, {}, fixture.guard)

    def test_short_and_reframe_refuse_before_any_new_source_callback(self) -> None:
        """Short support remains explicit unfinished work, never an implicit conversion."""
        changes = ({"target": {"mode": "short", "width": 1080, "height": 1920}},
                   {"reframe": {"strategy": "center"}})
        for change in changes:
            fixture, identity = self.fixture(change)
            fixture.guard.reset_mock()
            self.assertRaisesRegex(RuntimeError, "longform without reframe", fixture.base_context, identity)
            fixture.guard.assert_not_called()

    def test_presenter_registry_fence_is_not_released(self) -> None:
        """A source holder cannot waive even an empty requested presenter root."""
        fixture, identity = self.fixture({"presenterLayouts": []})
        self.assertRaisesRegex(RuntimeError, "presenterLayouts", fixture.base_context, identity)

    def test_first_holder_callback_cannot_change_original_inputs(self) -> None:
        """Capture precedes the first supplied persistent owner callback."""
        fixture, identity = self.fixture()
        fixture.guard.side_effect = lambda: fixture.inputs.documents["candidatePlan"].update(TEST=True)
        self.assertRaisesRegex(RuntimeError, "changed", fixture.base_context, identity)

    def test_original_render_command_identity_and_numeric_drift_refuse(self) -> None:
        """Type-coerced or equal-valued replacement command data is not rebaselined."""
        fixture, identity = self.fixture()
        ctx = fixture.render_context(fixture.base_context(identity))
        guard = hold_source_color_base_guard(ctx)
        changes = (("plan", deepcopy(ctx.plan)), ("manifest", deepcopy(ctx.manifest)),
                   ("out_dir", ctx.out_dir + "-changed"), ("resume", True), ("skip_graphics", 1))
        for name, value in changes:
            original = getattr(ctx, name)
            setattr(ctx, name, value)
            self.assertRaisesRegex(RuntimeError, "original render command", guard)
            setattr(ctx, name, original)
        ctx.plan["target"]["width"] = 1920.0
        self.assertRaisesRegex(RuntimeError, "original render command", guard)

    def test_final_source_callback_and_original_expiry_refuse(self) -> None:
        """The last callback cannot replace render arguments or renew the clock."""
        fixture, identity = self.fixture()
        ctx = fixture.render_context(fixture.base_context(identity))
        fixture.guard.side_effect = lambda: setattr(ctx, "out_dir", ctx.out_dir + "-changed")
        self.assertRaisesRegex(RuntimeError, "render arguments changed", require_source_color_base, ctx)
        fixture.guard.side_effect = lambda: setattr(fixture, "now", fixture.clock.end)
        self.assertRaisesRegex(RuntimeError, "deadline|time budget", require_source_color_base, ctx)

    def test_actual_render_still_reaches_existing_audio_gate(self) -> None:
        """Positive metadata stops at the unchanged production admission, before native."""
        fixture, identity = self.fixture()
        ctx = fixture.render_context(fixture.base_context(identity))
        with patch.object(render, "admit_audio", side_effect=RuntimeError("TEST existing audio gate")) as gate:
            self.assertRaisesRegex(RuntimeError, "existing audio gate", render.render, ctx)
        gate.assert_called_once_with(ctx.plan, ctx.manifest, (ctx.audio_clock_policy, ctx.resume))

    def test_owned_and_legacy_preparation_share_body_without_new_receipt_fields(self) -> None:
        """Legacy transport remains, while a fake owned result cannot omit actual encode hooks."""
        fixture, identity = self.fixture()
        context = fixture.base_context(identity)
        result = {"TEST": "no actual base evidence"}
        with patch("guided_opening_prepare._prepare", return_value=result) as prepare:
            self.assertIs(prepare_full_program(fixture.inputs, fixture.root, fixture.guard), result)
            prepare.assert_called_once_with(fixture.inputs, fixture.root, (fixture.guard, None, None))
            prepare.reset_mock()
            self.assertRaisesRegex(RuntimeError, "consumption is incomplete", prepare_source_color_full_program,
                                   fixture.inputs, fixture.root, context)
            arguments = prepare.call_args.args
        self.assertIs(arguments[2][2], context)
        self.assertIsNone(arguments[2][1])
        self.assertIs(arguments[2][0].__self__, context)

    def test_preparation_final_callback_failure_does_not_return_old_result(self) -> None:
        """An already-produced value is not success after original source lifetime fails."""
        fixture, identity = self.fixture()
        context = fixture.base_context(identity)

        def prepared(*_args: object) -> object:
            """Only mutate an in-memory TEST context after the fake render return."""
            fixture.guard.side_effect = RuntimeError("TEST late source change")
            return object()

        with patch("guided_opening_prepare._prepare", side_effect=prepared):
            self.assertRaisesRegex(RuntimeError, "late source change", prepare_source_color_full_program,
                                   fixture.inputs, fixture.root, context)

    def test_stage_preserves_original_arguments_and_checks_both_boundaries(self) -> None:
        """The wrapper does not modify a legacy operation or synthesize its output."""
        value, operation, guard = object(), Mock(), Mock()
        operation.return_value = value
        self.assertIs(source_color_stage(None, operation, (1, 2)), value)
        operation.assert_called_once_with(1, 2)
        self.assertIs(source_color_stage(guard, operation, (3,)), value)
        self.assertEqual(guard.call_count, 2)
        guard.side_effect = (None, RuntimeError("TEST post-stage"))
        self.assertRaisesRegex(RuntimeError, "post-stage", source_color_stage, guard, operation, ())

    def test_same_actual_source_context_reaches_cut_options_hook(self) -> None:
        """Only native/proof leaves are mocked; original guard factory/dispatch are real."""
        fixture, identity = self.fixture()
        ctx = fixture.render_context(fixture.base_context(identity))
        values = {"render_cut_speed_opts": {"TEST": "not native proof"},
                  "probe_video": {"r_frame_rate": "24/1"}, "write_manifestation": {"receiptHash": "TEST"}, "emit": None}
        with ExitStack() as stack:
            leaves = {name: stack.enter_context(patch.object(render, name, return_value=value))
                      for name, value in values.items()}
            legacy = stack.enter_context(patch.object(render, "render_cut_speed"))
            self.assertRaisesRegex(RuntimeError, "manifestation omitted", render.cut_stage, ctx)
        legacy.assert_not_called()
        options = leaves["render_cut_speed_opts"].call_args.args[3]
        self.assertIsNone(options.proxy_scale)
        self.assertIs(options.picture_consumption, ctx.source_color_base.consumption)
        fixture.guard.side_effect = RuntimeError("TEST retained cut source")
        self.assertRaisesRegex(RuntimeError, "retained cut source", options.before_encode)

    def test_actual_shared_preparation_body_preserves_legacy_output_fields(self) -> None:
        """All render/qualification leaves are TEST stubs; no schema1 color proof is added."""
        fixture, identity = self.fixture()
        context = fixture.base_context(identity)
        base, work = fixture.root / "TEST-base", fixture.root / "TEST-work"
        bus = SimpleNamespace(frame_rate="30000/1001", frames=24, admission=SimpleNamespace(tools={}), directory=str(base))

        def rendered(ctx: render.RenderCtx) -> dict:
            """Keep actual RenderCtx transport and explicitly omit all native work."""
            self.assertIn(ctx.source_color_base, (None, context))
            ctx.source_audio_bus = bus
            return {"TEST": "render not executed"}

        values = {"_validate_preparation": None, "_base_directories": (base, work),
                  "observe_picture": {"TEST": "picture not observed"},
                  "build_program_master": SimpleNamespace(directory=str(base)),
                  "capture_master_selection": SimpleNamespace(event_sha256="a" * 64),
                  "capture_short_geometry": None, "file_hash": "b" * 64}
        with ExitStack() as stack:
            for name, value in values.items():
                stack.enter_context(patch("guided_opening_prepare." + name, return_value=value))
            stack.enter_context(patch("guided_opening_prepare.render", side_effect=rendered))
            legacy = prepare_full_program(fixture.inputs, fixture.root, fixture.guard)
            from guided_opening_prepare import _prepare
            owned = _prepare(fixture.inputs, fixture.root, (context.assert_current, None, context))
            self.assertRaisesRegex(RuntimeError, "consumption is incomplete", context.consumption_record)
        self.assertEqual(owned.evidence, legacy.evidence)
        self.assertNotIn("sourceColor", owned.evidence)
        self.assertIsNone(owned.captions)
        self.assertFalse(base.exists())


if __name__ == "__main__":
    unittest.main()
