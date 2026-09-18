"""The private preview's float fit proves the UNPADDED source length before padding."""
from __future__ import annotations

import math
import os
import signal
import tempfile
import unittest
from array import array
from pathlib import Path
from unittest.mock import patch

from _common import *  # noqa: F401,F403

from audio.render_audio_bus import fit_float_samples

TOL = math.ceil(48_000 / (30000 / 1001)) + 1      # one NTSC frame + 1 sample = 1603


def _raw(path: Path, samples: int, value: float = 0.5) -> Path:
    data = array("f", [value, -value] * samples)
    path.write_bytes(data.tobytes())
    return path


class FloatFitTests(unittest.TestCase):
    def test_non_regular_or_aliased_inputs_are_rejected_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            raw = _raw(base / "raw.f32", 100)
            os.link(raw, base / "hardlink.f32")
            with self.assertRaisesRegex(RuntimeError, "regular unaliased"):
                fit_float_samples(raw, base / "fit.f32", 100, TOL)
            (base / "link.f32").symlink_to(raw)
            with self.assertRaises(OSError):
                fit_float_samples(base / "link.f32", base / "fit.f32", 100, TOL)
            os.mkfifo(base / "fifo.f32")
            previous = signal.signal(signal.SIGALRM, lambda *_: self.fail("FIFO read blocked"))
            signal.setitimer(signal.ITIMER_REAL, 0.5)
            try:
                with self.assertRaisesRegex(RuntimeError, "regular unaliased"):
                    fit_float_samples(base / "fifo.f32", base / "fit.f32", 100, TOL)
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)
                signal.signal(signal.SIGALRM, previous)

    def test_bad_counts_and_partial_stereo_frames_cannot_create_an_output(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            raw, target = _raw(Path(root, "raw.f32"), 100), Path(root, "fit.f32")
            for samples, tolerance in ((0, TOL), (-1, TOL), (True, TOL), (100, -1), (100, 1.5)):
                with self.subTest(samples=samples, tolerance=tolerance):
                    with self.assertRaisesRegex(RuntimeError, "valid integers"):
                        fit_float_samples(raw, target, samples, tolerance)
            raw.write_bytes(raw.read_bytes() + b"\x00")
            with self.assertRaisesRegex(RuntimeError, "more than one frame"):
                fit_float_samples(raw, target, 100, TOL)
            self.assertFalse(target.exists())

    def test_exact_fit_preserves_interior_and_never_overwrites_an_existing_target(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            raw, target = _raw(Path(root, "raw.f32"), 48000), Path(root, "fit.f32")
            self.assertEqual(fit_float_samples(raw, target, 48000, TOL), 0)
            self.assertEqual(target.read_bytes()[:-720 * 8], raw.read_bytes()[:-720 * 8])
            before = target.read_bytes()
            with self.assertRaises(FileExistsError):
                fit_float_samples(raw, target, 48000, TOL)
            self.assertEqual(target.read_bytes(), before)

    def test_empty_decode_is_not_a_short_quantized_audio_window(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            raw = _raw(Path(root, "empty.f32"), 0)
            target = Path(root, "fit.f32")
            with self.assertRaisesRegex(RuntimeError, "empty|missing"):
                fit_float_samples(raw, target, 1602, TOL)
            self.assertFalse(target.exists())

    def test_source_truncated_after_measurement_cannot_be_padded_as_silence(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            raw = _raw(Path(root, "raw.f32"), 48000)
            target = Path(root, "fit.f32")
            original = Path.open

            def open_then_truncate(path, *args, **kwargs):
                if path == target and args == ("xb",):
                    os.truncate(raw, 0)
                return original(path, *args, **kwargs)

            with patch.object(Path, "open", open_then_truncate):
                with self.assertRaisesRegex(RuntimeError, "changed|ended"):
                    fit_float_samples(raw, target, 48000, TOL)

    def test_short_by_more_than_one_frame_is_missing_audio_not_quantization(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            raw = _raw(Path(root, "raw.f32"), 48_000 - TOL - 1)
            with self.assertRaisesRegex(RuntimeError, "more than one frame"):
                fit_float_samples(raw, Path(root, "fit.f32"), 48_000, TOL)

    def test_within_one_frame_pads_or_truncates_and_declicks_the_tail(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            short = _raw(Path(root, "short.f32"), 48_000 - 1000)
            self.assertEqual(fit_float_samples(short, Path(root, "s.f32"), 48_000, TOL), 1000)
            self.assertEqual(os.path.getsize(Path(root, "s.f32")), 48_000 * 8)
            long = _raw(Path(root, "long.f32"), 48_000 + 1000)
            self.assertEqual(fit_float_samples(long, Path(root, "l.f32"), 48_000, TOL), -1000)
            fitted = array("f"); fitted.frombytes(Path(root, "l.f32").read_bytes())
            self.assertEqual(len(fitted), 48_000 * 2)
            self.assertLess(abs(fitted[-2]), 0.02)                 # last sample faded to ~0
            self.assertAlmostEqual(abs(fitted[2 * (48_000 - 720) - 2]), 0.5, places=3)   # untouched before the fade


if __name__ == "__main__":
    unittest.main(verbosity=2)
