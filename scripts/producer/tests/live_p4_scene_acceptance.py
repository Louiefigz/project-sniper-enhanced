#!/usr/bin/env python3
"""Opt-in real P4 clean-render, seek, and ordered-unit acceptance."""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest

from scene_fixtures import fire_sparkles_scene

from graphics.scene_bundle import capture_bundle
from graphics.scene_oracle import (
    UnitMedia,
    UnitOracleRequest,
    assert_clean_render_match,
    assert_random_seek_match,
    prove_unit_equivalence,
)
from graphics.scene_render import (
    SceneRenderRequest,
    render_scene,
    render_scene_units,
)

ENABLED = os.environ.get("RUN_P4_SCENE_TESTS") == "1"
HAVE_TOOLS = all(shutil.which(name) for name in ("ffmpeg", "ffprobe", "node"))
PRODUCER_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(
    PRODUCER_ROOT, "tests", "fixtures", "fire-sparkles-bundle")


@unittest.skipUnless(ENABLED and HAVE_TOOLS, "opt-in P4 scene acceptance")
class LiveP4SceneAcceptanceTests(unittest.TestCase):
    """Every decoded frame is deterministic and units equal the full scene."""

    def test_fire_sparkles_clean_seek_and_unit_oracles(self) -> None:
        bundle = capture_bundle(FIXTURE)
        scene = fire_sparkles_scene(bundle.digest)
        with tempfile.TemporaryDirectory(prefix="sniper-p4-live-") as root:
            first = render_scene(SceneRenderRequest(
                scene, bundle, os.path.join(root, "first")))
            second = render_scene(SceneRenderRequest(
                scene, bundle, os.path.join(root, "second")))
            clean = assert_clean_render_match(first["path"], second["path"])
            self.assertEqual(clean["frameCount"], 180)
            seek = assert_random_seek_match(
                first["path"], (179, 0, 90, 17, 164, 6, 23, 1))
            self.assertEqual(seek["checkedFrames"][0], 179)
            rendered_units = render_scene_units(
                scene, bundle, os.path.join(root, "units"), workers=2)
            z_index = {row["unitId"]: row["zIndex"]
                       for row in scene["renderUnits"]}
            units = tuple(UnitMedia(
                row["unitId"], z_index[row["unitId"]], row["path"])
                for row in rendered_units)
            oracle = prove_unit_equivalence(UnitOracleRequest(
                scene, first["path"], units,
                os.path.join(root, "ordered-units.mov")))
            self.assertGreaterEqual(oracle["colorSsim"], 0.995)
            self.assertGreaterEqual(oracle["alphaSsim"], 0.995)


if __name__ == "__main__":
    unittest.main(verbosity=2)
