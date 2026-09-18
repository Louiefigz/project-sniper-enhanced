"""Real-media integration for the legacy caption assembly path."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from audit.audit_captions import check_caption_authority
from captions.caption_assemble import project_caption_track
from compile_timeline import compile_plan
from cut_speed import probe_video_frames
from fingerprints import write_assembled_sidecar
from tests._caption_legacy_fixture import plan as caption_plan
from tests._caption_legacy_fixture import transcript as caption_transcript


def _fixture_video(path: str) -> None:
    command = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i",
        "color=c=0x203050:s=1080x1920:r=30000/1001:d=2",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:d=2",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", path,
    ]
    subprocess.run(command, check=True)


def _audio_hash(path: str) -> str:
    process = subprocess.run([
        "ffmpeg", "-v", "error", "-i", path, "-map", "0:a:0",
        "-c", "copy", "-f", "hash", "-hash", "sha256", "-",
    ], check=True, capture_output=True, text=True)
    return process.stdout.strip()


def _caption_band_luma(path: str) -> list[float]:
    process = subprocess.run([
        "ffmpeg", "-v", "error", "-i", path, "-vf",
        "crop=1080:500:0:1050,signalstats,"
        "metadata=print:key=lavfi.signalstats.YAVG:file=-",
        "-an", "-f", "null", "-",
    ], check=True, capture_output=True, text=True)
    return [
        float(value)
        for value in re.findall(
            r"lavfi\.signalstats\.YAVG=([0-9.]+)",
            process.stdout + process.stderr)
    ]


class CaptionLegacyMediaIntegrationTests(unittest.TestCase):
    def test_assemble_burns_after_base_and_copies_mastered_audio(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            plan = caption_plan()
            base = os.path.join(root, "base.mp4")
            final = os.path.join(root, "final.mp4")
            _fixture_video(base)
            shutil.copyfile(base, final)
            transcript = os.path.join(root, "transcript.json")
            Path(transcript).write_text(json.dumps(caption_transcript()))
            manifest = os.path.join(root, "manifest.json")
            Path(manifest).write_text(json.dumps({"sources": [{
                "id": "raw-a", "path": base,
                "transcriptPath": transcript,
            }]}))
            Path(root, "timeline_map.json").write_text(json.dumps(
                compile_plan(plan).to_dict()))
            job = SimpleNamespace(
                plan=plan, manifest=manifest, out=final, base=base)
            result = project_caption_track(job, lambda **_fields: None)
            self.assertEqual(result["cues"], 1)
            self.assertTrue(result["burned"])
            self.assertEqual(result["alphaShards"], 1)
            shards = json.loads(Path(root, "caption_shards.json").read_text())
            palmier = json.loads(Path(root, "caption_palmier.json").read_text())
            media_path = palmier["entries"][0]["mediaPath"]
            self.assertEqual(
                palmier["entries"][0]["mediaSha256"],
                shards["entries"][0]["media"]["sha256"])
            self.assertTrue(Path(media_path).is_file())
            self.assertEqual(
                probe_video_frames(base), probe_video_frames(final))
            self.assertEqual(_audio_hash(base), _audio_hash(final))
            self.assertNotEqual(
                Path(base).read_bytes(), Path(final).read_bytes())
            luma = _caption_band_luma(final)
            self.assertAlmostEqual(luma[0], luma[1], places=4)
            self.assertGreater(luma[2], luma[1] + 1)
            self.assertGreater(luma[35], luma[1] + 1)
            self.assertAlmostEqual(luma[36], luma[1], places=4)
            write_assembled_sidecar(final, plan)
            self.assertEqual(
                [row.status for row in check_caption_authority(root, plan)],
                ["pass"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
