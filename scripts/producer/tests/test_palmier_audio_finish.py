"""Authoritative Palmier-audio finish: safety, command, QC, and real media."""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from palmier import audio_finish as finish
from palmier.audio_finish import (AudioFinishError, FinishLimits, FinishReport,
                                  FinishSpec, VideoTiming,
                                  finish_authoritative_audio, verify_finished)


def _video_stream(frames: int = 240, rate: str = "24/1") -> dict:
    return {"codec_type": "video", "codec_name": "h264",
            "avg_frame_rate": rate, "r_frame_rate": rate,
            "nb_read_packets": str(frames), "duration": "10.000000"}


def _audio_stream(duration: str = "10.000000") -> dict:
    return {"codec_type": "audio", "codec_name": "aac",
            "sample_rate": "48000", "channels": 2,
            "channel_layout": "stereo", "duration": duration}


def _probe(*streams: dict) -> dict:
    return {"streams": list(streams)}


class AuthorityGateTests(unittest.TestCase):
    def test_frame_count_not_container_duration_is_visual_authority(self) -> None:
        stream = _video_stream(frames=300, rate="30000/1001")
        stream["duration"] = "999.0"
        timing = finish._video_timing(_probe(stream), "visual")
        self.assertEqual(timing, VideoTiming(300, Fraction(30000, 1001)))
        self.assertAlmostEqual(timing.duration_s, 10.01)

    def test_required_authority_streams_fail_loudly(self) -> None:
        with self.assertRaisesRegex(AudioFinishError, "no video stream"):
            finish._video_timing(_probe(_audio_stream()), "Palmier")
        with self.assertRaisesRegex(AudioFinishError, "no audio stream"):
            finish._stream_duration(None, "in-house master")

    def test_source_duration_delta_is_configurable_and_blocks_encode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            visual, master = Path(tmp, "palmier.mp4"), Path(tmp, "final.mp4")
            visual.write_bytes(b"visual")
            master.write_bytes(b"audio")
            spec = FinishSpec(str(visual), str(master), str(Path(tmp, "stage.mp4")),
                              FinishLimits(source_duration_delta_s=0.025))
            probes = [_probe(_video_stream()), _probe(_audio_stream("10.050"))]
            with patch.object(finish, "_probe_media", side_effect=probes), \
                    patch.object(finish, "_encode") as encode:
                with self.assertRaisesRegex(AudioFinishError,
                                            "authority duration mismatch"):
                    finish_authoritative_audio(spec)
            encode.assert_not_called()

    def test_refuses_input_or_existing_output_as_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            visual, master = Path(tmp, "palmier.mp4"), Path(tmp, "final.mp4")
            visual.write_bytes(b"visual")
            master.write_bytes(b"audio")
            same = FinishSpec(str(visual), str(master), str(visual))
            with self.assertRaisesRegex(AudioFinishError, "must be separate"):
                finish._validate_paths(same)
            stage = Path(tmp, "stage.mp4")
            stage.write_bytes(b"do-not-replace")
            existing = FinishSpec(str(visual), str(master), str(stage))
            with self.assertRaisesRegex(AudioFinishError, "refusing to replace"):
                finish._validate_paths(existing)
            self.assertEqual(stage.read_bytes(), b"do-not-replace")


class EncodeContractTests(unittest.TestCase):
    def test_command_copies_picture_and_finishes_only_master_audio(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp, "stage.mp4")
            spec = FinishSpec("palmier.mp4", "final.mp4", str(out))
            captured: list[str] = []

            def fake_run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
                captured.extend(cmd)
                out.write_bytes(b"new-stage")
                return subprocess.CompletedProcess(cmd, 0, "", "")

            with patch.object(finish, "_run", side_effect=fake_run):
                finish._encode(spec, VideoTiming(240, Fraction(24, 1)))
            self.assertIn("-n", captured)
            self.assertEqual(captured[captured.index("-map") + 1], "0:v:0")
            self.assertIn("1:a:0", captured)
            self.assertEqual(captured[captured.index("-c:v") + 1], "copy")
            self.assertEqual(captured[captured.index("-c:a") + 1], "aac")
            self.assertEqual(captured[captured.index("-ar") + 1], "48000")
            self.assertEqual(captured[captured.index("-ac") + 1], "2")
            self.assertEqual(captured[captured.index("-b:a") + 1], "256k")
            afilter = captured[captured.index("-af") + 1]
            self.assertIn("apad,atrim=start=0:end=10.000000000", afilter)
            self.assertIn("afade=t=out:st=9.980000000:d=0.020000000", afilter)

    def test_failed_qc_removes_new_stage_but_preserves_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            visual, master, stage = (Path(tmp, name) for name in
                                     ("palmier.mp4", "final.mp4", "stage.mp4"))
            visual.write_bytes(b"visual")
            master.write_bytes(b"master")
            probes = [_probe(_video_stream()), _probe(_audio_stream())]

            def fake_encode(_: FinishSpec, __: VideoTiming) -> None:
                stage.write_bytes(b"invalid-stage")

            with patch.object(finish, "_probe_media", side_effect=probes), \
                    patch.object(finish, "_encode", side_effect=fake_encode), \
                    patch.object(finish, "verify_finished",
                                 side_effect=AudioFinishError("bad QC")):
                with self.assertRaisesRegex(AudioFinishError, "bad QC"):
                    finish_authoritative_audio(
                        FinishSpec(str(visual), str(master), str(stage)))
            self.assertFalse(stage.exists())
            self.assertEqual(visual.read_bytes(), b"visual")
            self.assertEqual(master.read_bytes(), b"master")


class FinishedQCTests(unittest.TestCase):
    def _verify(self, probe: dict, loudness=(-14.2, -1.6),
                levels=(-20.0, -20.4)) -> FinishReport:
        with patch.object(finish, "_probe_media", return_value=probe), \
                patch.object(finish, "_is_faststart", return_value=True), \
                patch.object(finish, "_measure_loudness", return_value=loudness), \
                patch.object(finish, "_stereo_rms", return_value=levels):
            return verify_finished("stage.mp4", VideoTiming(240, Fraction(24, 1)),
                                   FinishLimits())

    def test_reports_all_delivery_measurements(self) -> None:
        report = self._verify(_probe(_video_stream(), _audio_stream("10.020")))
        self.assertAlmostEqual(report.video_duration_s, 10.0)
        self.assertAlmostEqual(report.audio_duration_s, 10.02)
        self.assertAlmostEqual(report.av_skew_s, 0.02)
        self.assertEqual(report.integrated_lufs, -14.2)
        self.assertEqual(report.true_peak_dbtp, -1.6)
        self.assertAlmostEqual(report.stereo_imbalance_db, 0.4)

    def test_collects_skew_loudness_peak_and_balance_failures(self) -> None:
        probe = _probe(_video_stream(), _audio_stream("10.200"))
        with self.assertRaises(AudioFinishError) as raised:
            self._verify(probe, loudness=(-16.0, -0.8), levels=(-20.0, -25.0))
        message = str(raised.exception)
        for expected in ("A/V skew", "integrated loudness", "true peak",
                         "stereo RMS imbalance"):
            self.assertIn(expected, message)

    def test_peak_must_be_strictly_below_minus_one(self) -> None:
        with self.assertRaisesRegex(AudioFinishError, "true peak"):
            self._verify(_probe(_video_stream(), _audio_stream()),
                         loudness=(-14.0, -1.0))


_HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


@unittest.skipUnless(_HAVE_FFMPEG, "needs ffmpeg and ffprobe")
class RealMediaFinishTests(unittest.TestCase):
    def _ffmpeg(self, *args: str) -> None:
        subprocess.run(["ffmpeg", "-y", "-v", "error", *args], check=True)

    def _video_hash(self, path: Path) -> str:
        proc = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0",
             "-c", "copy", "-f", "hash", "-hash", "sha256", "-"],
            capture_output=True, text=True, check=True)
        return proc.stdout.strip()

    def test_real_finish_preserves_picture_and_passes_audio_qc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            visual = Path(tmp, "palmier.mp4")
            master = Path(tmp, "final.mp4")
            stage = Path(tmp, "stage.mp4")
            self._ffmpeg("-f", "lavfi", "-i",
                         "color=c=blue:s=96x54:r=24:d=1.5",
                         "-an", "-c:v", "mpeg4", "-q:v", "5", str(visual))
            self._ffmpeg(
                "-f", "lavfi", "-i", "color=c=red:s=96x54:r=24:d=1.5",
                "-f", "lavfi", "-i",
                "sine=frequency=440:sample_rate=48000:duration=1.5",
                "-filter:a", "volume=4.1dB,pan=stereo|c0=c0|c1=c0",
                "-c:v", "mpeg4", "-q:v", "5", "-c:a", "aac",
                "-b:a", "256k", "-shortest", str(master))
            visual_before, master_before = visual.read_bytes(), master.read_bytes()

            report = finish_authoritative_audio(
                FinishSpec(str(visual), str(master), str(stage)))

            self.assertTrue(stage.exists())
            self.assertEqual(visual.read_bytes(), visual_before)
            self.assertEqual(master.read_bytes(), master_before)
            self.assertEqual(self._video_hash(stage), self._video_hash(visual))
            self.assertLessEqual(report.av_skew_s, 0.050)
            self.assertLessEqual(abs(report.integrated_lufs + 14.0), 1.0)
            self.assertLess(report.true_peak_dbtp, -1.0)
            self.assertLessEqual(report.stereo_imbalance_db, 3.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
