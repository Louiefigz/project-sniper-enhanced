"""OCI compact-vs-deep boundaries; synthetic facts are never retained proof."""
from __future__ import annotations

import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from graphics.comp_rate_artifact import RELEASED_RATES, _duration_for
from graphics.comp_rate_oci_artifact import CHECKS, ROOT, _probes, _source_rows, load_oci_receipt
from graphics.comp_rate_oci_audit import _request_sources, _runtime, audit
from graphics.comp_rate_oci_export import _runner_observation, export_receipt
from graphics.comp_rate_oci_inputs import _prepare_one


def rows() -> list[dict]:
    """Construct inert four-frame facts for isolated contract tests only."""
    result = []
    for rate in sorted(RELEASED_RATES):
        result.append({"kind": "inert", "rate": rate, "duration": _duration_for(rate),
                       "stream": {"codec_name": "prores", "pix_fmt": "yuva444p12le", "width": 16, "height": 16,
                                  "r_frame_rate": rate, "avg_frame_rate": rate, "nb_read_frames": "4"},
                       "mediaSha256": "1" * 64, "inputSha256": "2" * 64, "runtimeReceiptSha256": "3" * 64,
                       "sourceSha256": "4" * 64, "specHash": "5" * 64, "decoded": True,
                       "checks": CHECKS, "elapsedMs": 10})
    return result


class CompRateOciArtifactTests(unittest.TestCase):
    def test_all_pairs_and_streams_are_checked_even_after_resealing(self) -> None:
        _probes(rows(), {"inert": {"canvas": [16, 16]}})
        for mutation in ("missing", "duplicate", "duration", "stream", "decode", "checks", "hash"):
            changed = copy.deepcopy(rows())
            if mutation == "missing":
                changed.pop()
            elif mutation == "duplicate":
                changed[-1] = changed[0]
            elif mutation == "stream":
                changed[0]["stream"]["nb_read_frames"] = "3"
            else:
                value = {"duration": {}, "decode": False, "checks": [], "hash": "bad"}[mutation]
                # Keep each fault explicit; these are synthetic contract facts.
                field = {"duration": "duration", "decode": "decoded", "checks": "checks", "hash": "mediaSha256"}[mutation]
                changed[0][field] = value
            with self.subTest(mutation=mutation), self.assertRaises(RuntimeError):
                _probes(changed, {"inert": {"canvas": [16, 16]}})

    def test_missing_private_raw_evidence_cannot_claim_deep_revalidation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            with self.assertRaises(FileNotFoundError):
                audit(root)
            with self.assertRaises(FileNotFoundError):
                export_receipt(root, root / "compact.json")
            self.assertFalse((root / "compact.json").exists())

    def test_source_paths_cannot_select_other_host_files(self) -> None:
        for relative in ("/etc/passwd", "scripts/producer/../../secret", "src/.env"):
            with self.subTest(relative=relative), self.assertRaises(RuntimeError):
                _source_rows([{"path": relative, "sha256": "0" * 64}])

    def test_fifo_receipt_is_rejected_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw).resolve() / "receipt.json"
            os.mkfifo(path)
            value, issue = load_oci_receipt(path, "0" * 64)
            self.assertIsNone(value)
            self.assertIn("regular", issue)

    def test_midrun_observation_never_becomes_startup_capture(self) -> None:
        with patch("graphics.comp_rate_oci_export.bound_json", return_value={"runnerStartupCapture": "captured", "sha256": "x"}), \
                patch("graphics.comp_rate_oci_export.file_hash", return_value="x"), self.assertRaisesRegex(RuntimeError, "startup"):
            _runner_observation(Path("/private/tmp/inert"))

    def test_deep_runtime_requires_exact_rate_arguments(self) -> None:
        request = {"composition": "compositions/inert.html", "manifest": []}
        row = {"mediaSha256": "same", "runtimeReceiptSha256": "same", "inputSha256": "input", "rate": "24",
               "containerRemoval": {"canonicalAbsenceProved": True}}
        runtime = {"imageId": "image", "snapshotSha256": "input", "snapshotManifest": [],
                   "containerRemoval": row["containerRemoval"], "containerBeforeOutput": {"Args": ["--fps", "30"]}}
        with patch("graphics.comp_rate_oci_audit.file_hash", return_value="same"), \
                patch("graphics.comp_rate_oci_audit.bound_json", return_value=runtime), \
                patch("graphics.comp_rate_oci_audit.validate_runtime_shape"), self.assertRaisesRegex(RuntimeError, "arguments"):
            _runtime(row, request, Path("/private/tmp/inert"), "image")

    def test_source_audit_requires_exact_archive_closure_and_default_spec(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            source = ROOT / "templates/motion/compositions/line-swap.html"
            request = _prepare_one(str(ROOT), source, "24", root / "probe")
            _request_sources(request)
            for mutation in ("manifest", "spec", "duration"):
                changed = copy.deepcopy(request)
                if mutation == "manifest":
                    changed["manifest"].pop()
                elif mutation == "spec":
                    changed["specHash"] = "0" * 64
                else:
                    changed["duration"] = _duration_for("30")
                with self.subTest(mutation=mutation), self.assertRaises(RuntimeError):
                    _request_sources(changed)


if __name__ == "__main__":
    unittest.main()
