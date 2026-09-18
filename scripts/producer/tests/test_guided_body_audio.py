"""Bounded TEST signal selection/determinism; real encoded checks live separately."""
from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from _cut_preview_fixture import VOICE_BED_EXPR, _synthesize_longform
from _guided_body_audio import RATE, write_calibration_bed
from _guided_body_program import BODY_PROGRAM
from _guided_longform_program import build_program


class GuidedBodyAudioTests(unittest.TestCase):
    """Only the explicitly named new TEST source changes; no gate is patched."""

    def test_pcm_is_repeatable_exact_length_and_independent_of_chunk_partition(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sniper-calibration-unit-") as root:
            first, second = Path(root) / "a.wav", Path(root) / "b.wav"
            write_calibration_bed(first, 1.125)
            with patch("_guided_body_audio.CHUNK_SAMPLES", 12000):
                write_calibration_bed(second, 1.125)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with wave.open(str(first)) as audio:
                self.assertEqual((audio.getnchannels(), audio.getsampwidth(), audio.getframerate()), (1, 2, RATE))
                self.assertEqual(audio.getnframes(), 54000)

    def test_invalid_or_existing_output_rejects_without_replacing_bytes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sniper-calibration-bounds-") as root:
            path = Path(root) / "bed.wav"
            for duration in (True, 0, -1, float("nan"), float("inf"), 361):
                with self.assertRaises(ValueError):
                    write_calibration_bed(path, duration)
            path.write_bytes(b"TEST existing bytes")
            with self.assertRaises(FileExistsError):
                write_calibration_bed(path, 1)
            self.assertEqual(path.read_bytes(), b"TEST existing bytes")

    def test_guard_interrupt_retains_partial_audio_and_does_not_continue(self) -> None:
        observations = 0
        def guard() -> None:
            nonlocal observations
            observations += 1
            if observations == 3:
                raise RuntimeError("TEST original deadline")
        with tempfile.TemporaryDirectory(prefix="sniper-calibration-stop-") as root:
            path = Path(root) / "bed.wav"
            with self.assertRaisesRegex(RuntimeError, "deadline"):
                write_calibration_bed(path, 3, guard)
            with wave.open(str(path)) as audio:
                self.assertEqual(audio.getnframes(), RATE)

    def test_old_longform_synthesis_keeps_exact_historical_tonal_source_arguments(self) -> None:
        for duration in (96, 312):
            self._synthesis(build_program(duration), False)

    def test_only_explicit_body_variant_selects_new_bed(self) -> None:
        self._synthesis(build_program(312, BODY_PROGRAM), True)

    def _synthesis(self, program: dict, new_bed: bool) -> None:
        with tempfile.TemporaryDirectory(prefix="sniper-calibration-select-") as root:
            directory = Path(root)
            pulse = directory / "pulses.wav"
            pulse.touch()
            pair = directory / "raw.mp4", directory / "silent.mp4"
            with patch("_cut_preview_fixture._pulse_track", return_value=pulse), \
                    patch("_cut_preview_fixture.ffmpeg") as ffmpeg, \
                    patch("_guided_body_audio.write_calibration_bed") as bed:
                _synthesize_longform(directory, ["TEST-video-input"], pair, program)
            args = ffmpeg.call_args_list[0].args[0]
            if new_bed:
                bed.assert_called_once_with(directory / "TEST-non-speech-calibration.wav",
                    program["meta"]["sourceDurationS"] + 1)
                self.assertEqual(args[3:5], ["-i", str(directory / "TEST-non-speech-calibration.wav")])
            else:
                bed.assert_not_called()
                self.assertEqual(args[3:7], ["-f", "lavfi", "-i",
                    f"aevalsrc='{VOICE_BED_EXPR}':s=48000:d={program['meta']['sourceDurationS'] + 1}"])
            self.assertEqual(args[args.index("-filter_complex") + 1], "[1:a][2:a]amix=inputs=2:duration=first:normalize=0[a]")
            self.assertEqual(ffmpeg.call_args_list[1].args[0][0], "TEST-video-input")


if __name__ == "__main__":
    unittest.main(verbosity=2)
