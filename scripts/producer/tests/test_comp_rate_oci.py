"""Closed OCI matrix shape and failure retention without a real render."""
from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from graphics.comp_rate_oci import RELEASED_RATES, _record_probe, cohort_boundary, proof_tools, validate_completed
from graphics.comp_rate_oci_inputs import MOTION_DIR, _track_sources


class CompRateOciTests(unittest.TestCase):
    def test_requires_exact_complete_cross_product_and_observed_cleanup(self) -> None:
        rows = [{"kind": kind, "rate": rate, "passed": True, "decoded": True,
                 "containerRemoval": {"canonicalAbsenceProved": True}}
                for kind in ("a", "b") for rate in RELEASED_RATES]
        value = {"inputs": {"compositionKinds": ["a", "b"]}, "probes": rows}
        validate_completed(value)
        for mutation in ("missing", "duplicate", "cleanup", "decode"):
            changed = copy.deepcopy(value)
            if mutation == "missing":
                changed["probes"].pop()
            elif mutation == "duplicate":
                changed["probes"][-1] = changed["probes"][0]
            elif mutation == "cleanup":
                changed["probes"][0]["containerRemoval"] = {}
            else:
                changed["probes"][0]["decoded"] = False
            with self.subTest(mutation=mutation), self.assertRaises(RuntimeError):
                validate_completed(changed)

    def test_source_tracking_rejects_mixed_dependency_epochs(self) -> None:
        row = {"composition": "compositions/a.html", "sourceSha256": "original",
               "manifest": [{"path": "motion/compositions/a.html", "sha256": "duration-rewrite"},
                            {"path": "motion/tokens.css", "sha256": "before"}]}
        frozen = {}
        _track_sources(row, frozen)
        self.assertEqual(frozen[Path(MOTION_DIR) / "compositions/a.html"], "original")
        row["manifest"][1]["sha256"] = "after"
        with self.assertRaisesRegex(RuntimeError, "changed"):
            _track_sources(row, frozen)

    def test_proof_decoders_must_be_explicit(self) -> None:
        with patch.dict("os.environ", {}, clear=True), self.assertRaisesRegex(RuntimeError, "pins"):
            proof_tools()

    def test_failed_real_probe_boundary_is_recorded_without_rehashing_old_rows(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            row = {"kind": "inert", "rate": "30", "directory": str(root)}
            with patch("graphics.comp_rate_oci._probe", side_effect=RuntimeError("inert boundary failure")):
                result = _record_probe(row, {}, [1080, 1920])
            self.assertFalse(result["passed"])
            self.assertIn("inert boundary failure", result["error"])
            self.assertTrue((root / "result.json").is_file())
            self.assertNotIn("mediaSha256", result)

    def test_budget_stops_between_probes_before_an_overrun_launch(self) -> None:
        value = {"probes": [{"elapsedMs": 50_000}] * 10}
        with patch("graphics.comp_rate_oci.time.monotonic", return_value=600), self.assertRaisesRegex(RuntimeError, "projection"):
            cohort_boundary(0, 424, value)
        self.assertEqual(value["cohortBudget"]["softBudgetSeconds"], 1800)

    def test_operator_stop_request_is_honored_at_owned_probe_boundary(self) -> None:
        value = {"probes": [{"elapsedMs": 5}], "stopRequested": True}
        with patch("graphics.comp_rate_oci.time.monotonic", return_value=1), self.assertRaisesRegex(RuntimeError, "cleanup completed"):
            cohort_boundary(0, 424, value)

    def test_budget_passes_fast_cohort_but_includes_sealing_elapsed(self) -> None:
        value = {"probes": [{"elapsedMs": 3000}] * 10}
        with patch("graphics.comp_rate_oci.time.monotonic", return_value=40):
            cohort_boundary(0, 424, value)
        self.assertLess(value["cohortBudget"]["projectedSeconds"], 1800)
        with patch("graphics.comp_rate_oci.time.monotonic", return_value=1800), self.assertRaisesRegex(RuntimeError, "soft budget"):
            cohort_boundary(0, 424, value)


if __name__ == "__main__":
    unittest.main()
