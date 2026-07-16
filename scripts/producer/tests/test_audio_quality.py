"""Fast synthetic tests for the rendered-audio Audit B quality gates."""

import os
import json
import shutil
import subprocess
import tempfile
import unittest

from _common import *  # noqa: F401,F403

import numpy as np
from scipy import signal
from scipy.io import wavfile

from audit.audio_quality import check_audio_quality
from audit.audit_render import run_audit

RATE = 8000
DURATION = 4.0
MUSIC_PLAN = {"music": {"enabled": True}}


def _speech_like(duration: float = DURATION) -> np.ndarray:
    """Deterministic amplitude-modulated broadband proxy for connected speech."""
    rng = np.random.default_rng(72)
    t = np.arange(round(RATE * duration)) / RATE
    sos = signal.butter(4, [120, 3200], "bandpass", fs=RATE, output="sos")
    voice = signal.sosfilt(sos, rng.normal(size=t.size))
    envelope = 0.25 + 0.75 * (0.5 + 0.5 * np.sin(2 * np.pi * 2.7 * t)) ** 2
    voice = voice / np.sqrt(np.mean(np.square(voice))) * 0.08 * envelope
    return voice


def _write_wav(path: str, stereo: np.ndarray) -> None:
    """Write a clipped float fixture as PCM16."""
    pcm = np.clip(stereo, -0.98, 0.98)
    wavfile.write(path, RATE, np.asarray(pcm * 32767, dtype=np.int16))


def _mux(path: str, stereo: np.ndarray, video_duration: float = DURATION) -> None:
    """Mux finite color video with a synthetic WAV; do not trim audio tails."""
    wav = path + ".wav"
    _write_wav(wav, stereo)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
         f"color=c=navy:s=160x90:r=10:d={video_duration}", "-i", wav,
         "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264",
         "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", path],
        check=True)


def _by_name(path: str, plan: dict | None = None) -> dict:
    """Index quality results by check name."""
    return {item.name: item for item in check_audio_quality(path, plan or {})}


class AudioQualityTests(unittest.TestCase):
    """Clean controls pass while each targeted rendered defect hard-fails."""

    @classmethod
    def setUpClass(cls) -> None:
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            raise unittest.SkipTest("ffmpeg/ffprobe not on PATH")
        cls.tmp = tempfile.mkdtemp(prefix="producer-audio-quality-")
        cls.voice = _speech_like()
        cls.t = np.arange(cls.voice.size) / RATE

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _fixture(self, name: str, stereo: np.ndarray,
                 video_duration: float = DURATION) -> str:
        path = os.path.join(self.tmp, f"{name}.mp4")
        _mux(path, stereo, video_duration)
        return path

    def test_clean_speech_and_broadband_low_noise_pass(self) -> None:
        rng = np.random.default_rng(91)
        lowpass = signal.butter(4, 250, "lowpass", fs=RATE, output="sos")
        room = signal.sosfilt(lowpass, rng.normal(size=self.voice.size)) * 0.012
        stereo = np.column_stack([self.voice + room, self.voice + room])
        checks = _by_name(self._fixture("clean-broadband", stereo))
        self.assertEqual(checks["audio_av_timing"].status, "pass")
        self.assertEqual(checks["audio_channel_balance"].status, "pass")
        self.assertEqual(checks["audio_tonal_hum"].status, "pass")

    def test_post_picture_audio_fails_timing(self) -> None:
        voice = _speech_like(4.6)
        path = self._fixture("audio-tail", np.column_stack([voice, voice]), 4.0)
        result = _by_name(path)["audio_av_timing"]
        self.assertEqual(result.status, "fail")
        self.assertIn("post-picture audio", result.measured)

    def test_dead_dialogue_channel_fails_with_measured_delta(self) -> None:
        stereo = np.column_stack([self.voice, np.zeros_like(self.voice)])
        result = _by_name(self._fixture("dead-channel", stereo))["audio_channel_balance"]
        self.assertEqual(result.status, "fail")
        self.assertIn("median delta", result.measured)

    def test_stable_60_hz_hum_fails(self) -> None:
        hum = 0.05 * np.sin(2 * np.pi * 60 * self.t)
        stereo = np.column_stack([self.voice + hum, self.voice + hum])
        result = _by_name(self._fixture("hum-60", stereo))["audio_tonal_hum"]
        self.assertEqual(result.status, "fail")
        self.assertIn("60.0 Hz", result.measured)

    def test_hum_confined_to_final_seconds_still_fails(self) -> None:
        voice = _speech_like(6.0)
        timeline = np.arange(voice.size) / RATE
        hum = 0.05 * np.sin(2 * np.pi * 60 * timeline) * (timeline >= 3.0)
        stereo = np.column_stack([voice + hum, voice + hum])
        result = _by_name(self._fixture("ending-hum", stereo, 6.0))["audio_tonal_hum"]
        self.assertEqual(result.status, "fail")
        self.assertIn("60.0 Hz", result.measured)

    def test_stable_110_165_220_harmonics_fail(self) -> None:
        tones = sum(np.sin(2 * np.pi * hz * self.t) for hz in (110, 165, 220))
        stereo = np.column_stack([self.voice + 0.04 * tones] * 2)
        result = _by_name(self._fixture("hum-harmonics", stereo))["audio_tonal_hum"]
        self.assertEqual(result.status, "fail")
        self.assertRegex(result.measured, r"(110|165|220)\.0 Hz")

    def test_quiet_music_under_continuing_voice_passes_ending(self) -> None:
        left = self.voice + 0.008 * np.sin(2 * np.pi * 330 * self.t)
        right = self.voice + 0.008 * np.sin(2 * np.pi * 440 * self.t)
        result = _by_name(self._fixture("quiet-bed", np.column_stack([left, right])),
                          MUSIC_PLAN)["audio_ending_mix"]
        self.assertEqual(result.status, "pass")

    def test_music_dominant_ending_fails(self) -> None:
        gate = (self.t >= 2.5).astype(float)
        left_music = (np.sin(2 * np.pi * 330 * self.t)
                      + np.sin(2 * np.pi * 550 * self.t)) * 0.14 * gate
        right_music = (np.sin(2 * np.pi * 440 * self.t)
                       + np.sin(2 * np.pi * 660 * self.t)) * 0.14 * gate
        stereo = np.column_stack([self.voice + left_music,
                                  self.voice + right_music])
        result = _by_name(self._fixture("dominant-ending", stereo),
                          MUSIC_PLAN)["audio_ending_mix"]
        self.assertEqual(result.status, "fail")
        self.assertIn("tonal/diffuse", result.measured)

    def test_stereo_bed_only_tail_fails_when_body_had_voice(self) -> None:
        gate = (self.t >= 2.5).astype(float)
        voice = self.voice.copy()
        voice[self.t >= 2.5] = 0.0
        stereo = np.column_stack([
            voice + 0.12 * gate * np.sin(2 * np.pi * 330 * self.t),
            voice + 0.12 * gate * np.sin(2 * np.pi * 440 * self.t)])
        result = _by_name(self._fixture("bed-only-tail", stereo),
                          MUSIC_PLAN)["audio_ending_mix"]
        self.assertEqual(result.status, "fail")

    def test_audit_b_runs_the_rendered_audio_quality_gate(self) -> None:
        out_dir = os.path.join(self.tmp, "audit-b-integration")
        os.makedirs(out_dir)
        final = os.path.join(out_dir, "final.mp4")
        _mux(final, np.column_stack([self.voice, self.voice]))
        with open(os.path.join(out_dir, "edit_plan.json"), "w") as handle:
            json.dump({"target": {"mode": "longform"},
                       "music": {"enabled": False}}, handle)
        names = {check.name for check in run_audit(out_dir).checks}
        self.assertTrue({"audio_av_timing", "audio_channel_balance",
                         "audio_tonal_hum", "audio_ending_mix"} <= names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
