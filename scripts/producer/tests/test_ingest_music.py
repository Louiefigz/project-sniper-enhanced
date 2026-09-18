"""Music-ingest classification contracts."""

from __future__ import annotations

import sys
import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

PRODUCER_DIR = Path(__file__).resolve().parents[1]
if str(PRODUCER_DIR) not in sys.path:
    sys.path.insert(0, str(PRODUCER_DIR))

import ingest
import ingest_scan
from ingest_probe import MediaProbe, probe_media


def audio_probe(present: bool = True) -> MediaProbe:
    """A small ffprobe result for scanner tests."""
    return MediaProbe(
        duration=12.5,
        fps=None,
        vfr=False,
        width=None,
        height=None,
        rotation=0,
        audio_present=present,
        audio_channels=2 if present else None,
        audio_sample_rate=48000 if present else None,
    )


class ExactRateProbeTest(unittest.TestCase):
    def test_probe_preserves_canonical_r_frame_rate(self) -> None:
        payload = {
            "format": {"duration": "1.001"},
            "streams": [
                {
                    "codec_type": "video", "width": 1920, "height": 1080,
                    "r_frame_rate": "60000/2002",
                    "avg_frame_rate": "30000/1001",
                },
                {
                    "codec_type": "audio", "channels": 2,
                    "sample_rate": "48000",
                },
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "fixture.mp4"
            source.write_bytes(b"TEST ONLY media identity")
            with patch("ingest_probe.ffprobe_json", return_value=payload):
                result = probe_media(str(source))
        self.assertEqual(result.frame_rate, "30000/1001")


class MusicIngestTest(unittest.TestCase):
    def test_atomic_json_failure_preserves_previous_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "asset_manifest.json"
            destination.write_text('{"version":"old"}\n')
            with patch.object(ingest_scan.os, "replace", side_effect=OSError("disk busy")):
                with self.assertRaisesRegex(OSError, "disk busy"):
                    ingest_scan.atomic_write_json(destination, {"version": "new"})

            self.assertEqual(json.loads(destination.read_text()), {"version": "old"})
            self.assertEqual(list(destination.parent.glob(".asset_manifest.json.*.tmp")), [])

    def test_only_explicit_music_folder_is_classified_as_music(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            loose_audio = root / "interview.wav"
            track = root / "music" / "calm" / "bed.wav"
            loose_audio.touch()
            track.parent.mkdir(parents=True)
            track.touch()

            classified = ingest.classify_inputs(root)

            self.assertIn(loose_audio, classified.raw_files)
            self.assertEqual(classified.music_dir, root / "music")

    def test_music_scan_requires_supported_file_and_audio_stream(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            music_dir = Path(tmp) / "music"
            calm = music_dir / "calm" / "bed.wav"
            silent = music_dir / "silent.mp3"
            ignored = music_dir / "notes.txt"
            calm.parent.mkdir(parents=True)
            for path in (calm, silent, ignored):
                path.touch()

            probes = {
                str(calm): audio_probe(),
                str(silent): audio_probe(False),
            }
            with patch.object(ingest_scan, "probe_media", side_effect=lambda p: probes[p]):
                entries = ingest_scan.scan_music(music_dir)

            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["id"], "music-1")
            self.assertEqual(entries[0]["path"], str(calm))
            self.assertEqual(entries[0]["vibe"], ["calm"])
            self.assertEqual(entries[0]["source"], "library")


if __name__ == "__main__":
    unittest.main()
