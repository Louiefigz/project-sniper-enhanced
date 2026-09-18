"""Non-visible Palmier component inventory tests."""
import os
import tempfile
import unittest

from _common import *  # noqa: F401,F403
from palmier.components import component_assets


class ComponentInventoryTests(unittest.TestCase):
    def test_collects_every_current_edit_asset_without_unselected_broll(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = {
                "brollTrack": [{"assetId": "used"}],
                "music": {"enabled": True, "path": "bed.wav"},
                "captions": {"srtPath": "captions.srt"},
                "titleCards": [{"renderPath": "title.mov"}],
                "transitions": [{"sfx": {"path": "hit.wav"}}],
            }
            manifest = {
                "sources": [{"id": "a", "path": "raw.mp4",
                             "transcriptPath": "raw.words.json"}],
                "broll": [{"id": "used", "path": "broll.mp4"},
                          {"id": "unused", "path": "unused.mp4"}],
            }
            paths = component_assets(
                plan, manifest, os.path.join(tmp, "asset_manifest.json"),
                {0: os.path.join(tmp, "graphic.mov")})
        self.assertEqual(set(paths), {
            "graphics:0", "source:a", "source:a:transcript", "broll:used",
            "music:selected",
        })
        self.assertFalse(
            {"captions:0:srtPath", "title:0:renderPath", "transition:0:sfx"}
            & set(paths))
        self.assertNotIn("broll:unused", paths)
        self.assertTrue(all(os.path.isabs(path) for path in paths.values()))


if __name__ == "__main__":
    unittest.main()
