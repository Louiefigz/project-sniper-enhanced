"""Fractional-clock and unsupported-timeline gates for audio-only delivery."""
from __future__ import annotations

import contextlib
import io
import shutil
import tempfile
import unittest
from pathlib import Path

from audio.audio_mix import MixSpec, run_audio_mix
from audio.audio_mix_picture import packet_signature
from audio.audio_mix_without import _probe
from fingerprints import file_sha256
from test_program_mix_headroom_media import RATE, _ffmpeg, _left_samples


def _source(root: Path, mode: str) -> Path:
    """Create actual NTSC, nonzero-start, or dropped-frame VFR source media."""
    path = root / "source.mp4"
    rate, duration = ("24000/1001", "3.003") if mode == "ntsc" else ("24", "3")
    command = ["-f", "lavfi", "-i", f"testsrc2=s=64x64:r={rate}:d={duration}",
               "-f", "lavfi", "-i", f"aevalsrc=0.2*sin(2*PI*1000*t):s={RATE}:d={duration}"]
    audio_filter = "pan=stereo|c0=c0|c1=c0"
    if mode == "offset":
        command += ["-vf", "setpts=PTS+1/TB"]
        audio_filter += ",asetpts=PTS+1/TB"
    if mode == "vfr":
        command += ["-vf", "select='not(eq(n,2))'"]
    command += ["-af", audio_filter, "-fps_mode", "passthrough", "-c:v", "libx264",
                "-preset", "ultrafast", "-c:a", "aac", "-b:a", "256k", str(path)]
    _ffmpeg(command)
    return path


def _music(root: Path) -> Path:
    """Generate a small deterministic fixture bed, not creator music."""
    path = root / "bed.wav"
    _ffmpeg(["-f", "lavfi", "-i", f"sine=f=180:r={RATE}:d=4",
             "-c:a", "pcm_f32le", str(path)])
    return path


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                     "installed FFmpeg and ffprobe required")
class MusicPictureClockMediaTests(unittest.TestCase):
    """A music-only edit cannot quantize, offset, or silently re-clock picture."""

    def test_both_ntsc_variants_keep_exact_picture_pts_and_presented_audio_samples(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source, music = _source(root, "ntsc"), _music(root)
            mixed, without = root / "with.mp4", root / "without.mp4"
            with contextlib.redirect_stdout(io.StringIO()):
                result = run_audio_mix(MixSpec(
                    str(source), str(music), str(mixed), out_without=str(without)))
            self.assertEqual(result["status"], "done", result)
            original = packet_signature(str(source), "v:0")
            self.assertEqual(len(original), 72)
            for path in (mixed, without):
                with self.subTest(path=path):
                    self.assertEqual(packet_signature(str(path), "v:0"), original)
                    audio = _probe(str(path))["audio"]
                    self.assertEqual(audio["codec_name"], "aac")
                    self.assertEqual(audio["duration_ts"], 144_144)
                    self.assertEqual(audio["time_base"], "1/48000")
                    self.assertEqual(audio["start_pts"], 0)
                    self.assertGreaterEqual(len(_left_samples(path)), 144_144)
                    self.assertLess(len(_left_samples(path)), 145_168)

    def test_nonzero_start_is_rejected_without_mutating_either_prior_output(self) -> None:
        self._assert_unsupported_timeline("offset")

    def test_actual_vfr_is_rejected_without_mutating_either_prior_output(self) -> None:
        self._assert_unsupported_timeline("vfr")

    def _assert_unsupported_timeline(self, mode: str) -> None:
        """First prove the fixture pathology, then require pre-publication failure."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source, music = _source(root, mode), _music(root)
            video = _probe(str(source))["video"]
            if mode == "offset":
                self.assertGreater(min(row[0] for row in packet_signature(str(source), "v:0")), 0)
            else:
                self.assertNotEqual(video["r_frame_rate"], video["avg_frame_rate"])
            mixed, without = root / "with.mp4", root / "without.mp4"
            shutil.copyfile(source, mixed)
            shutil.copyfile(source, without)
            before = (file_sha256(str(mixed)), file_sha256(str(without)))
            with contextlib.redirect_stdout(io.StringIO()):
                result = run_audio_mix(MixSpec(
                    str(source), str(music), str(mixed), out_without=str(without)))
            self.assertEqual(result["status"], "error", result)
            self.assertEqual(before, (file_sha256(str(mixed)), file_sha256(str(without))))
            self.assertFalse(list(root.glob(".audio-mix-candidate-*")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
