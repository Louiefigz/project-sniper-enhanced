#!/usr/bin/env python3
"""Opt-in live acceptance for the native external-media admission jail."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from headless.admit_external_media_cli import admit_reference
from headless.external_media_probe import admit_external_media

ENABLED = os.environ.get("RUN_EXTERNAL_MEDIA_SANDBOX_TESTS") == "1"
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


@unittest.skipUnless(ENABLED and HAVE_FFMPEG, "opt-in native jail/ffmpeg acceptance")
class LiveExternalMediaProbeTests(unittest.TestCase):
    """Prove real full decode and representative adversarial rejection."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _store(self, name: str) -> Path:
        store = self.root / name
        store.mkdir()
        return store

    def test_valid_media_full_decodes_networkless(self) -> None:
        media = self.root / "valid.mp4"
        _ffmpeg(
            "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=1",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", str(media),
        )
        receipt = admit_external_media(str(media), str(self._store("valid")))
        self.assertTrue(receipt["decoded"]["decoded"])
        self.assertEqual(receipt["isolation"]["network"], "denied")
        self.assertEqual(receipt["isolation"]["processCreation"], "denied")
        self.assertTrue(all(run["sandboxed"] for run in receipt["isolation"]["decoderRuns"]))

    def test_reference_wrapper_retains_exact_video_authority(self) -> None:
        media = self.root / "reference.mp4"
        _ffmpeg(
            "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=24:duration=0.5",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(media),
        )
        authority = admit_reference(
            str(media), str(self._store("reference-store")))
        self.assertEqual(authority["mediaKind"], "timed-media")
        self.assertTrue(Path(authority["snapshotPath"]).is_file())
        self.assertTrue(Path(authority["receiptPath"]).is_file())
        self.assertEqual(
            Path(authority["snapshotPath"]).name,
            f"{authority['snapshotSha256']}.media",
        )

    def test_malformed_truncated_and_huge_dimensions_reject(self) -> None:
        malformed = self.root / "malformed.mp4"
        malformed.write_bytes(b"not-media")
        with self.assertRaisesRegex(RuntimeError, "decode rejected"):
            admit_external_media(
                str(malformed), str(self._store("malformed-store")))

        valid = self.root / "source.mp4"
        _ffmpeg(
            "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=30:duration=2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(valid),
        )
        truncated = self.root / "truncated.mp4"
        data = valid.read_bytes()
        truncated.write_bytes(data[:max(1, len(data) // 3)])
        with self.assertRaisesRegex(RuntimeError, "decode rejected"):
            admit_external_media(
                str(truncated), str(self._store("truncated-store")))

        huge = self.root / "huge.nut"
        _ffmpeg(
            "-f", "lavfi", "-i", "color=size=8194x2:rate=1:duration=1",
            "-c:v", "rawvideo", str(huge),
        )
        with self.assertRaisesRegex(RuntimeError, "DIMENSION_LIMIT"):
            admit_external_media(str(huge), str(self._store("huge-store")))

    def test_still_svg_and_font_use_bounded_nonexecuting_lanes(self) -> None:
        image = self.root / "still.png"
        _ffmpeg(
            "-f", "lavfi", "-i", "color=c=blue:size=64x64:rate=1",
            "-frames:v", "1", str(image),
        )
        image_receipt = admit_external_media(
            str(image), str(self._store("image-store")))
        self.assertEqual(
            image_receipt["decoded"]["facts"]["mediaKind"], "still-image")

        svg = self.root / "safe.svg"
        svg.write_text(
            '<svg width="64" height="32" xmlns="http://www.w3.org/2000/svg">'
            '<rect width="64" height="32"/></svg>',
            encoding="utf-8")
        svg_receipt = admit_external_media(
            str(svg), str(self._store("svg-store")))
        self.assertEqual(svg_receipt["decoded"]["facts"]["mediaKind"], "svg")

        font_source = Path(
            __file__).parents[3] / "assets" / "fonts" / "Inter-Regular.ttf"
        font = self.root / "font.ttf"
        shutil.copyfile(font_source, font)
        font_receipt = admit_external_media(
            str(font), str(self._store("font-store")))
        self.assertEqual(font_receipt["decoded"]["facts"]["mediaKind"], "font")


if __name__ == "__main__":
    unittest.main()
