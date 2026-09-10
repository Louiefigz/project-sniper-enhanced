"""Real-media coverage for frozen editable-versus-master parity."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fingerprints import file_sha256
from palmier.editable_parity_contract import (
    POLICY,
    approvals_path,
    policy_hash,
    run_parity,
    validate_parity,
)
from palmier.editable_parity_measure import probe
from palmier.mcp_client import PalmierError
from palmier.native_qc_audit import run_native_audit

HAVE_MEDIA = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _media(path: str, color: str = "red") -> None:
    result = subprocess.run([
        "ffmpeg", "-y", "-nostdin", "-v", "error",
        "-f", "lavfi", "-i", f"color=c={color}:s=320x180:r=24:d=0.5",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:d=0.5",
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "mpeg4",
        "-q:v", "2", "-c:a", "aac", "-shortest", path,
    ], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr)


def _approval(tmp: str, receipt: dict) -> None:
    mismatches = [row for row in receipt["metrics"]
                  if row["status"] == "mismatch"]
    value = {
        "schemaVersion": 1,
        "kind": "palmier-editable-parity-approvals",
        "masterHash": receipt["master"]["hash"],
        "candidateHash": receipt["candidate"]["hash"],
        "policyHash": policy_hash(),
        "approver": "operator@example.test",
        "approvedAt": "2026-07-30T15:00:00+00:00",
        "approximations": [
            {"metricId": row["metricId"],
             "reason": "Connected editor cannot reproduce this baked treatment natively."}
            for row in mismatches
        ],
    }
    with open(approvals_path(tmp), "w", encoding="utf-8") as handle:
        json.dump(value, handle)


@unittest.skipUnless(HAVE_MEDIA, "ffmpeg and ffprobe are required")
class EditableParityTests(unittest.TestCase):
    def test_audio_count_uses_decoded_samples_not_container_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            media = os.path.join(tmp, "aac.mp4")
            _media(media)
            measured = probe(media)
            container_estimate = round(
                measured["durationSeconds"] * measured["audioSampleRate"])
            self.assertEqual(measured["audioSampleCount"], 24_576)
            self.assertEqual(container_estimate, 24_000)

    def test_identical_full_streams_pass_frozen_policy_and_revalidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            master = os.path.join(tmp, "final.mp4")
            candidate = os.path.join(tmp, "palmier.candidate.mp4")
            _media(master)
            shutil.copyfile(master, candidate)
            master_hash = file_sha256(master)
            receipt = run_parity(tmp, candidate, master_hash)
            self.assertEqual(receipt["verdict"], "pass")
            self.assertEqual(receipt["blockedMetricIds"], [])
            self.assertEqual(receipt["policy"]["tolerances"],
                             POLICY["tolerances"])
            self.assertEqual(
                {row["status"] for row in receipt["metrics"]}, {"pass"})
            self.assertEqual(
                validate_parity(
                    tmp, file_sha256(candidate), master_hash)["digest"],
                receipt["digest"])

    def test_every_mismatch_needs_exact_hash_bound_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            master = os.path.join(tmp, "final.mp4")
            candidate = os.path.join(tmp, "palmier.candidate.mp4")
            _media(master, "red")
            _media(candidate, "blue")
            master_hash = file_sha256(master)
            blocked = run_parity(tmp, candidate, master_hash)
            self.assertEqual(blocked["verdict"], "blocked")
            self.assertIn("picture.mean-ssim", blocked["blockedMetricIds"])
            with self.assertRaisesRegex(PalmierError, "not a passing"):
                validate_parity(tmp, file_sha256(candidate), master_hash)

            _approval(tmp, blocked)
            approved = run_parity(tmp, candidate, master_hash)
            self.assertEqual(approved["verdict"], "pass")
            approved_rows = [row for row in approved["metrics"]
                             if row["status"] == "approved-approximation"]
            self.assertEqual(
                {row["metricId"] for row in approved_rows},
                set(blocked["blockedMetricIds"]))
            validate_parity(tmp, file_sha256(candidate), master_hash)

            with open(approvals_path(tmp), "a", encoding="utf-8") as handle:
                handle.write(" ")
            with self.assertRaisesRegex(PalmierError, "approval changed"):
                validate_parity(tmp, file_sha256(candidate), master_hash)

    def test_full_plan_live_build_audit_enforces_parity_not_surgical_lane(self):
        with tempfile.TemporaryDirectory() as tmp:
            parity_file = os.path.join(tmp, "palmier.editable-parity.json")
            with open(parity_file, "w", encoding="utf-8") as handle:
                handle.write("{}\n")
            export = {"path": "candidate.mp4", "hash": "e" * 64}
            parity = {"verdict": "pass", "blockedMetricIds": [],
                      "digest": "p" * 64}
            found = SimpleNamespace(fingerprint="f" * 64)
            graph = {"checks": []}
            with patch("palmier.native_qc_audit.structural_proof",
                       return_value=graph), \
                    patch("palmier.native_qc_audit._export_checks",
                          return_value=([], [])), \
                    patch("palmier.native_qc_audit.run_parity",
                          return_value=parity) as compare, \
                    patch("palmier.native_qc_audit.master_authority_hash",
                          return_value="m" * 64):
                live = run_native_audit(tmp, {
                    "outDir": tmp, "export": export,
                    "authority": {"kind": "live-build",
                                  "planHash": "q" * 64,
                                  "inputDigest": "i" * 64},
                }, found)
                self.assertEqual(
                    live["checks"][0]["name"], "editable_master_parity")
                compare.assert_called_once_with(
                    tmp, "candidate.mp4", "m" * 64)
                compare.reset_mock()
                run_native_audit(tmp, {
                    "outDir": tmp, "export": export,
                    "authority": {"kind": "desktop-build",
                                  "planHash": "q" * 64,
                                  "inputDigest": "i" * 64},
                }, found)
                compare.assert_called_once_with(
                    tmp, "candidate.mp4", "m" * 64)
                compare.reset_mock()
                run_native_audit(tmp, {
                    "outDir": tmp, "export": export,
                    "authority": {"inputDigest": "i" * 64},
                }, found)
                compare.assert_not_called()


if __name__ == "__main__":
    unittest.main()
