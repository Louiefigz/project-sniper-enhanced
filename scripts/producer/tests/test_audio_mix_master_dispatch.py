"""Shared mastering policy and bounded exact-sum measurement regressions."""
from __future__ import annotations

import math
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from audio import audio_mix, audio_mix_delivery, master
from fingerprints import file_sha256
from audit.audit_probe import measure_loudness as delivery_loudness
from test_program_mix_headroom_media import RATE, _ffmpeg, _left_samples


def _stats(integrated: float = -20, peak: float = -10, lra: float = 2) -> dict:
    """Build finite pass-one evidence with no loudnorm sentinel values."""
    return {"input_i": integrated, "input_tp": peak, "input_lra": lra,
            "input_thresh": -35, "target_offset": 0}


class SharedMasterDispatchTests(unittest.TestCase):
    """Policy tests use supplied measurements, not fake creator-quality claims."""

    def test_legal_linear_program_needs_no_static_dry_run(self) -> None:
        callback = mock.Mock(side_effect=AssertionError("unexpected dry run"))
        chain, note = master.build_pass2_afilter("unused", None, _stats(), callback)
        self.assertIn("linear=true", chain)
        self.assertIsNone(note)

    def test_positive_i_with_nonzero_lra_cannot_enter_illegal_linear_filter(self) -> None:
        callback = mock.Mock(return_value=master.AUDIO["lufs_target"])
        chain, note = master.build_pass2_afilter(
            "unused", None, _stats(2.65, 2.71, 2), callback)
        self.assertNotIn("measured_I=", chain)
        self.assertIn("volume=-16.65dB", chain)
        self.assertIn("alimiter", chain)
        self.assertIn("static gain", note or "")
        self.assertEqual(callback.call_count, 1)

    def test_all_illegal_measured_option_ranges_leave_the_linear_path(self) -> None:
        for field, value in (("input_i", 1), ("input_tp", 100),
                             ("input_lra", 100), ("input_thresh", 1),
                             ("target_offset", 100)):
            with self.subTest(field=field):
                evidence = {**_stats(), field: value}
                chain, note = master.build_pass2_afilter(
                    "unused", None, evidence, lambda _: master.AUDIO["lufs_target"])
                self.assertNotIn("linear=true", chain)
                self.assertIn("static gain", note or "")

    def test_quiet_high_crest_gain_trim_measures_callback_not_dialogue_alone(self) -> None:
        callback = mock.Mock(side_effect=[-15.5, -14.0])
        with mock.patch.object(master, "_measure_chain_lufs",
                               side_effect=AssertionError("wrong source measured")):
            chain, note = master.build_pass2_afilter(
                "dialogue-only-path", None, _stats(-35, -5, 4), callback)
        self.assertEqual(callback.call_count, 2)
        self.assertIn("volume=21.00dB", callback.call_args_list[0].args[0])
        self.assertIn("volume=22.50dB", chain)
        self.assertIn("static gain", note or "")

    def test_high_lra_uses_static_gain_even_when_peak_allows_linear_gain(self) -> None:
        callback = mock.Mock(return_value=-14.0)
        chain, note = master.build_pass2_afilter(
            "unused", None, _stats(-25, -20, 15), callback)
        self.assertIn("volume=11.00dB", chain)
        self.assertIn("static gain", note or "")
        self.assertEqual(callback.call_count, 1)

    def test_nonconvergent_measurement_has_a_strict_iteration_budget(self) -> None:
        callback = mock.Mock(return_value=-15.0)
        chain, note = master.build_pass2_afilter(
            "unused", None, _stats(-35, -5, 4), callback)
        self.assertEqual(callback.call_count, master.STATIC_MAX_TRIMS)
        self.assertIn("alimiter", chain)
        self.assertIsNotNone(note)
        # This is bounded DSP preparation, not successful final-output QC.

    def test_static_measurement_failure_does_not_trigger_unbounded_retries(self) -> None:
        callback = mock.Mock(return_value=None)
        chain, note = master.build_pass2_afilter(
            "unused", None, _stats(-35, -5, 4), callback)
        self.assertEqual(callback.call_count, 1)
        self.assertIn("alimiter", chain)
        self.assertIsNotNone(note)

    def test_mix_callback_keeps_bed_sum_float_until_measurement(self) -> None:
        result = mock.Mock(returncode=0, stderr="I: -14.0 LUFS")
        with mock.patch.object(audio_mix, "_run", return_value=result) as run:
            value = audio_mix._measure_mix_chain_lufs("program", "bed", 3, "volume=2dB")
        command = run.call_args.args[0]
        graph = command[command.index("-filter_complex") + 1]
        self.assertEqual(value, -14.0)
        self.assertIn("amix=inputs=2:duration=first:normalize=0", graph)
        self.assertIn("volume=2dB,ebur128=peak=true", graph)
        self.assertNotIn("sample_fmts=s32", graph)
        self.assertEqual(command[command.index("-map") + 1], "[out]")

    def test_delivery_requires_both_measured_loudness_and_true_peak(self) -> None:
        cases = (("-14", "-1.4"), ("-16", "-2"), ("nan", "-2"), ("-14", "inf"))
        for integrated, peak in cases:
            with self.subTest(integrated=integrated, peak=peak):
                with mock.patch.object(audio_mix_delivery, "_observe_final_audio",
                                       return_value=({"input_i": integrated, "input_tp": peak}, 0, "")):
                    evidence = audio_mix_delivery.measure_delivery("not-decoded-in-unit-test")
                self.assertFalse(evidence["qualified"])

    def test_failed_decode_cannot_qualify_plausible_partial_loudness_statistics(self) -> None:
        partial = ({"input_i": -14, "input_tp": -2}, 1, "corrupt final AAC packet")
        with mock.patch.object(audio_mix_delivery, "_observe_final_audio", return_value=partial):
            evidence = audio_mix_delivery.measure_delivery("unit-test-partial-decode")
        self.assertFalse(evidence["audioDecodeSucceeded"])
        self.assertFalse(evidence["qualified"])
        self.assertIsNone(evidence["integratedLufs"])


def _master_fixture(directory: Path, amplitude: str) -> tuple[Path, Path, Path]:
    """Generate 16 seconds of synthetic dynamics and a digitally silent bed."""
    source, bed, output = (directory / name for name in ("source.mkv", "bed.wav", "master.mp4"))
    tone = f"aevalsrc='{amplitude}*sin(2*PI*1000*t)':s={RATE}:d=16"
    _ffmpeg(["-f", "lavfi", "-i", "color=s=64x64:r=2:d=16",
             "-f", "lavfi", "-i", tone, "-af", "pan=stereo|c0=c0|c1=c0",
             "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "pcm_f32le", str(source)])
    _ffmpeg(["-f", "lavfi", "-i", f"anullsrc=r={RATE}:cl=stereo:d=16",
             "-c:a", "pcm_f32le", str(bed)])
    return source, bed, output


def _window_rms(samples: object, start: float, end: float) -> float:
    """Measure synthetic stationary windows, away from edit/codec boundaries."""
    values = samples[int(start * RATE):int(end * RATE)]
    return math.sqrt(math.fsum(value * value for value in values) / len(values))


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                     "installed FFmpeg and ffprobe required")
class SharedMasterMediaTests(unittest.TestCase):
    """Actual float-sum/AAC DSP checks, not subjective music intelligibility."""

    def test_high_lra_program_retains_its_quiet_loud_relationship(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source, bed, output = _master_fixture(
                Path(raw), "if(lt(mod(t,8),4),0.005,0.04)")
            measured = audio_mix._measure_mix(str(source), str(bed), 16)
            self.assertGreater(float(measured["input_lra"]), master.AUDIO["lra"])
            result = audio_mix.mix_master(str(source), str(bed), str(output), 16)
            self.assertTrue(result["ok"], result)
            self.assertFalse(result["linear"])
            self.assertIn("static gain", result["mastering_note"])
            self.assertEqual(result["mastering_decision"]["branch"], "static")
            samples = _left_samples(output)
            difference = 20 * math.log10(_window_rms(samples, 4.5, 7.5)
                                         / _window_rms(samples, 0.5, 3.5))
            self.assertAlmostEqual(difference, 20 * math.log10(8), delta=0.3)
            integrated, peak = delivery_loudness(str(output))
            self.assertAlmostEqual(integrated, master.AUDIO["lufs_target"], delta=1)
            self.assertLessEqual(peak, master.AUDIO["true_peak_dbtp"])

    def test_exhausted_high_crest_master_is_retained_unapproved_not_published(self) -> None:
        """Two bounded trims do not qualify this input; preserve prior output."""
        with tempfile.TemporaryDirectory() as raw:
            source, bed, output = _master_fixture(
                Path(raw), "if(lt(mod(t,1),0.005),0.8,0.005)")
            measured = audio_mix._measure_mix(str(source), str(bed), 16)
            projected = float(measured["input_tp"]) + master.AUDIO["lufs_target"] \
                - float(measured["input_i"])
            self.assertGreater(projected, master.AUDIO["loudnorm_tp_param"])
            shutil.copyfile(source, output)
            previous = file_sha256(str(output))
            result = audio_mix.mix_master(str(source), str(bed), str(output), 16)
            self.assertFalse(result["ok"], result)
            self.assertFalse(result["published"])
            self.assertEqual(result["mastering_decision"]["convergence"], "budget-exhausted")
            self.assertFalse(result["mastering_decision"]["selectedFilterMeasured"])
            self.assertIn("static gain", result["mastering_note"])
            self.assertEqual(file_sha256(str(output)), previous)
            candidate = result["unapprovedCandidate"]
            integrated, peak = delivery_loudness(candidate)
            self.assertGreater(abs(integrated - master.AUDIO["lufs_target"]), 1)
            self.assertLessEqual(peak, master.AUDIO["true_peak_dbtp"])
            self.assertFalse(result["delivery"]["qualified"])
            self.assertIn("LUFS residual", result["stderr"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
