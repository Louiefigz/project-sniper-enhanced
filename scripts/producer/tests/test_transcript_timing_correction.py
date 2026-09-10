"""Actual durable synthetic correction flow; no media, models or human consent."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from _timing_correction_fixture import TimingCorrectionFixture
from transcript_source_authority import verify_result


class TimingCorrectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = TimingCorrectionFixture()
        self.addCleanup(self.fixture.close)

    def test_new_revision_and_strong_status_preserve_originals_and_all_other_words(self) -> None:
        fixture = self.fixture
        before = fixture.parent_inventory()
        prepared = fixture.correct()
        self.assertEqual(prepared["state"], "prepared")
        self.assertIsNone(prepared["revision"])
        recorded = fixture.correct("record", fixture.submission(prepared))
        self.assertEqual(recorded["state"], "committed")
        self.assertFalse(recorded["selected"])
        self.assertFalse(recorded["cutApproved"])
        self.assertFalse(recorded["deliveryApproved"])
        revised = json.loads(Path(recorded["revision"]["path"]).read_bytes())
        parent = json.loads(before[fixture.transcript])
        expected = copy.deepcopy(parent["transcript"])
        expected[0]["words"][1]["start"] = 13.5
        self.assertEqual(revised["transcript"], expected)
        self.assertEqual(before, fixture.parent_inventory())
        source = json.loads(before[fixture.manifest])["sources"][0]
        self.assertIsNone(verify_result(revised, source, recorded["revision"]["path"]))
        self.assertEqual(fixture.correct("status")["revision"], recorded["revision"])

    def test_exact_replay_does_not_rewrite_any_record_or_parent(self) -> None:
        fixture = self.fixture
        prepared = fixture.correct()
        sent = fixture.submission(prepared)
        initial = fixture.correct("record", sent)
        before = {path.name: (path.read_bytes(), path.stat().st_mtime_ns)
                  for path in fixture.correction_root.iterdir()}
        replayed = fixture.correct("record", sent)
        self.assertTrue(replayed["replayed"])
        self.assertEqual(replayed["revision"], initial["revision"])
        self.assertTrue(fixture.correct()["replayed"])
        self.assertEqual(before, {path.name: (path.read_bytes(), path.stat().st_mtime_ns)
                                  for path in fixture.correction_root.iterdir()})

    def test_second_decision_and_reused_id_with_changed_content_both_reject(self) -> None:
        fixture = self.fixture
        prepared = fixture.correct()
        sent = fixture.submission(prepared)
        fixture.correct("record", sent)
        with self.assertRaisesRegex(RuntimeError, "conflict"):
            fixture.correct("record", fixture.submission(prepared))
        changed = copy.deepcopy(sent)
        changed["reviews"][0]["rationale"] += " Altered."
        with self.assertRaisesRegex(RuntimeError, "conflict"):
            fixture.correct("record", changed)

    def test_only_affected_utterance_endpoints_are_recomputed(self) -> None:
        fixture = self.fixture
        fixture.proposed["corrections"] = [{"sourceWordIndex": 0, "newStart": 8.4, "newEnd": 8.64},
                                          {"sourceWordIndex": 6, "newStart": 14.69, "newEnd": 15.2}]
        prepared = fixture.correct()
        result = fixture.correct("record", fixture.submission(prepared))
        revised = json.loads(Path(result["revision"]["path"]).read_text())
        self.assertEqual((revised["transcript"][0]["start"], revised["transcript"][0]["end"]), (8.4, 15.2))
        self.assertEqual([w["word"] for w in revised["transcript"][0]["words"]],
                         ["If", "If", "you", "run", "content", "for", "clients."])

    def test_original_asr_provenance_is_historical_not_corrected_model_output(self) -> None:
        fixture = self.fixture
        payload = json.loads(fixture.transcript.read_text())
        payload["provenance"] = {"parserPolicy": "TEST-old-ASR", "resultSha256": "a" * 64}
        fixture.rebind_test_payload(payload)
        prepared = fixture.correct()
        result = fixture.correct("record", fixture.submission(prepared))
        revised = json.loads(Path(result["revision"]["path"]).read_text())
        self.assertEqual(revised["provenance"], payload["provenance"])
        lineage = revised["timingCorrectionAuthority"]
        self.assertEqual(lineage["parentAsrProvenance"], payload["provenance"])
        self.assertEqual(lineage["boundsOrigin"], "explicit-human-boundary-review-not-emitted-by-ASR")


if __name__ == "__main__":
    unittest.main()
