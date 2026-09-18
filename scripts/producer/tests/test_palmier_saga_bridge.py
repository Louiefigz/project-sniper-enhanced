"""Closed proof/readback tests for the durable Palmier commit bridge."""
import tempfile
import unittest
from unittest.mock import patch

from _common import *  # noqa: F401,F403
from palmier.candidate_receipt import load_candidate, save_candidate
from palmier.native_qc_contract import load_qc, save_qc
from palmier.quality_hash import stable_hash
from palmier.saga_bridge import observe_head, prove_candidate
from test_palmier_native_delta import NativeClient
from test_palmier_native_qc import _approve, _candidate


def _approved(tmp: str, client: NativeClient) -> tuple[dict, dict]:
    parent, candidate = _candidate(tmp, client)
    _approve(tmp, parent, candidate)
    candidate = load_candidate(tmp)
    candidate["qc"]["approvalDigest"] = "c" * 64
    save_candidate(tmp, candidate)
    receipt = load_qc(tmp)
    receipt.update({
        "approvalDigest": "c" * 64,
        "authority": {
            "manifestHash": "d" * 64,
            "inputDigest": "e" * 64,
            "nativePlanHash": "1" * 64,
            "summary": {"transcriptDigest": "f" * 64},
        },
    })
    save_qc(tmp, receipt)
    return parent, candidate


class PalmierSagaBridgeTests(unittest.TestCase):
    def test_proof_is_stable_and_restores_the_visible_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = NativeClient()
            parent, candidate = _approved(tmp, client)
            with patch("palmier.saga_bridge.validate_approved_candidate"):
                first = prove_candidate(client, tmp)
                second = prove_candidate(client, tmp)
            self.assertEqual(client.active, parent["timelineId"])
            self.assertEqual(first["status"], "saga-candidate-proved")
            self.assertEqual(first["candidateId"], candidate["timelineId"])
            stable = {key: value for key, value in first.items()
                      if key not in ("ok", "status", "candidateHash", "provedAt")}
            self.assertEqual(first["candidateHash"], stable_hash(stable))
            self.assertEqual(first["candidateHash"], second["candidateHash"])
            self.assertEqual(first["timelineHash"], candidate["fingerprint"])

    def test_observation_exposes_hashes_only_for_the_exact_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = NativeClient()
            _parent, candidate = _approved(tmp, client)
            parent = observe_head(client, tmp)
            self.assertIsNone(parent["candidateHash"])
            self.assertIsNone(parent["timelineHash"])
            client.active = candidate["timelineId"]
            with patch("palmier.saga_bridge.validate_approved_candidate"):
                selected = observe_head(client, tmp)
                proof = prove_candidate(client, tmp)
            self.assertEqual(selected["headId"], candidate["timelineId"])
            self.assertEqual(selected["candidateHash"], proof["candidateHash"])
            self.assertEqual(selected["timelineHash"], proof["timelineHash"])

    def test_promoted_lifecycle_keeps_the_same_reservation_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = NativeClient()
            _parent, candidate = _approved(tmp, client)
            with patch("palmier.saga_bridge.validate_approved_candidate"):
                before = prove_candidate(client, tmp)
            candidate = load_candidate(tmp)
            candidate["status"] = "promoted"
            save_candidate(tmp, candidate)
            receipt = load_qc(tmp)
            receipt["status"] = "promoted"
            receipt["promotedAt"] = "2026-07-30T12:00:00Z"
            save_qc(tmp, receipt)
            client.active = candidate["timelineId"]
            with patch("palmier.saga_bridge.validate_approved_candidate"):
                after = prove_candidate(client, tmp)
                observed = observe_head(client, tmp)
            self.assertEqual(after["candidateHash"], before["candidateHash"])
            self.assertEqual(observed["candidateHash"], before["candidateHash"])


if __name__ == "__main__":
    unittest.main()
