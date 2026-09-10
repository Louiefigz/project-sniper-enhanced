"""Actual temporary request/decision/gate lifecycle; all human/media facts TEST ONLY."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]

from _timing_review_fixture import TimingReviewFixture
import transcript_timing_review as service
import transcript_timing_review_authority as authority
import transcript_timing_review_store as store


class TimingReviewLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = TimingReviewFixture()
        self.addCleanup(self.fixture.close)

    def _directory(self) -> Path:
        return next((self.fixture.manifest.parent / ".sniper-timing-reviews").iterdir())

    def test_no_human_review_blocks_even_after_prepare(self) -> None:
        self.assertFalse(self.fixture.check()["ok"])
        result = self.fixture.prepare()
        self.assertEqual(result["review"]["state"], "unresolved")
        self.assertIsNone(result["review"]["decisionHash"])
        self.assertEqual(result["subjectiveListening"], "not-performed-by-system")
        self.assertFalse(self.fixture.check()["ok"])
        self.assertEqual(list((self._directory() / "decisions").iterdir()), [])

    def test_exact_review_is_consumed_without_source_transcript_or_cut_writes(self) -> None:
        paths = (self.fixture.media, self.fixture.transcript, self.fixture.plan, self.fixture.manifest)
        before = {path: path.read_bytes() for path in paths}
        prepared = self.fixture.prepare()
        result = self.fixture.record(self.fixture.submission(prepared))
        gate = self.fixture.check()
        self.assertTrue(gate["ok"], gate["errors"])
        self.assertFalse(result["deliveryApproved"])
        self.assertEqual(gate["metrics"]["receipt"]["outputQuality"]["timingReview"]
                         ["decisionHash"], result["review"]["decisionHash"])
        self.assertEqual(before, {path: path.read_bytes() for path in paths})

    def test_kept_review_never_clears_independent_duplicate_or_midword_errors(self) -> None:
        plan = json.loads(self.fixture.plan.read_text())
        plan["cutTrack"][0]["start"] = 0.37
        self.fixture.plan.write_text(json.dumps(plan))
        prepared = self.fixture.prepare()
        self.fixture.record(self.fixture.submission(prepared))
        result = self.fixture.check()
        self.assertFalse(result["ok"])
        self.assertIn("adjacent duplicate word 'if'", " ".join(result["errors"]))
        plan["cutTrack"][0]["start"] = 13.75
        self.fixture.plan.write_text(json.dumps(plan))
        prepared = self.fixture.prepare()
        self.fixture.record(self.fixture.submission(prepared))
        result = self.fixture.check()
        self.assertFalse(result["ok"])
        self.assertIn("cuts through word 'you'", " ".join(result["errors"]))

    def test_unresolved_history_can_be_explicitly_superseded_without_rewrite(self) -> None:
        prepared = self.fixture.prepare()
        first = self.fixture.record(self.fixture.submission(prepared, resolved=False))
        original = (self._directory() / "decisions" / "0001.json").read_bytes()
        self.assertFalse(self.fixture.check()["ok"])
        second = self.fixture.record(self.fixture.submission(first))
        self.assertTrue(self.fixture.check()["ok"])
        self.assertNotEqual(first["review"]["decisionHash"], second["review"]["decisionHash"])
        self.assertEqual((self._directory() / "decisions" / "0001.json").read_bytes(), original)

    def test_old_replay_does_not_overrule_later_unresolved_decision(self) -> None:
        prepared = self.fixture.prepare()
        sent = self.fixture.submission(prepared)
        first = self.fixture.record(sent)
        self.fixture.record(self.fixture.submission(first, resolved=False))
        replay = self.fixture.record(sent)
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["review"]["state"], "unresolved")
        self.assertFalse(self.fixture.check()["ok"])
        self.assertEqual(len(list((self._directory() / "decisions").iterdir())), 2)

    def test_changed_idempotent_submission_and_stale_previous_hash_reject(self) -> None:
        prepared = self.fixture.prepare()
        sent = self.fixture.submission(prepared)
        self.fixture.record(sent)
        changed = copy.deepcopy(sent)
        changed["reviews"][0]["rationale"] += " Changed."
        with self.assertRaisesRegex(RuntimeError, "idempotency"):
            self.fixture.record(changed)
        with self.assertRaisesRegex(RuntimeError, "previous decision"):
            self.fixture.record(self.fixture.submission(prepared))

    def test_full_prefix_escape_and_changed_cut_invalidate_review(self) -> None:
        prepared = self.fixture.prepare()
        self.fixture.record(self.fixture.submission(prepared))
        plan = json.loads(self.fixture.plan.read_text())
        plan["cutTrack"][0]["start"] = 13.85  # Also omit 'you'; both If anomalies remain.
        self.fixture.plan.write_text(json.dumps(plan))
        result = self.fixture.check()
        self.assertFalse(result["ok"])
        rows = result["metrics"]["receipt"]["outputQuality"]["suspiciousWordSpans"]
        self.assertEqual([row["start"] for row in rows], [0.37, 11.54])

    def test_only_downstream_visual_additions_preserve_the_exact_cut_review(self) -> None:
        prepared = self.fixture.prepare()
        self.fixture.record(self.fixture.submission(prepared))
        plan = json.loads(self.fixture.plan.read_text())
        plan["graphicsTrack"] = [{"id": "TEST-not-rendered", "outStart": 0, "outEnd": 1}]
        self.fixture.plan.write_text(json.dumps(plan))
        self.assertTrue(self.fixture.check()["ok"])
        self.assertTrue(self.fixture.prepare()["replayed"])

    def test_source_transcript_and_manifest_drift_cannot_reuse_review(self) -> None:
        prepared = self.fixture.prepare()
        self.fixture.record(self.fixture.submission(prepared))
        for path in (self.fixture.media, self.fixture.transcript, self.fixture.manifest):
            before = path.read_bytes()
            changed = b"X" + before[1:] if path == self.fixture.media else before + b"\n"
            path.write_bytes(changed)
            self.assertFalse(self.fixture.check()["ok"], str(path))
            path.write_bytes(before)
        self.assertTrue(self.fixture.check()["ok"])

    def test_current_gate_rehashes_once_not_twice_or_stat_only(self) -> None:
        prepared = self.fixture.prepare()
        self.fixture.record(self.fixture.submission(prepared))
        real = authority.execution_media_authority_entries
        with patch.object(authority, "execution_media_authority_entries", wraps=real) as observed:
            self.assertTrue(self.fixture.check()["ok"])
            self.assertEqual(observed.call_count, 1)
            self.assertTrue(self.fixture.check()["ok"])
            self.assertEqual(observed.call_count, 2)

    def test_timeout_after_final_read_cannot_publish_gate_success(self) -> None:
        prepared = self.fixture.prepare()
        self.fixture.record(self.fixture.submission(prepared))
        real = service._unchanged
        clock = [0.0]

        def expire(*args) -> None:
            real(*args)
            clock[0] = 121.0

        with patch.object(service.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(service, "_unchanged", side_effect=expire):
            result = self.fixture.check()
        self.assertFalse(result["ok"])
        self.assertEqual(result["metrics"]["receipt"]["outputQuality"]["timingReview"]["state"], "blocked")

    def test_expired_guard_before_publication_writes_no_decision(self) -> None:
        prepared = self.fixture.prepare()
        with patch.object(store, "recheck", side_effect=RuntimeError("TEST deadline expired")):
            with self.assertRaisesRegex(RuntimeError, "deadline"):
                self.fixture.record(self.fixture.submission(prepared))
        self.assertEqual(list((self._directory() / "decisions").iterdir()), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
