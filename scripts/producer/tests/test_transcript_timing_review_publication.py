"""Cut receipts retain their initial bytes across timing-review/final publication."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]

from _timing_review_fixture import TimingReviewFixture
import transcript_cut_contract as gate


class TimingReviewPublicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = TimingReviewFixture()
        self.addCleanup(self.fixture.close)
        prepared = self.fixture.prepare()
        self.fixture.record(self.fixture.submission(prepared))

    def test_candidate_change_after_review_cannot_be_receipted_as_reviewed(self) -> None:
        original = self.fixture.plan.read_bytes()
        real = gate.consume_timing_reviews

        def mutate(*args) -> tuple:
            result = real(*args)
            changed = json.loads(original)
            changed["cutTrack"][0]["start"] = 13.85
            self.fixture.plan.write_text(json.dumps(changed))
            return result

        with patch.object(gate, "consume_timing_reviews", side_effect=mutate):
            result = self.fixture.check()
        self.assertFalse(result["ok"], "The reviewed cut must not certify later candidate bytes")
        self.assertIn("changed during cut validation", " ".join(result["errors"]))
        self.assertEqual(result["metrics"]["receipt"]["planHash"], hashlib.sha256(original).hexdigest())

    def test_manifest_change_after_review_keeps_original_receipt_and_rejects(self) -> None:
        original = self.fixture.manifest.read_bytes()
        real = gate.consume_timing_reviews

        def mutate(*args) -> tuple:
            result = real(*args)
            self.fixture.manifest.write_bytes(original + b"\n")
            return result

        with patch.object(gate, "consume_timing_reviews", side_effect=mutate):
            result = self.fixture.check()
        self.assertFalse(result["ok"])
        self.assertEqual(result["metrics"]["receipt"]["manifestHash"], hashlib.sha256(original).hexdigest())

    def test_final_parent_guard_runs_after_approval_check_too(self) -> None:
        original = self.fixture.plan.read_bytes()

        def mutate(_path: str, _receipt: dict, _errors: list) -> None:
            self.fixture.plan.write_bytes(original + b"\n")

        with patch.object(gate, "_check_approval", side_effect=mutate):
            result = gate.check(*self.fixture.paths, approval_path="TEST-ONLY-unused")
        self.assertFalse(result["ok"])
        self.assertIn("changed during cut validation", " ".join(result["errors"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
