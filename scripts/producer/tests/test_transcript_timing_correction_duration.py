"""Exact admitted duration eligibility; no duplicate source hash or new decode."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from _timing_correction_fixture import TimingCorrectionFixture
import transcript_timing_correction as correction
import transcript_timing_correction_authority as authority


class TimingCorrectionDurationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = TimingCorrectionFixture()
        self.addCleanup(self.fixture.close)

    def test_verified_receipt_duration_matches_honest_synthetic_manifest(self) -> None:
        manifest = json.loads(self.fixture.manifest.read_bytes())
        source = manifest["sources"][0]
        value = SimpleNamespace(inputs=self.fixture.inputs, source=source)
        with patch.object(authority, "observe_source", side_effect=AssertionError("extra media hash")):
            path, raw = authority._duration_receipt(value, source, lambda: None)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), source["admissionReceiptSha256"])
        self.assertEqual(json.loads(raw)["decoded"]["facts"]["durationSeconds"], 16)
        self.assertEqual(path, self.fixture.manifest.parent / source["admissionReceiptPath"])

    def test_changed_manifest_duration_rejects_even_with_matching_parent_hash(self) -> None:
        original = self.fixture.manifest.read_bytes()
        for duration in (15.9, 16.001, 100):
            manifest = json.loads(original)
            manifest["sources"][0]["duration"] = duration
            self.fixture.manifest.write_text(json.dumps(manifest))
            self.fixture.proposed = self.fixture.proposal()
            with self.assertRaisesRegex(RuntimeError, "duration differs from admitted decoded source"):
                self.fixture.correct()
            self.assertFalse(self.fixture.correction_root.exists())

    def test_selected_receipt_is_held_through_final_source_readback(self) -> None:
        prepared = self.fixture.correct()
        self.fixture.correct("record", self.fixture.submission(prepared))
        manifest = json.loads(self.fixture.manifest.read_bytes())
        path = self.fixture.manifest.parent / manifest["sources"][0]["admissionReceiptPath"]
        raw = path.read_bytes()
        original_result = correction._result

        def mutate_after_result(*args: object) -> tuple:
            result = original_result(*args)
            path.write_bytes(raw + b" ")
            return result

        with patch.object(correction, "_result", side_effect=mutate_after_result):
            with self.assertRaisesRegex(RuntimeError, "parent changed"):
                self.fixture.correct("status")

    def test_duration_metadata_rejects_receipt_hash_mutation_without_source_rehash(self) -> None:
        source = json.loads(self.fixture.manifest.read_bytes())["sources"][0]
        path = self.fixture.manifest.parent / source["admissionReceiptPath"]
        path.write_bytes(path.read_bytes() + b" ")
        value = SimpleNamespace(inputs=self.fixture.inputs, source=source)
        with patch.object(authority, "observe_source", side_effect=AssertionError("extra media hash")):
            with self.assertRaisesRegex(RuntimeError, "admission receipt changed"):
                authority._duration_receipt(value, source, lambda: None)


if __name__ == "__main__":
    unittest.main()
