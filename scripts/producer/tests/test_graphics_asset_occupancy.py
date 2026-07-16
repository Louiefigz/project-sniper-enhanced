"""Real-media regressions for sustained rendered graphic occupancy."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from _common import pl  # noqa: F401
from graphics import asset_proof as proof


def _entry(anchor: str = "own-screen") -> dict:
    return {"kind": "statement-card", "anchor": anchor,
            "spec": {"variant": "classic", "text": "Visible copy"}}


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg required")
class SustainedOccupancyTests(unittest.TestCase):
    def test_opaque_card_records_measured_content_not_canvas_opacity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "content.mp4")
            source = ("color=c=black:s=64x64:d=0.4:r=10,"
                      "drawbox=x=8:y=8:w=24:h=24:color=white:t=fill")
            subprocess.run([
                "ffmpeg", "-v", "error", "-f", "lavfi", "-i", source,
                "-c:v", "libx264", "-pix_fmt", "yuv420p", path,
            ], check=True)
            result = proof.prove_rendered_asset(
                path, _entry(), "mp4", (64, 64), 0.4, "content-key")
            occupancy = result["occupancy"]
            self.assertEqual(occupancy["mode"], "opaque-measured-content")
            self.assertGreater(occupancy["areaRatio"], 0.0)
            self.assertLess(occupancy["areaRatio"], 1.0)

    def test_opaque_black_card_fails_meaningful_content_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "black.mp4")
            subprocess.run([
                "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                "color=c=black:s=64x64:d=0.4:r=10", "-c:v", "libx264",
                "-pix_fmt", "yuv420p", path,
            ], check=True)
            with self.assertRaisesRegex(RuntimeError, "blank/flat"):
                proof.prove_rendered_asset(
                    path, _entry(), "mp4", (64, 64), 0.4, "black-key")

    def test_one_frame_alpha_speck_fails_sustained_occupancy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "speck.mov")
            source = (
                "nullsrc=s=64x64:d=1:r=10,format=rgba,"
                "geq=r=255:g=255:b=255:"
                "a='if(eq(N,4)*between(X,8,23)*between(Y,8,23),255,0)'")
            subprocess.run([
                "ffmpeg", "-v", "error", "-f", "lavfi", "-i", source,
                "-c:v", "qtrle", path,
            ], check=True)
            with self.assertRaisesRegex(RuntimeError, "sustained meaningful"):
                proof.prove_rendered_asset(
                    path, _entry("free-band"), "mov", (64, 64), 1.0,
                    "speck-key")


if __name__ == "__main__":
    unittest.main(verbosity=2)
