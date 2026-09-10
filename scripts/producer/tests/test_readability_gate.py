"""Real-background contrast/backing gate samples actual decoded footage."""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest

from graphics.readability_gate import ReadabilityRequest, prove_readability


def _solid(path: str, color: str) -> None:
    subprocess.run([
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
        f"color=c={color}:s=160x90:r=30:d=0.4",
        "-c:v", "ffv1", "-pix_fmt", "yuv420p", path,
    ], check=True)


def _two_tone(path: str) -> None:
    subprocess.run([
        "ffmpeg", "-v", "error",
        "-f", "lavfi", "-i", "color=c=black:s=160x90:r=30:d=0.2",
        "-f", "lavfi", "-i", "color=c=white:s=160x90:r=30:d=0.2",
        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0",
        "-c:v", "ffv1", "-pix_fmt", "yuv420p", path,
    ], check=True)


def _request(path: str, color: str,
             frame_range: tuple[int, int] = (0, 12),
             backing: dict | None = None) -> ReadabilityRequest:
    treatment = {"textColor": color, "minimumContrast": 4.5}
    if backing is not None:
        treatment["backing"] = backing
    return ReadabilityRequest(
        os.path.realpath(path), frame_range, (0.1, 0.1, 0.8, 0.8),
        treatment)


class ReadabilityGateTests(unittest.TestCase):
    def test_actual_white_background_accepts_black_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "white.mkv")
            _solid(path, "white")
            receipt = prove_readability(_request(path, "#000000"))
        self.assertTrue(receipt["passed"])
        self.assertEqual(receipt["sourceFps"], {
            "numerator": "30", "denominator": "1"})
        self.assertGreater(receipt["minimumContrast"], 20)

    def test_same_color_without_backing_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "white.mkv")
            _solid(path, "white")
            with self.assertRaisesRegex(RuntimeError, "readability failed"):
                prove_readability(_request(path, "#FFFFFF"))

    def test_hash_bound_backing_can_prove_contrast(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "white.mkv")
            _solid(path, "white")
            backing = {
                "color": "#000000", "opacity": 0.85,
                "assetProofSha256": "a" * 64,
            }
            receipt = prove_readability(
                _request(path, "#FFFFFF", backing=backing))
        self.assertTrue(receipt["passed"])
        self.assertEqual(
            receipt["backing"]["assetProofSha256"], "a" * 64)

    def test_visible_interval_changes_the_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "two-tone.mkv")
            _two_tone(path)
            self.assertTrue(prove_readability(
                _request(path, "#FFFFFF", (0, 6)))["passed"])
            with self.assertRaisesRegex(RuntimeError, "readability failed"):
                prove_readability(_request(path, "#FFFFFF", (0, 12)))

    def test_unproved_backing_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "white.mkv")
            _solid(path, "white")
            backing = {"color": "#000000", "opacity": 1}
            with self.assertRaisesRegex(ValueError, "backing proof"):
                prove_readability(
                    _request(path, "#FFFFFF", backing=backing))


if __name__ == "__main__":
    unittest.main(verbosity=2)
