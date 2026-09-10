"""Synthetic decoded-media acceptance for strict Audit B audio evidence."""
from __future__ import annotations

import shutil
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from audit.audit_checks import check_loudness
from audit.audit_probe import measure_loudness
from audit import audit_render
from audio import audio_mix_delivery
from audio.audio_mix_delivery import measure_delivery
from fingerprints import file_sha256
from test_audio_mix_without_media import _corrupt_audio_tail, _source
from test_program_mix_headroom_media import _ffmpeg


class AuditAudioPolicyTests(unittest.TestCase):
    """Policy boundaries share the same measurement implementation as music."""

    def test_peak_ceiling_is_hard_without_a_warning_band(self) -> None:
        for peak, expected in ((-1.5, "pass"), (-1.49, "fail"), (-0.6, "fail")):
            with self.subTest(peak=peak), mock.patch.object(
                    audio_mix_delivery, "_observe_final_audio",
                    return_value=({"input_i": "-14", "input_tp": str(peak)}, 0, "")):
                checks = check_loudness("synthetic-observation", True)
                self.assertEqual(checks[-1].status, expected)
                self.assertFalse(any(row.status == "warn" for row in checks))

    def test_nonfinite_and_missing_statistics_fail(self) -> None:
        for invalid in ("NaN", "Infinity", "-Infinity", None):
            with self.subTest(value=invalid), mock.patch.object(
                    audio_mix_delivery, "_observe_final_audio",
                    return_value=({"input_i": invalid, "input_tp": invalid}, 0, "")):
                self.assertEqual([row.status for row in check_loudness("mock", True)],
                                 ["pass", "fail", "fail"])

    def test_nonzero_exit_discards_valid_looking_json(self) -> None:
        result = mock.Mock(returncode=1, stderr='{"input_i":"-14","input_tp":"-2"}')
        with mock.patch.object(audio_mix_delivery.subprocess, "run", return_value=result):
            observed = measure_delivery("mock")
        self.assertFalse(observed["qualified"])
        self.assertIsNone(observed["integratedLufs"])
        self.assertFalse(observed["audioDecodeSucceeded"])

    def test_decode_timeout_and_os_failure_are_unqualified_evidence(self) -> None:
        for error in (subprocess.TimeoutExpired("ffmpeg", 0.001), OSError("unavailable")):
            with self.subTest(error=type(error).__name__), mock.patch.object(
                    audio_mix_delivery.subprocess, "run", side_effect=error) as run:
                observed = measure_delivery("mock")
                self.assertFalse(observed["qualified"])
                self.assertEqual(observed["audioDecodeExitCode"], -1)
                self.assertTrue(observed["audioDecodeError"])
                self.assertGreater(run.call_args.kwargs["timeout"], 0)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                     "installed FFmpeg and ffprobe required")
class AuditAudioMediaTests(unittest.TestCase):
    """Signal/codec evidence only, not listening or visual equivalence."""

    def test_clean_audio_has_explicit_complete_decode_proof(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = _source(Path(raw), (0.2, 0.2))
            checks = {row.name: row for row in check_loudness(str(source), True)}
            self.assertIn("audio_decode_complete", checks)
            self.assertTrue(all(row.status == "pass" for row in checks.values()))

    def test_corrupt_aac_tail_discards_plausible_partial_statistics(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = _source(Path(raw), (0.2, 0.2))
            _corrupt_audio_tail(source)
            self.assertEqual(measure_loudness(str(source)), (None, None))
            checks = check_loudness(str(source), True)
            self.assertTrue(any(row.status == "fail" for row in checks))

    def test_real_silence_and_no_audio_cannot_qualify(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            silent = _source(root, (0.0, 0.0))
            self.assertEqual([row.status for row in check_loudness(str(silent), True)],
                             ["pass", "fail", "fail"])
            picture = root / "no-audio.mp4"
            _ffmpeg(["-i", str(silent), "-map", "0:v", "-c:v", "copy", "-an", str(picture)])
            self.assertTrue(all(row.status == "fail"
                                for row in check_loudness(str(picture), False)))

    def test_audit_report_binds_real_candidate_and_shared_observation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            final = root / "final.mp4"
            _source(root, (0.2, 0.2)).rename(final)
            with mock.patch.object(audit_render, "file_sha256", wraps=file_sha256) as hashes:
                report = audit_render.run_audit(raw)
            value = audit_render.report_to_dict(report)
            self.assertEqual(value["audioDeliveryPolicyVersion"], 2)
            self.assertTrue(value["audioDelivery"]["qualified"])
            self.assertEqual(value["finalSha256"], file_sha256(str(final)))
            self.assertEqual(hashes.call_count, 2)
            self.assertTrue(any(row.name == "final_identity" and row.status == "pass"
                                for row in report.checks))
            json.dumps(value, allow_nan=False)

    def test_mutation_during_audit_fails_even_when_audio_numbers_pass(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            final = _source(root, (0.2, 0.2))
            original = file_sha256(str(final))
            probed = audit_render.Probed(raw, str(final), "short", {}, None,
                                         final_sha256=original)
            with final.open("ab") as handle:
                handle.write(b"owned synthetic mutation")
            report = audit_render._assemble(probed, [], [])
            self.assertEqual(report.overall, "fail")
            self.assertEqual(report.checks[-1].name, "final_identity")


if __name__ == "__main__":
    unittest.main(verbosity=2)
