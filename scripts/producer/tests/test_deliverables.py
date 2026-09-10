"""P4 real, hash-bound publication-frame deliverables."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from graphics.deliverables import (
    DeliverableError,
    DeliverableRequest,
    create_frame_deliverable,
)

RECEIPT_HASH = hashlib.sha256(b"networkless-sandbox-receipt").hexdigest()


@unittest.skipUnless(
    shutil.which("ffmpeg") and shutil.which("ffprobe"),
    "ffmpeg and ffprobe are required",
)
class DeliverableTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "source.mov"
        self.ffmpeg = os.path.realpath(shutil.which("ffmpeg") or "")
        self.ffprobe = os.path.realpath(shutil.which("ffprobe") or "")
        subprocess.run([
            self.ffmpeg, "-nostdin", "-v", "error", "-f", "lavfi",
            "-i", "testsrc2=s=320x180:r=30:d=1", "-frames:v", "30",
            "-c:v", "ffv1", "-pix_fmt", "yuv420p", str(self.source),
        ], check=True, stdin=subprocess.DEVNULL)
        self.source_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.tools = {
            "node": self.ffmpeg,
            "browser": self.ffmpeg,
            "ffmpeg": self.ffmpeg,
            "ffprobe": self.ffprobe,
        }

    def _request(self, kind: str, frame: int) -> DeliverableRequest:
        return DeliverableRequest(
            kind=kind,
            source_path=str(self.source),
            source_sha256=self.source_hash,
            sandbox_receipt_hash=RECEIPT_HASH,
            frame_index=frame,
            output_path=str(self.root / f"{kind}.png"),
        )

    def _create(self, kind: str, frame: int) -> dict:
        with patch("graphics.deliverables.resolve_tools",
                   return_value=self.tools):
            return create_frame_deliverable(self._request(kind, frame))

    def test_thumbnail_cover_and_loop_frame_are_real_bound_pngs(self) -> None:
        for kind, frame in (
                ("thumbnail", 0), ("cover", 10), ("loop-frame", 29)):
            with self.subTest(kind=kind):
                receipt = self._create(kind, frame)
                output = self.root / f"{kind}.png"
                recorded = json.loads(
                    Path(f"{output}.receipt.json").read_text())
                self.assertEqual(output.read_bytes()[:8],
                                 b"\x89PNG\r\n\x1a\n")
                self.assertEqual(receipt, recorded)
                self.assertEqual(receipt["sourceSha256"], self.source_hash)
                self.assertEqual(receipt["sandboxReceiptHash"], RECEIPT_HASH)
                self.assertEqual(receipt["frameIndex"], frame)
                self.assertEqual(receipt["output"]["width"], 320)
                self.assertEqual(receipt["output"]["height"], 180)
                self.assertEqual(
                    receipt["output"]["sha256"],
                    hashlib.sha256(output.read_bytes()).hexdigest())

    def test_missing_frame_fails_without_publication_artifact(self) -> None:
        with self.assertRaisesRegex(DeliverableError, "does not exist"):
            self._create("cover", 30)
        self.assertFalse((self.root / "cover.png").exists())
        self.assertFalse((self.root / "cover.png.receipt.json").exists())

    def test_source_mutation_or_wrong_hash_fails_closed(self) -> None:
        request = self._request("thumbnail", 0)
        request = DeliverableRequest(
            **{**request.__dict__, "source_sha256": "0" * 64})
        with patch("graphics.deliverables.resolve_tools",
                   return_value=self.tools):
            with self.assertRaisesRegex(RuntimeError, "media proof"):
                create_frame_deliverable(request)
        self.assertFalse((self.root / "thumbnail.png").exists())

    def test_existing_or_wrong_extension_target_is_rejected(self) -> None:
        existing = self.root / "thumbnail.png"
        existing.write_bytes(b"operator-owned")
        with self.assertRaisesRegex(DeliverableError, "new file"):
            self._create("thumbnail", 0)
        request = DeliverableRequest(
            **{**self._request("cover", 0).__dict__,
               "output_path": str(self.root / "cover.jpg")})
        with patch("graphics.deliverables.resolve_tools",
                   return_value=self.tools):
            with self.assertRaisesRegex(DeliverableError, r"\.png"):
                create_frame_deliverable(request)


if __name__ == "__main__":
    unittest.main(verbosity=2)
