"""Opt-in real HTTP admission of supplied clip and raster formats in one additive rescan."""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from _supporting_rescan_http_fixture import HttpFixture
from fingerprints import file_sha256
from test_supporting_rescan_media import _ffmpeg, _recording


def supporting_formats(root: Path) -> dict[str, tuple[Path, str]]:
    """Generate real containers/codecs, never rename bytes to simulate another format."""
    video = root / "provided.mp4"
    _recording(video, "red")
    movie = root / "provided.mov"
    _ffmpeg(["-i", str(video), "-c", "copy", str(movie)])
    image = root / "provided.jpeg"
    webp = root / "provided.webp"
    _ffmpeg(["-f", "lavfi", "-i", "color=c=green:s=80x80", "-frames:v", "1", "-threads", "1", str(image)])
    _ffmpeg(["-f", "lavfi", "-i", "color=c=yellow:s=80x80", "-frames:v", "1", "-threads", "1", str(webp)])
    return {"MP4": (video, "video"), "MOV": (movie, "video"),
            "JPEG": (image, "image"), "WebP": (webp, "image")}


@unittest.skipUnless(os.environ.get("RUN_SUPPORTING_RESCAN_HTTP_TESTS") == "1",
                     "opt-in supervised real Next HTTP and Docker admission acceptance")
class SupportingRescanHttpFormatsMediaTests(HttpFixture):
    """Exercise every remaining app intake format using actual full-decode admission."""

    def stage_file(self, selected: Path) -> dict:
        """Prove HTTP staging copies exact bytes and cannot publish before admission."""
        status, result = self.post("/api/producer/supporting-media", {"dir": str(self.directory), "inputPath": str(selected)})
        self.assertEqual(status, 200, result)
        self.assertEqual(result["status"], "staged-awaiting-sandbox-admission")
        self.assertEqual(result["sha256"], file_sha256(str(selected)))
        self.assertEqual(result["sha256"], file_sha256(result["path"]))
        self.unchanged()
        return result

    def test_video_and_raster_formats_publish_together_without_changing_transcripts(self) -> None:
        self.initial_project()
        formats = supporting_formats(self.fixture)
        staged = {name: self.stage_file(path) for name, (path, _kind) in formats.items()}
        status, events = self.rescan()
        self.assertEqual(status, 200, events)
        self.assert_published(events, staged["MP4"])
        manifest = json.loads(self.manifest_path.read_text())
        rows = {row["originalPath"]: row for row in manifest["broll"]}
        self.assertEqual(len(rows), 4)
        self.assertEqual(len({row["id"] for row in rows.values()}), 4)
        for name, (_path, kind) in formats.items():
            receipt = staged[name]
            row = rows[receipt["path"]]
            self.assertEqual(row["kind"], kind)
            self.assertEqual(row["sourceSha256"], receipt["sha256"])
            self.assertEqual(file_sha256(row["path"]), receipt["sha256"])
            self.assertIsNone(row["hasBurnedText"])
            if kind == "video":
                self.assertGreaterEqual(row["duration"], 1)
                self.assertIsNone(row["hasSpeech"], "Tone audio is not proof of speech")
            else:
                self.assertEqual(row["resolution"], [80, 80])
                self.assertIs(row["hasSpeech"], False)


if __name__ == "__main__":
    unittest.main()
