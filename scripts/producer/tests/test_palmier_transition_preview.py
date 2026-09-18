"""Palmier transition checkpoint previews stay visible and honest."""
import os
import tempfile
import unittest
from unittest.mock import patch

from _common import *  # noqa: F401,F403
from palmier.checkpoint_plan import prepare_checkpoint_plan
from palmier.mcp_client import PalmierError
from palmier.transition_preview import (_render_dimensions,
                                        render_transition_preview,
                                        supported_transition_kinds)


class TransitionPreviewAssetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_white_flash_is_a_proved_three_frame_alpha_overlay(self):
        result = render_transition_preview(
            {"kind": "white-flash", "outTime": 1.0}, 24, 64, 36,
            self.tmp.name)
        self.assertTrue(os.path.isfile(result.path))
        self.assertEqual(result.fidelity, "baked")
        self.assertEqual(result.entry["outStart"], 23 / 24)
        self.assertEqual(result.entry["outEnd"], 26 / 24)
        self.assertEqual(result.proof["alphaMode"], "required")
        self.assertEqual(result.proof["asset"]["frameCount"], 3)
        self.assertEqual(result.proof["alphaProfile"]["frameCount"], 3)
        self.assertGreater(result.proof["alphaProfile"]["normalized"][0], 0.5)

    def test_light_leak_is_labeled_approximate_not_exact(self):
        result = render_transition_preview(
            {"kind": "light-leak", "outTime": 1.0}, 24, 64, 36,
            self.tmp.name)
        self.assertEqual(result.fidelity, "approximate")
        self.assertIn("luma-screen blend", result.limitation)
        self.assertEqual(result.proof["asset"]["frameCount"], 9)

    def test_identical_kind_reuses_one_content_asset_across_seams(self):
        first = render_transition_preview(
            {"kind": "white-flash", "outTime": 1.0}, 24, 64, 36,
            self.tmp.name)
        second = render_transition_preview(
            {"kind": "white-flash", "outTime": 2.0}, 24, 64, 36,
            self.tmp.name)
        self.assertEqual(first.path, second.path)
        self.assertNotEqual(first.entry["outStart"], second.entry["outStart"])

    def test_zoom_pull_is_not_misrepresented_as_supported(self):
        self.assertNotIn("zoom-pull", supported_transition_kinds())
        with self.assertRaisesRegex(ValueError, "no checkpoint preview"):
            render_transition_preview(
                {"kind": "zoom-pull", "outTime": 1.0}, 24, 64, 36,
                self.tmp.name)

    def test_4k_project_reuses_a_full_canvas_1080p_solid_overlay(self):
        self.assertEqual(_render_dimensions(3840, 2160), (1920, 1080))


class CheckpointTransitionIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.plan = {
            "target": {"mode": "longform",
                       "lanes": {"transitions": "operator"}},
            "cutTrack": [{"sourceId": "src", "start": 0, "end": 2}],
            "transitions": [{"kind": "white-flash", "outTime": 1.0}],
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_supported_visual_is_placed_as_overlay_and_not_omitted(self):
        prepared = prepare_checkpoint_plan(
            self.plan, self.tmp.name, fps=24, width=64, height=36)
        self.assertNotIn("transitions", prepared.plan)
        self.assertEqual(len(prepared.plan["graphicsTrack"]), 1)
        self.assertEqual(len(prepared.graphics), 1)
        self.assertEqual(prepared.limitations[0]["fidelity"], "baked")
        self.assertFalse(any(row["lane"] == "transitions"
                             for row in prepared.omissions))

    def test_supported_visual_render_failure_blocks_the_checkpoint(self):
        with patch("palmier.checkpoint_plan.render_transition_preview",
                   side_effect=RuntimeError("alpha render failed")):
            with self.assertRaisesRegex(
                    PalmierError, r"required transitions\[0\].*alpha render failed"):
                prepare_checkpoint_plan(
                    self.plan, self.tmp.name, fps=24, width=64, height=36)

    def test_automatic_supported_transition_is_visible_and_labeled_baked(self):
        plan = {**self.plan, "target": {"mode": "longform"}}
        prepared = prepare_checkpoint_plan(
            plan, self.tmp.name, fps=24, width=64, height=36)
        self.assertEqual(len(prepared.plan["graphicsTrack"]), 1)
        self.assertEqual(prepared.limitations[0]["fidelity"], "baked")

    def test_zoom_pull_remains_an_explicit_omission(self):
        self.plan["transitions"] = [{
            "kind": "zoom-pull", "variant": "whip", "outTime": 1.0,
        }]
        prepared = prepare_checkpoint_plan(
            self.plan, self.tmp.name, fps=24, width=64, height=36)
        omission = next(row for row in prepared.omissions
                        if row["lane"] == "transitions")
        self.assertIn("blur-masked", omission["reason"])


if __name__ == "__main__":
    unittest.main()
