"""Landscape/portrait title-card alpha geometry contracts."""
from __future__ import annotations

import os
import unittest
from fractions import Fraction
from unittest import mock

from _common import *  # noqa: F401,F403
from captions import overlays
from captions import title_card_shards
from captions.overlays import _overlay_xy
from captions.title_card_layout import layout_for_canvas
from captions.title_card_shards import _command


class TitleCardAlphaLayoutTests(unittest.TestCase):
    def test_landscape_card_is_centered_inside_16x9_safe_geometry(self):
        layout = layout_for_canvas(1920, 1080)
        x, y = _overlay_xy(900, 120, layout)
        self.assertEqual(layout.visual_center_x, 880)
        self.assertGreaterEqual(x, layout.safe["left"])
        self.assertLessEqual(
            x + 900, layout.width - layout.safe["right"])
        self.assertGreaterEqual(y, layout.safe["top"])
        self.assertLessEqual(y + 120, layout.y_range[1])

    def test_landscape_alpha_command_uses_exact_canvas_clock_and_frames(self):
        layout = layout_for_canvas(1920, 1080)
        command = _command(
            "/tmp/card.png", "/tmp/card.mov", (900, 240), {
                "frames": 72, "rate": Fraction(24, 1), "layout": layout,
            })
        self.assertIn(
            "color=c=black@0.0:s=1920x1080:r=24/1,format=rgba", command)
        self.assertEqual(command[command.index("-frames:v") + 1], "72")
        self.assertEqual(command[command.index("-pix_fmt") + 1], "rgba")
        self.assertEqual(command[-1], "/tmp/card.mov")

    def test_portrait_alpha_command_uses_exact_canvas(self):
        layout = layout_for_canvas(1080, 1920)
        command = _command(
            "/tmp/card.png", "/tmp/card.mov", (600, 180), {
                "frames": 90, "rate": Fraction(30, 1), "layout": layout,
            })
        self.assertIn(
            "color=c=black@0.0:s=1080x1920:r=30/1,format=rgba", command)
        self.assertEqual(command[command.index("-frames:v") + 1], "90")

    def test_standalone_builder_derives_layout_from_input_video(self):
        stream = {"width": 1920, "height": 1080, "r_frame_rate": "24/1"}
        with mock.patch.object(overlays, "probe_video", return_value=stream), \
             mock.patch.object(
                 overlays, "build_card_png", return_value=(900, 120)
             ) as build, \
             mock.patch.object(overlays, "apply_cards") as apply:
            result = overlays.build_and_apply(
                "/tmp/in.mp4",
                [{"text": "LANDSCAPE", "outStart": 0, "outEnd": 2}],
                "/tmp/out.mp4", "/tmp")
        layout = build.call_args.args[2]
        self.assertEqual((layout.width, layout.height), (1920, 1080))
        self.assertIs(apply.call_args.args[3], layout)
        self.assertEqual(result["canvas"], [1920, 1080])

    def test_overlay_loop_uses_input_fractional_frame_rate(self):
        layout = layout_for_canvas(1920, 1080)
        card = {
            "png": "/tmp/card.png", "outStart": 0.0, "outEnd": 2.0,
        }
        image = mock.MagicMock()
        image.__enter__.return_value.size = (900, 120)
        with mock.patch.object(overlays.Image, "open", return_value=image), \
             mock.patch.object(overlays, "probe_video", return_value={
                 "width": 1920, "height": 1080,
                 "r_frame_rate": "24000/1001",
             }), mock.patch.object(overlays, "_run") as run:
            overlays.apply_cards(
                "/tmp/in.mp4", [card], "/tmp/out.mp4", layout)
        command = run.call_args.args[0]
        self.assertEqual(
            command[command.index("-framerate") + 1], "24000/1001")

    def test_title_authority_normalizes_relative_output_directory(self):
        plan = {"titleCards": [{
            "text": "TITLE", "outStart": 0.0, "outEnd": 1.0,
        }]}
        built = [{"canvas": [320, 180], "png": "/tmp/card.png",
                  "dims": [100, 20]}]
        manifestation = {
            "frameRate": "30/1", "receiptHash": "receipt",
            "timelineMapSha256": "timeline",
            "concat": {"videoFrames": 30},
        }
        with mock.patch.object(
                title_card_shards, "verify_manifestation",
                return_value=manifestation), \
             mock.patch.object(
                 title_card_shards, "_renderer",
                 return_value=({}, {}, "renderer")), \
             mock.patch.object(
                 title_card_shards, "_render_one",
                 return_value={}) as render, \
             mock.patch.object(title_card_shards, "write_json_atomic"):
            title_card_shards.materialize_title_card_shards(
                plan, "relative-output", built)
        self.assertTrue(os.path.isabs(render.call_args.args[0]))


if __name__ == "__main__":
    unittest.main()
