"""Rendered music-mix regressions: the picture timeline owns audio length."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from fractions import Fraction
from unittest import mock

from _common import *  # noqa: F401,F403
from audio.audio_mix import MixSpec, run_audio_mix
from audio import audio_mix_bed
from audio.audio_mix_bed import probe_video_duration
import render as renderer


def _stream_durations(path: str) -> tuple[float, float]:
    cmd = ["ffprobe", "-v", "error", "-show_entries",
           "stream=codec_type,duration", "-of", "json", path]
    data = json.loads(subprocess.run(
        cmd, capture_output=True, text=True, check=True).stdout)
    by_type = {s["codec_type"]: float(s["duration"])
               for s in data["streams"]}
    return by_type["video"], by_type["audio"]


class AudioMixAuthorityTests(unittest.TestCase):
    """Picture timing is frame-count/rational-rate authority, not metadata."""

    def test_declared_stream_duration_cannot_override_picture_timeline(self) -> None:
        payload = {
            "streams": [{
                "avg_frame_rate": "30000/1001",
                "r_frame_rate": "30000/1001",
                "nb_read_packets": "300",
                "duration": "999.000000",
            }],
        }
        completed = subprocess.CompletedProcess(
            ["ffprobe"], 0, json.dumps(payload), "")
        with mock.patch.object(audio_mix_bed, "run", return_value=completed) as run:
            duration = probe_video_duration("master.mp4")

        self.assertAlmostEqual(duration or 0.0, 10.01, places=9)
        command = run.call_args.args[0]
        self.assertIn("-count_packets", command)
        self.assertNotIn("stream=duration", command)

    def test_non_cfr_rate_evidence_fails_closed(self) -> None:
        payload = {
            "streams": [{
                "avg_frame_rate": "24000/1001",
                "r_frame_rate": "24/1",
                "nb_read_packets": "240",
            }],
        }
        completed = subprocess.CompletedProcess(
            ["ffprobe"], 0, json.dumps(payload), "")
        with mock.patch.object(audio_mix_bed, "run", return_value=completed):
            self.assertIsNone(probe_video_duration("vfr.mp4"))


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                     "ffmpeg/ffprobe required")
class AudioMixDurationTests(unittest.TestCase):
    """A longer source-audio tail must never survive past the picture."""

    def test_mix_trims_audio_to_video_stream_not_container(self) -> None:
        with tempfile.TemporaryDirectory(prefix="audio-mix-tail-") as tmp:
            source = os.path.join(tmp, "source.mp4")
            music = os.path.join(tmp, "music.wav")
            output = os.path.join(tmp, "mixed.mp4")
            subprocess.run([
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc2=s=320x180:r=24:d=2",
                "-f", "lavfi", "-i", "sine=f=220:r=48000:d=3",
                "-c:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p", "-c:a", "aac", source,
            ], check=True)
            subprocess.run([
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "sine=f=110:r=48000:d=1",
                "-c:a", "pcm_f32le", music,
            ], check=True)

            result = run_audio_mix(MixSpec(
                video_in=source, music=music, out_with=output, duck=True))

            self.assertEqual(result["status"], "done", result)
            self.assertAlmostEqual(probe_video_duration(source) or 0, 2.0, places=2)
            video_s, audio_s = _stream_durations(output)
            self.assertLessEqual(abs(audio_s - video_s), 0.05)
            self.assertLessEqual(audio_s, 2.05)

    def test_dialogue_mix_cannot_disable_sidechain_ducking(self) -> None:
        with tempfile.TemporaryDirectory(prefix="audio-mix-duck-") as tmp:
            source = os.path.join(tmp, "source.mp4")
            music = os.path.join(tmp, "music.wav")
            subprocess.run([
                "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                "color=c=black:s=160x90:r=24:d=1", "-f", "lavfi", "-i",
                "sine=f=220:r=48000:d=1", "-c:v", "libx264", "-c:a", "aac",
                "-shortest", source], check=True)
            subprocess.run([
                "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                "sine=f=110:r=48000:d=1", "-c:a", "pcm_f32le", music],
                check=True)

            result = run_audio_mix(MixSpec(
                video_in=source, music=music,
                out_with=os.path.join(tmp, "mixed.mp4"), duck=False))

            self.assertEqual(result["status"], "error")
            self.assertIn("cannot be disabled", result["error"])

    def test_four_part_aac_padding_cannot_extend_picture_or_round_ntsc(self) -> None:
        with tempfile.TemporaryDirectory(prefix="audio-aac-tail-") as tmp:
            source = os.path.join(tmp, "source.mp4")
            mezz = os.path.join(tmp, "mezz.mp4")
            final = os.path.join(tmp, "final.mp4")
            parts = os.path.join(tmp, "parts")
            os.makedirs(parts)
            subprocess.run([
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i",
                "testsrc2=s=320x180:r=24000/1001:d=2",
                "-f", "lavfi", "-i", "sine=f=220:r=48000:d=2",
                "-c:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", source,
            ], check=True)
            plan = {"target": {"mode": "longform"}, "cutTrack": [
                {"sourceId": "raw", "start": start, "end": start + 0.2}
                for start in (0.0, 0.4, 0.8, 1.2)
            ]}
            manifest = {"sources": [{"id": "raw", "path": source}]}

            cs.render_cut_speed(plan, manifest, mezz, parts)
            before = cs.probe_video_frames(mezz)
            ctx = renderer.RenderCtx(plan, manifest, tmp, tmp)
            result = renderer.master_stage(
                ctx, mezz, None, ct.compile_plan(plan).output_duration)

            self.assertEqual(result["status"], "done", result)
            self.assertEqual(cs.probe_video_frames(final), before)
            actual_rate = cs.probe_video(final)["r_frame_rate"]
            self.assertEqual(Fraction(actual_rate), Fraction("24000/1001"))
            video_s, audio_s = _stream_durations(final)
            self.assertLessEqual(abs(audio_s - video_s), 0.05)


if __name__ == "__main__":
    unittest.main(verbosity=2)
