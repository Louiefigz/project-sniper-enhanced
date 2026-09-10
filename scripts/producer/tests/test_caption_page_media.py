"""Real-media alpha and timing checks for caption-page composition."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest

from captions.caption_page_media import (
    CaptionPageMediaContext,
    render_caption_page,
)
from fingerprints import file_sha256


class CaptionPageMediaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.mkdtemp(prefix="caption-page-media-")
        self.ffmpeg = shutil.which("ffmpeg")
        self.ffprobe = shutil.which("ffprobe")
        if not self.ffmpeg or not self.ffprobe:
            self.skipTest("ffmpeg/ffprobe unavailable")

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def _asset(self, name: str, drawbox: str) -> str:
        path = os.path.join(self.root, name)
        source = (
            "color=c=black@0.0:s=64x64:r=30,format=rgba,"
            f"{drawbox}:replace=1"
        )
        subprocess.run([
            self.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", source,
            "-frames:v", "3", "-an", "-c:v", "png", "-pix_fmt", "rgba",
            "-r", "30", "-fps_mode", "cfr", path,
        ], check=True)
        return path

    def _pixel(self, path: str, frame: int, point: tuple[int, int]) -> bytes:
        x, y = point
        process = subprocess.run([
            self.ffmpeg, "-v", "error", "-i", path, "-vf",
            f"select='eq(n,{frame})',crop=1:1:{x}:{y},format=rgba",
            "-frames:v", "1", "-f", "rawvideo", "-",
        ], check=True, capture_output=True)
        return process.stdout

    def test_page_preserves_transparency_pixels_and_exact_frame_offsets(
            self) -> None:
        red = self._asset(
            "red.mov",
            "drawbox=x=8:y=8:w=8:h=8:color=red@1:t=fill")
        green = self._asset(
            "green.mov",
            "drawbox=x=24:y=24:w=8:h=8:color=green@1:t=fill")
        media = lambda path: {
            "name": os.path.basename(path), "sha256": file_sha256(path)}
        page = {"startFrame": 0, "endFrameExclusive": 6, "inputs": [
            {"cueId": "red", "media": media(red), "sourceStartFrame": 0,
             "sourceEndFrameExclusive": 3, "pageStartFrame": 0},
            {"cueId": "green", "media": media(green), "sourceStartFrame": 0,
             "sourceEndFrameExclusive": 3, "pageStartFrame": 3},
        ]}
        manifest = {
            "fps": {"numerator": "30", "denominator": "1"},
            "destination": {"width": 64, "height": 64},
        }
        tools = {"ffmpeg": {"path": self.ffmpeg},
                 "ffprobe": {"path": self.ffprobe}}
        output = os.path.join(self.root, "page.mov")
        proof, _ = render_caption_page(
            page, output, CaptionPageMediaContext(
                manifest, self.root, tools))
        self.assertEqual(proof["stream"]["nb_read_frames"], "6")
        self.assertEqual(self._pixel(output, 0, (0, 0)), b"\x00\x00\x00\x00")
        self.assertEqual(self._pixel(output, 0, (8, 8)), b"\xff\x00\x00\xff")
        self.assertEqual(self._pixel(output, 3, (24, 24))[-1], 255)


if __name__ == "__main__":
    unittest.main()
