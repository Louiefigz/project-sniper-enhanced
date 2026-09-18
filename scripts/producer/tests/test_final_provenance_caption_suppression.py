"""Final-provenance coverage for legacy caption suppression."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import render as renderer
from tests._final_provenance_fixture import plan as provenance_plan


class CaptionSuppressionTests(unittest.TestCase):
    def test_base_render_suppresses_legacy_captions_for_takeover(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp, "captions.ass")
            source.write_text(
                "[Events]\n"
                "Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
                "MarginV, Effect, Text\n"
                "Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,Hide\n"
                "Dialogue: 0,0:00:02.00,0:00:03.00,Default,,0,0,0,,Keep\n",
                encoding="utf-8",
            )
            plan = provenance_plan()
            plan["graphicsTrack"][0].update({
                "anchor": "own-screen", "outStart": 0.0, "outEnd": 1.5,
            })
            ctx = renderer.RenderCtx(
                plan, {}, tmp, tmp, skip_graphics=True,
            )
            output = renderer._suppress_legacy_base_captions(
                ctx, str(source),
            )
            self.assertIsNotNone(output)
            rendered = Path(output).read_text(encoding="utf-8")
            self.assertNotIn("Hide", rendered)
            self.assertIn("Keep", rendered)


if __name__ == "__main__":
    unittest.main(verbosity=2)
