"""Qualify shorter decoder pre-roll against exact CRF mezzanine parts."""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import cut_speed
from fingerprints import file_sha256


class CutPreseekMediaTests(unittest.TestCase):
    """Real AAC/HEVC cuts include fractional clocks, short windows and J-cuts."""

    def _source(self, root: Path, fps: str) -> Path:
        """Create bounded moving picture and audio; no user footage is modified."""
        source = root / "source.mp4"
        command = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                   f"testsrc2=s=320x180:r={fps}:d=15", "-f", "lavfi", "-i",
                   "sine=f=443:r=48000:d=15", "-c:v", "libx265", "-preset", "ultrafast",
                   "-x265-params", "pools=1:frame-threads=1:log-level=error",
                   "-g", "120", "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)]
        subprocess.run(command, check=True, capture_output=True, timeout=60)
        return source

    def _render(self, root: Path, source: Path, pad: float) -> dict:
        """Compare complete part bytes at a stable cumulative frame/sample clock."""
        directory = root / f"pad-{pad}"
        directory.mkdir()
        plan = {"cutTrack": [
            {"sourceId": "s", "start": 10.437, "end": 11.157, "speed": 1},
            {"sourceId": "s", "start": 12.083, "end": 12.983, "speed": 1.25, "audioLeadMs": 120},
            {"sourceId": "s", "start": 13.221, "end": 14.413, "speed": 1}]}
        manifest = {"sources": [{"id": "s", "path": str(source)}]}
        started = time.monotonic()
        with patch.object(cut_speed, "PRESEEK_PAD_S", pad), contextlib.redirect_stdout(io.StringIO()):
            result = cut_speed.render_cut_speed(plan, manifest, str(directory / "mezz.mp4"), str(directory))
        seconds = time.monotonic() - started
        parts = sorted(directory.glob("part_*.mp4"))
        return {"seconds": seconds, "videoFrames": result["videoFrames"],
                "parts": [file_sha256(str(path)) for path in parts],
                "retimedStreams": self._stream_hashes(parts[1])}

    def _stream_hashes(self, path: Path) -> dict:
        """Separate packet picture equality from lossless float-audio equality."""
        result = {}
        for stream, codec in (("v", "copy"), ("a", "pcm_f32le")):
            proc = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path),
                                   "-map", f"0:{stream}:0", f"-c:{stream}", codec,
                                   "-f", "hash", "-hash", "sha256", "-"],
                                  check=True, capture_output=True, text=True, timeout=30)
            result[stream] = proc.stdout.strip()
        return result

    def test_qualified_pad_preserves_parts_at_integer_and_fractional_fps(self) -> None:
        if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
            self.skipTest("ffmpeg/ffprobe unavailable")
        for fps in ("30", "30000/1001"):
            with self.subTest(fps=fps), tempfile.TemporaryDirectory(prefix="sniper-preseek-") as temp:
                root = Path(temp)
                source = self._source(root, fps)
                baseline = self._render(root, source, 10.0)
                candidate = self._render(root, source, 2.0)
                print(json.dumps({"preseekQualification": fps, "baseline": baseline, "candidate": candidate}))
                self.assertEqual(candidate["videoFrames"], baseline["videoFrames"])
                self.assertEqual(candidate["parts"], baseline["parts"])


if __name__ == "__main__":
    unittest.main()
