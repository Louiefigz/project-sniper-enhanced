"""Rendered regression for steady-noise dialogue cleanup."""
from __future__ import annotations

import math
import os
import shutil
import subprocess
import tempfile
import unittest
import wave

import numpy as np

from _common import *  # noqa: F401,F403

from audio.audio_enhance import run_audio_enhance

RATE = 48_000


def _rms_db(samples: np.ndarray) -> float:
    """RMS dBFS with a numerical floor."""
    return 20.0 * math.log10(max(float(np.sqrt(np.mean(samples ** 2))), 1e-12))


def _write_noisy_voice(path: str) -> None:
    """Six seconds: steady room noise plus a deterministic speech proxy."""
    time = np.arange(RATE * 6) / RATE
    rng = np.random.default_rng(7)
    noise = (0.012 * rng.normal(size=time.size)
             + 0.015 * np.sin(2 * np.pi * 60 * time))
    active = ((time >= 2.0) & (time < 5.0)).astype(float)
    envelope = active * (0.55 + 0.45 * np.sin(2 * np.pi * 2.7 * time) ** 2)
    voice = envelope * (
        0.11 * np.sin(2 * np.pi * 180 * time)
        + 0.06 * np.sin(2 * np.pi * 360 * time)
        + 0.035 * np.sin(2 * np.pi * 720 * time))
    stereo = np.repeat(np.clip(noise + voice, -0.95, 0.95)[:, None], 2, axis=1)
    with wave.open(path, "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(np.asarray(stereo * 32767, dtype="<i2").tobytes())


def _decode(path: str) -> np.ndarray:
    """Decode an MP4 audio stream to mono float samples."""
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-map", "0:a:0",
         "-ac", "1", "-ar", str(RATE), "-f", "f32le", "pipe:1"],
        capture_output=True, check=True)
    return np.frombuffer(proc.stdout, dtype="<f4")


@unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
class AudioEnhanceRenderTests(unittest.TestCase):
    """The default longform preset must improve noise without eating speech."""

    def test_voice_preset_improves_steady_noise_snr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wav = os.path.join(tmp, "noisy.wav")
            source = os.path.join(tmp, "source.mp4")
            cleaned = os.path.join(tmp, "cleaned.mp4")
            _write_noisy_voice(wav)
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                 "color=c=black:s=160x90:r=24:d=6", "-i", wav,
                 "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264",
                 "-preset", "ultrafast", "-c:a", "aac", "-shortest", source],
                check=True)

            report = run_audio_enhance(source, "voice", cleaned)
            self.assertEqual(report["status"], "ok")
            before, after = _decode(source), _decode(cleaned)
            quiet = slice(round(0.5 * RATE), round(1.5 * RATE))
            speech = slice(round(2.5 * RATE), round(4.5 * RATE))
            snr_before = _rms_db(before[speech]) - _rms_db(before[quiet])
            snr_after = _rms_db(after[speech]) - _rms_db(after[quiet])

            self.assertGreaterEqual(snr_after - snr_before, 3.0)
            self.assertLessEqual(abs(_rms_db(after[speech])
                                     - _rms_db(before[speech])), 3.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
