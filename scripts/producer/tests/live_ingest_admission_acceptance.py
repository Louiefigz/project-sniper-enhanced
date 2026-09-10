#!/usr/bin/env python3
"""Opt-in live raw+b-roll+music Producer-ingest sandbox acceptance."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ingest
from ingest_admission_contract import verify_source_set_binding

ENABLED = os.environ.get("RUN_P0_INGEST_ADMISSION_TESTS") == "1"
HAVE_FFMPEG = shutil.which("ffmpeg") is not None


def _ffmpeg(*args: str) -> None:
    subprocess.run(
        [shutil.which("ffmpeg") or "ffmpeg", "-nostdin", "-v", "error",
         "-y", *args],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=True,
    )


@unittest.skipUnless(ENABLED and HAVE_FFMPEG, "opt-in Docker/ffmpeg acceptance")
class LiveIngestAdmissionTests(unittest.TestCase):
    """Prove the product convergence point consumes three admitted snapshots."""

    def test_raw_broll_and_music_bind_one_source_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            incoming, output = root / "incoming", root / "output"
            (incoming / "broll").mkdir(parents=True)
            (incoming / "music").mkdir()
            _ffmpeg(
                "-f", "lavfi", "-i", "color=c=blue:s=160x90:r=24:d=0.5",
                "-f", "lavfi", "-i",
                "sine=frequency=440:sample_rate=48000:duration=0.5",
                "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", str(incoming / "take.mp4"))
            _ffmpeg(
                "-f", "lavfi", "-i", "color=c=red:s=80x80",
                "-frames:v", "1", str(incoming / "broll" / "shot.png"))
            _ffmpeg(
                "-f", "lavfi", "-i",
                "sine=frequency=220:sample_rate=48000:duration=0.5",
                str(incoming / "music" / "bed.wav"))
            with patch("ingest.scan_builtin_music", return_value=[]):
                manifest = ingest.build_manifest(
                    incoming, output, no_transcribe=True)
            verify_source_set_binding(manifest, output)
            rows = [
                *manifest["sources"], *manifest["broll"], *manifest["music"]]
            self.assertEqual(manifest["sourceSetAdmission"]["entryCount"], 3)
            self.assertEqual(len(rows), 3)
            self.assertTrue(all(
                str(output / ".sniper-external-media") in row["path"]
                for row in rows))


if __name__ == "__main__":
    unittest.main()
