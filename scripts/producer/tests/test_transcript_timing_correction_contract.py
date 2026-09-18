"""Closed timing-only intent and explicit TEST human decision negatives."""
from __future__ import annotations

import copy
import json
import unittest
from unittest.mock import patch

from _timing_correction_fixture import TimingCorrectionFixture
from transcript_timing_correction_contract import parse_json, proposal
from transcript_timing_correction_words import word_locations


class TimingCorrectionContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = TimingCorrectionFixture()
        self.addCleanup(self.fixture.close)

    def assert_rejected_before_source(self) -> None:
        """Faults must not spend a full-source verification or create artifacts."""
        with patch("transcript_timing_correction.verify_sources") as verify:
            with self.assertRaises((RuntimeError, ValueError, TypeError)):
                self.fixture.correct()
            verify.assert_not_called()
        self.assertFalse(self.fixture.correction_root.exists())

    def test_malformed_intervals_indices_and_unknown_text_changes_reject(self) -> None:
        base = copy.deepcopy(self.fixture.proposed)
        changes = [{"newStart": True}, {"newStart": float("nan")}, {"newEnd": float("inf")},
                   {"newStart": 14}, {"newStart": -1}, {"newStart": "13.5"},
                   {"sourceWordIndex": True}, {"sourceWordIndex": -1},
                   {"sourceWordIndex": 9999}, {"word": "changed"},
                   {"newStart": 11.54}, {"newEnd": 17}, {"newStart": 8.0}]
        for change in changes:
            self.fixture.proposed = copy.deepcopy(base)
            self.fixture.proposed["corrections"][0].update(change)
            self.assert_rejected_before_source()

    def test_unsorted_duplicate_and_empty_corrections_reject(self) -> None:
        change = self.fixture.proposed["corrections"][0]
        values = [[], [change, change], [change, {**change, "sourceWordIndex": 0}]]
        for changes in values:
            self.fixture.proposed["corrections"] = changes
            self.assert_rejected_before_source()

    def test_wrong_parent_hash_and_proposal_identity_reject(self) -> None:
        base = self.fixture.proposed
        values = [{"expectedPlanSha256": "0" * 64}, {"expectedTranscriptSha256": "0" * 64},
                  {"expectedManifestSha256": "0" * 64}, {"sourceId": "raw-2"},
                  {"requestId": "../escape"}, {"schemaVersion": True}, {"selected": True}]
        for change in values:
            self.fixture.proposed = {**base, **change}
            self.assert_rejected_before_source()

    def test_submission_cannot_infer_listening_or_boundary_comparison(self) -> None:
        prepared = self.fixture.correct()
        sent = self.fixture.submission(prepared)
        variants = [None, {**sent, "reviews": []}, {**sent, "expectedRecordHash": "0" * 64}]
        for field, value in (("comparedOriginalAndProposedBounds", False), ("rationale", "short"),
                             ("listenedToSourceWindows", []), ("correctionHash", "0" * 64)):
            changed = copy.deepcopy(sent)
            changed["reviews"][0][field] = value
            variants.append(changed)
        changed = copy.deepcopy(sent)
        changed["reviews"][0]["listenedToSourceWindows"][0]["listened"] = 1
        variants.append(changed)
        with patch("transcript_timing_correction.verify_sources") as verify:
            for invalid in variants:
                with self.assertRaises(RuntimeError):
                    self.fixture.correct("record", invalid)
            verify.assert_not_called()
        self.assertFalse((self.fixture.correction_root / "record-claim.json").exists())

    def test_malformed_original_structure_approvals_and_chains_reject(self) -> None:
        parent = json.loads(self.fixture.transcript.read_bytes())
        mutations = []
        for key, value in (("start", 0), ("end", 19), ("text", 123)):
            changed = copy.deepcopy(parent)
            changed["transcript"][0][key] = value
            mutations.append(changed)
        for extra in ({"timingCorrectionAuthority": {}}, {"provenance": {"approved": True}}):
            mutations.append({**parent, **extra})
        changed = copy.deepcopy(parent)
        changed["transcript"][0]["words"][1]["start"] = 8.0
        mutations.append(changed)
        for invalid in mutations:
            with self.assertRaises(RuntimeError):
                word_locations(invalid, 16)

    def test_lexical_text_and_arbitrary_unchanged_word_metadata_are_preserved(self) -> None:
        payload = json.loads(self.fixture.transcript.read_bytes())
        payload["transcript"][0]["words"][1]["speaker"] = "TEST-speaker"
        payload["transcript"][0]["words"][1]["customEvidence"] = {"original": [1, 2]}
        self.fixture.rebind_test_payload(payload)
        prepared = self.fixture.correct()
        original = prepared["request"]["corrections"][0]["originalWord"]
        self.assertEqual(original, payload["transcript"][0]["words"][1])

    def test_duplicate_json_keys_and_nonfinite_json_never_gain_authority(self) -> None:
        for raw in (b'{"schemaVersion":1,"schemaVersion":1}', b'{"x":NaN}'):
            with self.assertRaises((RuntimeError, ValueError)):
                parse_json(raw)
        for invalid in (None, [], {**self.fixture.proposed, "operation": "approve-cut"}):
            with self.assertRaises(RuntimeError):
                proposal(invalid)


if __name__ == "__main__":
    unittest.main()
