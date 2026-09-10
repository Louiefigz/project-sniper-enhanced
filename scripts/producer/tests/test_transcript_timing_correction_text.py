"""Versioned one-to-one TEST text decisions; no actual audition or ASR."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from _timing_correction_fixture import TimingCorrectionFixture


def text_proposal(fixture: TimingCorrectionFixture, word: str = "won’t") -> None:
    """Select v2 explicitly; never try v1 and silently fall back."""
    fixture.proposed.update(schemaVersion=2, operation="propose-source-word-text-correction",
                            corrections=[{"sourceWordIndex": 3, "newWord": word}])


def text_submission(fixture: TimingCorrectionFixture, prepared: dict) -> dict:
    """Explicitly simulated source-faithful review, not real creator approval."""
    sent = fixture.submission(prepared)
    sent.update(schemaVersion=2, operation="record-source-word-text-correction")
    for review in sent["reviews"]:
        review.pop("comparedOriginalAndProposedBounds")
        review.update(comparedOriginalAndProposedText=True, confirmsSourceFaithfulTranscription=True)
    return sent


class TimingCorrectionTextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = TimingCorrectionFixture()
        self.addCleanup(self.fixture.close)

    def test_explicit_text_revision_preserves_timing_and_historical_confidence(self) -> None:
        fixture = self.fixture
        parent = json.loads(fixture.transcript.read_bytes())
        parent["transcript"][0]["text"] = " ".join(w["word"] for w in parent["transcript"][0]["words"])
        parent["transcript"][0]["words"][3]["speaker"] = "TEST-speaker"
        fixture.rebind_test_payload(parent)
        text_proposal(fixture)
        before = fixture.parent_inventory()
        prepared = fixture.correct()
        self.assertEqual(prepared["request"]["policy"], "sniper-source-word-text-correction-v2")
        self.assertEqual(prepared["request"]["corrections"][0]["originalWord"]["confidence"], .9)
        recorded = fixture.correct("record", text_submission(fixture, prepared))
        revised = json.loads(Path(recorded["revision"]["path"]).read_bytes())
        expected = copy.deepcopy(parent["transcript"])
        expected[0]["words"][3]["word"] = "won’t"
        expected[0]["words"][3].pop("confidence")
        expected[0]["text"] = " ".join(w["word"] for w in expected[0]["words"])
        self.assertEqual(revised["transcript"], expected)
        self.assertNotIn("timingCorrectionAuthority", revised)
        self.assertEqual(revised["sourceWordCorrectionAuthority"]["textOrigin"],
                         "explicit-human-source-review-not-emitted-by-ASR")
        self.assertFalse(recorded["selected"])
        self.assertEqual(before, fixture.parent_inventory())
        self.assertEqual(fixture.correct("status")["revision"], recorded["revision"])

    def test_text_revision_without_utterance_text_does_not_invent_one(self) -> None:
        text_proposal(self.fixture, "OpenAI")
        prepared = self.fixture.correct()
        result = self.fixture.correct("record", text_submission(self.fixture, prepared))
        revised = json.loads(Path(result["revision"]["path"]).read_bytes())
        self.assertNotIn("text", revised["transcript"][0])

    def test_lexical_names_numbers_and_negation_are_explicit_not_inferred(self) -> None:
        for word in ("O’Neill", "José", "GPT-4o", "$1,000", "2.5", "not", "won’t", "東京"):
            text_proposal(self.fixture, word)
            prepared = self.fixture.correct()
            self.assertEqual(prepared["request"]["corrections"][0]["newWord"], word)
            self.fixture.proposed = self.fixture.proposal()

    def test_ambiguous_or_nonlexical_replacement_rejects_before_source_work(self) -> None:
        words = ("", " ", "New York", " run", "run ", "\tname", "\nname", ".", "...", "—",
                 "a\u200bb", "a\x00b", "[_BEG_]", "run", "x" * 121, "\ud800")
        with patch("transcript_timing_correction.verify_sources") as verify:
            for word in words:
                text_proposal(self.fixture, word)
                with self.assertRaises((RuntimeError, ValueError, UnicodeError)):
                    self.fixture.correct()
            verify.assert_not_called()
        self.assertFalse(self.fixture.correction_root.exists())

    def test_ambiguous_original_utterance_text_is_not_normalized_or_replaced(self) -> None:
        parent = json.loads(self.fixture.transcript.read_bytes())
        parent["transcript"][0]["text"] = "If  If you run content for clients."
        self.fixture.rebind_test_payload(parent)
        text_proposal(self.fixture)
        with patch("transcript_timing_correction.verify_sources") as verify:
            with self.assertRaisesRegex(RuntimeError, "utterance text"):
                self.fixture.correct()
            verify.assert_not_called()

    def test_versions_cannot_exchange_timing_fields_or_human_review_kind(self) -> None:
        text_proposal(self.fixture)
        self.fixture.proposed["corrections"][0]["newStart"] = 13.9
        with self.assertRaises(RuntimeError):
            self.fixture.correct()
        self.fixture.proposed["corrections"][0].pop("newStart")
        prepared = self.fixture.correct()
        with self.assertRaises(RuntimeError):
            self.fixture.correct("record", self.fixture.submission(prepared))
        sent = text_submission(self.fixture, prepared)
        sent["reviews"][0]["confirmsSourceFaithfulTranscription"] = False
        with self.assertRaises(RuntimeError):
            self.fixture.correct("record", sent)
        self.assertFalse((self.fixture.correction_root / "record-claim.json").exists())

    def test_text_replay_never_rewrites_and_a_different_text_cannot_rebase(self) -> None:
        text_proposal(self.fixture)
        prepared = self.fixture.correct()
        sent = text_submission(self.fixture, prepared)
        first = self.fixture.correct("record", sent)
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.fixture.correction_root.iterdir()}
        self.assertTrue(self.fixture.correct("record", sent)["replayed"])
        self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns)
                                  for p in self.fixture.correction_root.iterdir()})
        self.fixture.proposed["corrections"][0]["newWord"] = "should"
        with self.assertRaises(RuntimeError):
            self.fixture.correct("status")
        self.assertTrue(Path(first["revision"]["path"]).is_file())


if __name__ == "__main__":
    unittest.main()
