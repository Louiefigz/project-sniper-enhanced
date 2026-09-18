"""Exact ordered-part elementary video proof tests."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest

from _common import *  # noqa: F401,F403

from fractions import Fraction

from cut_elementary_proof import prove_video_sequence
from cut_speed import Profile, concat_parts

# Production parts: B-frame-free video (packet order == presentation order)
# with float PCM audio; concat_parts rebuilds the joined clock from the index.
PROFILE = Profile(160, 90, Fraction(24), "yuv420p")


class CutElementaryProofTests(unittest.TestCase):
    """Prove an actual stream-copy concat and reject reordered parts."""

    def setUp(self) -> None:
        if shutil.which("ffmpeg") is None:
            self.skipTest("ffmpeg unavailable")
        self.root = tempfile.mkdtemp(prefix="cut-elementary-proof-")
        self.parts = [
            os.path.join(self.root, "part-0.mp4"),
            os.path.join(self.root, "part-1.mp4"),
        ]
        self._part(self.parts[0], "red")
        self._part(self.parts[1], "blue")

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def _part(self, path: str, color: str) -> None:
        subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
            f"color={color}:s=160x90:r=24:d=0.5", "-f", "lavfi", "-t", "0.5",
            "-i", "anullsrc=r=48000:cl=stereo", "-c:v", "libx264", "-bf", "0",
            "-pix_fmt", "yuv420p", "-c:a", "pcm_f32le", path,
        ], check=True)

    def test_stream_copy_concat_equals_ordered_parts(self) -> None:
        concat = os.path.join(self.root, "concat.mp4")
        concat_parts(self.parts, concat, self.root, PROFILE)
        proof = prove_video_sequence(self.parts, concat)
        self.assertEqual(proof.ordered_parts, proof.concat)
        self.assertEqual(
            proof.ordered_parts.size_bytes,
            sum(row.size_bytes for row in proof.parts))

    def test_reordered_concat_is_rejected(self) -> None:
        concat = os.path.join(self.root, "reversed.mp4")
        concat_parts(list(reversed(self.parts)), concat, self.root, PROFILE)
        with self.assertRaisesRegex(RuntimeError, "ordered encoded parts"):
            prove_video_sequence(self.parts, concat)


if __name__ == "__main__":
    unittest.main(verbosity=2)
