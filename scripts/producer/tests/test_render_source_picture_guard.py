"""Actual cut-stage dispatch with TEST native/proof leaves, never source-color approval."""
from __future__ import annotations

import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

import guided_presenter_base as base
import render


class RenderPictureGuardTests(unittest.TestCase):
    """Original-context checking reaches the actual options/part-encode entry."""

    def setUp(self) -> None:
        """Create only one private TEST output tree; all source/native leaves stay inert."""
        temporary = tempfile.TemporaryDirectory(prefix="sniper-render-guard-", dir="/private/tmp")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.plan = {"cutTrack": [{"sourceId": "TEST-source", "start": 0, "end": 1}]}
        self.manifest = {"sources": [{"id": "TEST-source", "path": str(self.root / "source-not-created.mp4")}]}
        self.ctx = render.RenderCtx(self.plan, self.manifest, str(self.root / "out"), str(self.root / "work"))
        self.proof = {"TEST": "no actual proof"}

    def leaves(self, stack: ExitStack) -> dict[str, Mock]:
        """Keep actual compiler/dispatch but stub all native and output-proof operations."""
        values = {"render_cut_speed": self.proof, "render_cut_speed_opts": self.proof,
                  "probe_video": {"r_frame_rate": "24/1"}, "write_manifestation": {"receiptHash": "TEST"}, "emit": None}
        return {name: stack.enter_context(patch.object(render, name, return_value=result)) for name, result in values.items()}

    def test_actual_unowned_layout_fence_precedes_compile_directory_and_native(self) -> None:
        """The genuine new guard factory refuses direct unowned rendering, not a fake predicate."""
        self.ctx.plan["presenterLayouts"] = []
        with patch.object(render, "compile_plan") as compile_plan, patch.object(render, "render_cut_speed") as native:
            with self.assertRaisesRegex(RuntimeError, "actual live preparation context"):
                render.cut_stage(self.ctx)
        compile_plan.assert_not_called()
        native.assert_not_called()
        self.assertFalse(Path(self.ctx.work_dir).exists())

    def test_legacy_absent_layout_reaches_identical_original_call(self) -> None:
        """Actual legacy guard is None; no new caller hook or options route is imposed."""
        with ExitStack() as stack:
            leaves = self.leaves(stack)
            output = render.cut_stage(self.ctx)
        leaves["render_cut_speed"].assert_called_once_with(self.plan, self.manifest, output,
                                                         str(Path(self.ctx.work_dir) / "cut-parts"))
        leaves["render_cut_speed_opts"].assert_not_called()

    def test_same_code_only_guard_is_passed_to_the_actual_options_slot(self) -> None:
        """A TEST factory seam verifies transport only; it cannot qualify original footage."""
        guard = Mock()
        with ExitStack() as stack:
            leaves = self.leaves(stack)
            factory = stack.enter_context(patch.object(base, "hold_presenter_base_guard", return_value=guard))
            render.cut_stage(self.ctx)
        factory.assert_called_once_with(self.ctx)
        leaves["render_cut_speed"].assert_not_called()
        args = leaves["render_cut_speed_opts"].call_args.args
        self.assertIs(args[0], self.plan)
        self.assertIs(args[1], self.manifest)
        self.assertIs(args[3].before_encode, guard)
        self.assertIsNone(args[3].proxy_scale)
        guard.assert_called_once()
        leaves["write_manifestation"].assert_called_once()

    def test_failed_original_post_guard_prevents_manifestation_publication(self) -> None:
        """Returning native work does not erase a failed ownership check before proof writes."""
        guard = Mock(side_effect=RuntimeError("TEST source picture changed"))
        with ExitStack() as stack:
            leaves = self.leaves(stack)
            stack.enter_context(patch.object(base, "hold_presenter_base_guard", return_value=guard))
            with self.assertRaisesRegex(RuntimeError, "source picture changed"):
                render.cut_stage(self.ctx)
        leaves["render_cut_speed_opts"].assert_called_once()
        leaves["write_manifestation"].assert_not_called()
        leaves["probe_video"].assert_not_called()


if __name__ == "__main__":
    unittest.main()
