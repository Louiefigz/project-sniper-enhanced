"""Processing receipts distinguish selected gain, measured convergence and approval."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from audio import master
from audio.mastering_filter import MasterFilterInput, select_master_filter
from audio.mastering_profile import NATIVE_SHORT_MASTERING_PROFILE


def measured(integrated: float = -35, peak: float = -5) -> dict:
    """High-crest fixture takes the static branch without touching media."""
    return {"input_i": integrated, "input_tp": peak, "input_lra": 4,
            "input_thresh": -40, "target_offset": 0}


class MasteringDecisionTests(unittest.TestCase):
    """Only actual measured filters can claim the tighter preparation tolerance."""

    def test_linear_choice_does_not_claim_static_convergence(self) -> None:
        callback = Mock(side_effect=AssertionError("unexpected dry run"))
        selected = select_master_filter(MasterFilterInput(None, measured(-20, -10), callback))
        self.assertEqual(selected.evidence["branch"], "linear")
        self.assertIsNone(selected.evidence["gainDb"])
        self.assertEqual(selected.evidence["dryRuns"], [])
        self.assertEqual(selected.evidence["convergence"], "not-applicable")
        self.assertIn(":linear=true:", selected.evidence["filter"])

    def test_dynamic_choice_serializes_nonfinite_input_without_inventing_gain(self) -> None:
        for stats in (None, measured(-60, -20), measured(float("nan"), -20)):
            with self.subTest(stats=stats):
                selected = select_master_filter(MasterFilterInput(
                    "pan=stereo|c0=c0|c1=c0", stats, Mock()))
                self.assertEqual(selected.evidence["branch"], "dynamic")
                self.assertIsNone(selected.evidence["gainDb"])
                self.assertTrue(selected.chain.startswith("pan=stereo"))
                json.dumps(selected.evidence, allow_nan=False)

    def test_converged_gain_records_exact_two_decimal_filter_not_rounded_note(self) -> None:
        callback = Mock(side_effect=[-14.23, -14.04])
        selected = select_master_filter(MasterFilterInput(None, measured(), callback))
        evidence = selected.evidence
        self.assertEqual(evidence["gainDb"], 21.23)
        self.assertIn("gain +21.2 dB", selected.note)
        self.assertIn("volume=21.23dB", selected.chain)
        self.assertEqual(evidence["convergence"], "converged")
        self.assertTrue(evidence["selectedFilterMeasured"])
        self.assertEqual(evidence["filter"], callback.call_args.args[0])
        self.assertEqual(evidence["staticTrimToleranceLu"], 0.10)
        self.assertEqual(evidence["dryRuns"][-1]["integratedLufs"], -14.04)
        self.assertEqual(callback.call_count, 2)

    def test_budget_exhaustion_does_not_bless_the_unmeasured_final_gain(self) -> None:
        callback = Mock(return_value=-15)
        selected = select_master_filter(MasterFilterInput(None, measured(), callback))
        evidence = selected.evidence
        self.assertEqual(evidence["convergence"], "budget-exhausted")
        self.assertFalse(evidence["selectedFilterMeasured"])
        self.assertEqual(evidence["gainDb"], 23)
        self.assertEqual([row["gainDb"] for row in evidence["dryRuns"]], [21, 22])
        self.assertNotEqual(evidence["filter"], callback.call_args.args[0])
        self.assertEqual(callback.call_count, 2)

    def test_missing_measurement_is_recorded_without_an_extra_dry_run(self) -> None:
        callback = Mock(return_value=None)
        selected = select_master_filter(MasterFilterInput(None, measured(), callback))
        self.assertEqual(selected.evidence["convergence"], "measurement-unavailable")
        self.assertFalse(selected.evidence["selectedFilterMeasured"])
        self.assertEqual(selected.evidence["gainDb"], 21)
        self.assertEqual(callback.call_count, 1)

    def test_native_profile_retains_its_actual_budget_and_internal_peak(self) -> None:
        callback = Mock(return_value=-15)
        selected = select_master_filter(MasterFilterInput(
            None, measured(), callback, NATIVE_SHORT_MASTERING_PROFILE))
        self.assertEqual(selected.evidence["profile"], NATIVE_SHORT_MASTERING_PROFILE.receipt())
        self.assertEqual(callback.call_count, 6)
        self.assertEqual(selected.evidence["gainDb"], 27)
        self.assertEqual(selected.evidence["convergence"], "budget-exhausted")

    def test_legacy_report_describes_the_filter_given_to_the_encoder(self) -> None:
        spec = master.MasterSpec(src="TEST source", out="TEST output")
        self.enterContext(patch.object(master, "has_audio", return_value=True))
        self.enterContext(patch.object(master, "dead_channel_prefix", return_value=(None, None)))
        self.enterContext(patch.object(master, "measure_loudness", return_value=measured()))
        self.enterContext(patch.object(master, "_measure_chain_lufs", return_value=-14))
        self.enterContext(patch.object(master.os.path, "exists", return_value=True))
        self.enterContext(patch.object(master, "_finalize", return_value={"status": "done"}))
        encoded = self.enterContext(patch.object(master, "_encode",
            return_value=subprocess.CompletedProcess([], 0, "", "")))
        result = master.master(spec)
        self.assertEqual(result["mastering_decision"]["filter"], encoded.call_args.args[2])
        self.assertEqual(result["mastering_decision"]["branch"], "static")
        self.assertEqual(result["mastering_decision"]["scope"],
                         "processing-observation-not-delivery-approval")

    def test_audio_only_rebuild_retains_a_decision_bound_to_completed_bytes(self) -> None:
        """The process log alone is insufficient after the candidate is promoted."""
        from audio import base_audio
        from fingerprints import file_sha256

        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        evidence = {"TEST": "processing decision"}

        def remaster(_source: str, destination: str) -> tuple[None, dict]:
            Path(destination).write_bytes(b"TEST completed media")
            return None, evidence

        with patch.object(base_audio, "_remaster_audio", side_effect=remaster):
            completed, _ = base_audio.rebuild_audio_bus("TEST source", {}, str(root))
        record = json.loads((root / "audio_rebuild.json").read_text())
        self.assertEqual(record["mastering_decision"], evidence)
        self.assertEqual(record["completedBaseSha256"], file_sha256(completed))
        self.assertEqual(record["scope"], "processing-observation-not-delivery-approval")


if __name__ == "__main__":
    unittest.main()
