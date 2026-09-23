"""Eligibility and geometry safeguards for cutting directly to delivery size."""
from __future__ import annotations

import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cut_reframe import select_fusion
from cut_speed import Profile, Segment, _video_chain


class CutReframeTests(unittest.TestCase):
    """Only crops fixed before encoding can remove the second generation."""

    def setUp(self) -> None:
        """Use placeholder paths; only the geometry probe is simulated."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / "source.mp4"
        self.source.write_bytes(b"geometry-test")
        self.ctx = SimpleNamespace(plan={"target": {"mode": "short"},
            "cutTrack": [{"sourceId": "s", "start": 0, "end": 1}]},
            manifest={"sources": [{"id": "s", "path": str(self.source)}]}, resume=False)
        self.size = {"width": 2160, "height": 3840}

    def select(self, guarded: bool = False) -> object:
        """Select against a controlled ffprobe response."""
        with patch("cut_reframe.probe_video", return_value=self.size):
            return select_fusion(self.ctx, guarded)

    def test_portrait_default_face_uses_crop_before_scale_and_exact_clock(self) -> None:
        """Portrait passthrough has no face-dependent geometry."""
        selected = self.select()
        profile = selected.output_profile(Profile(2160, 3840, Fraction(30000, 1001), "yuv420p10le"))
        self.assertEqual((profile.width, profile.height, profile.fps_arg), (1080, 1920, "30000/1001"))
        graph = _video_chain(Segment(0, "s", 3, 4, 1, 0, 1), 1, profile, selected)
        self.assertLess(graph.index("crop="), graph.index("scale="))
        self.assertNotIn("pad=", graph)
        with self.assertRaisesRegex(RuntimeError, "geometry changed"):
            selected.output_profile(Profile(3840, 2160, Fraction(30), "yuv420p"))

    def test_landscape_face_keeps_tracking_but_center_can_fuse(self) -> None:
        """A fixed center crop is available without guessing face windows."""
        self.size = {"width": 3840, "height": 2160}
        self.assertIsNone(self.select())
        self.ctx.plan["reframe"] = {"strategy": "center"}
        self.assertIn("crop=1216:2160:1312:0", self.select().video_filter)

    def test_rotation_uses_display_dimensions(self) -> None:
        """Rotated phone footage remains portrait in both selectors."""
        self.size = {"width": 3840, "height": 2160, "side_data_list": [{"rotation": 270}]}
        self.assertEqual(self.select().source_width, 2160)

    def test_ineligible_paths_keep_existing_pipeline(self) -> None:
        """Protected, manual, baseline, proxy-size and resumed routes remain owned."""
        self.assertIsNone(self.select(True))
        for cfg in ({"crop": {}}, {"layout": "split"}, {"strategy": "blurpad"}, {"strategy": "none"}):
            self.ctx.plan["reframe"] = cfg
            self.assertIsNone(self.select())
        self.ctx.plan.pop("reframe")
        self.ctx.resume = True
        self.assertIsNone(self.select())
        self.ctx.resume = False
        self.ctx.plan["baselineLook"] = {"contrast": 1.1}
        self.assertIsNone(self.select())
        self.ctx.plan.pop("baselineLook")
        self.size = {"width": 1080, "height": 1920}
        self.assertIsNone(self.select())

    def test_mixed_geometry_and_missing_sources_do_not_fuse(self) -> None:
        """The original common-profile normalization remains necessary."""
        second = self.source.with_name("second.mp4")
        second.write_bytes(b"second")
        self.ctx.manifest["sources"].append({"id": "b", "path": str(second)})
        self.ctx.plan["cutTrack"].append({"sourceId": "b", "start": 1, "end": 2})
        with patch("cut_reframe.probe_video", side_effect=[self.size, {"width": 3840, "height": 2160}]):
            self.assertIsNone(select_fusion(self.ctx, False))
        second.unlink()
        self.assertIsNone(self.select())
