"""Synthetic decoded music-tail regression through the ordinary mixing seam."""
from __future__ import annotations

import contextlib
import array
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from audio.audio_mix import MixSpec, _Ctx, _make_bed_stem, _normalize_context, duck_bed
from audio.audio_mix_bed import fit_length
from test_audio_mix_picture_media import _source, _music


def _samples(path: Path) -> int:
    """Read the actual float WAV clock, independent of container duration text."""
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(path)],
        capture_output=True, text=True, check=True, timeout=10)
    audio = json.loads(result.stdout)['streams'][0]
    if audio['time_base'] != '1/48000' or audio['codec_name'] != 'pcm_f32le':
        raise AssertionError(audio)
    return int(audio['duration_ts'])


def _tail_energy(path: Path) -> float:
    """A sample-count fix may not replace the last authored music with silence."""
    result = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(path),
        '-map', '0:a:0', '-ac', '1', '-c:a', 'pcm_f32le', '-f', 'f32le', '-'],
        capture_output=True, check=True, timeout=10)
    values = array.array('f', result.stdout)[-1024:]
    return sum(sample * sample for sample in values)


class OrdinaryDuckClockMediaTests(unittest.TestCase):
    """Keep real ordinary normalization and ducking; no mocked DSP or waveform."""

    def test_normalized_ntsc_program_preserves_every_fitted_bed_sample(self) -> None:
        root = Path(tempfile.mkdtemp(prefix='sniper-legacy-duck-clock-', dir='/private/tmp'))
        source, music = _source(root, 'ntsc'), _music(root)
        fitted = root / 'bed-fit.wav'
        result = fit_length(str(music), 3.003, str(fitted))
        self.assertTrue(result['ok'], result)
        self.assertEqual(_samples(fitted), 144144)
        ctx = _Ctx(MixSpec(str(source), str(music), str(root / 'final.mp4')),
            3.003, True, str(root))
        with contextlib.redirect_stdout(io.StringIO()):
            _normalize_context(ctx)
            ducked, depth = _make_bed_stem(ctx, str(fitted))
        print('retained synthetic ordinary duck fixture:', root, flush=True)
        self.assertIsNotNone(ducked, depth)
        self.assertEqual(_samples(Path(ducked)), 144144,
            'The bed must reach its authored end; do not pad a truncated duck output to pass.')
        self.assertGreater(_tail_energy(Path(ducked)), _tail_energy(fitted) * 0.01)

    def test_fractional_millisecond_length_fit_uses_exact_samples(self) -> None:
        with tempfile.TemporaryDirectory(dir='/private/tmp') as temporary:
            root = Path(temporary)
            music, fitted = _music(root), root / 'fitted.wav'
            duration = 144169 / 48000
            self.assertTrue(fit_length(str(music), duration, str(fitted))['ok'])
            self.assertEqual(_samples(fitted), 144169)

    def test_short_detector_releases_over_real_remaining_music_not_padded_output(self) -> None:
        with tempfile.TemporaryDirectory(dir='/private/tmp') as temporary:
            root = Path(temporary)
            music, fitted, detector = _music(root), root / 'fitted.wav', root / 'short-key.wav'
            self.assertTrue(fit_length(str(music), 3.003, str(fitted))['ok'])
            subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
                'sine=f=1000:r=48000:d=0.5', '-c:a', 'pcm_f32le', str(detector)],
                capture_output=True, check=True, timeout=10)
            output = root / 'ducked.wav'
            result = duck_bed(str(detector), str(fitted), str(output))
            self.assertTrue(result['ok'], result)
            self.assertEqual(_samples(output), 144144)
            self.assertGreater(_tail_energy(output), _tail_energy(fitted) * 0.8)


if __name__ == '__main__':
    unittest.main(verbosity=2)
