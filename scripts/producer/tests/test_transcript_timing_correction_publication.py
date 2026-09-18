"""Publication source/path/clock faults preserve immutable parents and fences."""
from __future__ import annotations

import copy
from dataclasses import replace
import json
import os
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from _timing_correction_fixture import TimingCorrectionFixture
import transcript_timing_correction as correction
import transcript_timing_correction_store as store
from transcript_source_authority import bind_result, observe_source


class TimingCorrectionPublicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = TimingCorrectionFixture()
        self.addCleanup(self.fixture.close)

    def test_resealed_changed_output_still_differs_from_reconstructed_decision(self) -> None:
        prepared = self.fixture.correct()
        recorded = self.fixture.correct("record", self.fixture.submission(prepared))
        path = Path(recorded["revision"]["path"])
        payload = json.loads(path.read_bytes())
        source = payload.pop("sourceMediaAuthority")
        payload["transcript"][0]["words"][1]["start"] = 13.4
        observed = observe_source(self.fixture.media, (source["sourceSha256"], source["sourceSizeBytes"]))
        path.write_bytes(store._bytes(bind_result(payload, observed)))
        with self.assertRaisesRegex(RuntimeError, "corrected-transcript.json differs"):
            self.fixture.correct("status")

    def test_actual_earlier_monotonic_expiry_after_output_cannot_commit(self) -> None:
        prepared = self.fixture.correct()
        sent = self.fixture.submission(prepared)
        original_write, real_monotonic = store.write_new, time.monotonic
        deadline = real_monotonic() + 30
        clock = [real_monotonic()]

        def expire_after_output(path: Path, payload: dict) -> None:
            original_write(path, payload)
            if path.name == "corrected-transcript.json":
                clock[0] = deadline + 0.001

        with patch.object(store, "write_new", side_effect=expire_after_output):
            with patch.object(correction.time, "monotonic", side_effect=lambda: clock[0]):
                with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
                    correction.execute("record", replace(self.fixture.inputs, parent_deadline=deadline),
                                       self.fixture.proposed, sent)
        self.assertFalse((self.fixture.correction_root / "commit.json").exists())
        self.assertTrue((self.fixture.correction_root / "failure.json").exists())

    def test_parent_changes_after_decision_write_fence_partial_output(self) -> None:
        prepared = self.fixture.correct()
        sent = self.fixture.submission(prepared)
        original_write = store.write_new

        def change_after_decision(path: Path, payload: dict) -> None:
            original_write(path, payload)
            if path.name == "decision.json":
                self.fixture.plan.write_bytes(self.fixture.plan.read_bytes() + b" ")

        with patch.object(store, "write_new", side_effect=change_after_decision):
            with self.assertRaisesRegex(RuntimeError, "parent changed"):
                self.fixture.correct("record", sent)
        self.assertFalse((self.fixture.correction_root / "commit.json").exists())
        self.assertTrue((self.fixture.correction_root / "record-claim.json").exists())
        self.assertTrue((self.fixture.correction_root / "failure.json").exists())

    def test_unsafe_namespace_and_linked_artifacts_reject(self) -> None:
        prepared = self.fixture.correct()
        request = self.fixture.correction_root / "request.json"
        original = request.read_bytes()
        other = self.fixture.root / "TEST-request-copy.json"
        other.write_bytes(original)
        request.unlink()
        request.symlink_to(other)
        with self.assertRaises((OSError, RuntimeError)):
            self.fixture.correct("record", self.fixture.submission(prepared))
        request.unlink()
        os.link(other, request)
        with self.assertRaisesRegex(RuntimeError, "regular file"):
            self.fixture.correct("status")

    def test_source_alias_and_same_bytes_hardlink_are_not_current_source_authority(self) -> None:
        self.fixture.correct()
        alias = self.fixture.root / "TEST-hardlink-source.mp4"
        os.link(self.fixture.media, alias)
        with self.assertRaisesRegex(RuntimeError, "regular no-follow file"):
            self.fixture.correct("status")

    def test_corrupted_claim_is_not_accepted_even_with_unchanged_corrected_transcript(self) -> None:
        prepared = self.fixture.correct()
        sent = self.fixture.submission(prepared)
        self.fixture.correct("record", sent)
        path = self.fixture.correction_root / "record-claim.json"
        claim = json.loads(path.read_bytes())
        claim["submissionHash"] = "0" * 64
        path.write_bytes(store._bytes(claim))
        with self.assertRaisesRegex(RuntimeError, "record-claim.json differs"):
            self.fixture.correct("status")


if __name__ == "__main__":
    unittest.main()
