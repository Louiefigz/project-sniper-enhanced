"""Actual private store fault injection; no model, media or creator mutation."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from _timing_correction_fixture import TimingCorrectionFixture
import transcript_timing_correction as correction
import transcript_timing_correction_store as store


class TimingCorrectionFaultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = TimingCorrectionFixture()
        self.addCleanup(self.fixture.close)

    def committed(self) -> dict:
        """Commit only the fixture's explicitly labelled TEST attestations."""
        prepared = self.fixture.correct()
        return self.fixture.correct("record", self.fixture.submission(prepared))

    def test_all_committed_artifacts_are_reconstructed_not_just_self_hashed(self) -> None:
        self.committed()
        for path in sorted(self.fixture.correction_root.iterdir()):
            raw = path.read_bytes()
            path.write_bytes(raw + b" ")
            with self.assertRaises(RuntimeError):
                self.fixture.correct("status")
            path.write_bytes(raw)
        self.assertEqual(self.fixture.correct("status")["state"], "committed")

    def test_changed_commit_during_final_parent_recheck_rejects_both_reader_seams(self) -> None:
        self.committed()
        original_recheck = correction.recheck
        for name in ("decision.json", "record-claim.json", "commit.json"):
            path = self.fixture.correction_root / name
            raw = path.read_bytes()

            def late_change(value: object, guard: object) -> None:
                original_recheck(value, guard)
                path.write_bytes(raw + b" ")

            with patch.object(correction, "recheck", side_effect=late_change):
                with self.assertRaisesRegex(RuntimeError, "artifacts changed"):
                    correction.inspect_current(self.fixture.inputs, self.fixture.proposed, lambda: None)
            path.write_bytes(raw)
            with patch.object(correction, "recheck", side_effect=late_change):
                with self.assertRaisesRegex(RuntimeError, "artifacts changed"):
                    self.fixture.correct("status")
            path.write_bytes(raw)

    def test_failure_marker_overrides_otherwise_committed_output(self) -> None:
        self.committed()
        (self.fixture.correction_root / "failure.json").write_text('{"TEST":true}')
        with self.assertRaisesRegex(RuntimeError, "incomplete|fenced"):
            self.fixture.correct("status")

    def test_expired_or_malformed_caller_deadline_rejects_before_parent_reads(self) -> None:
        for deadline in (time.monotonic() - 1, float("inf"), float("nan"), True):
            inputs = replace(self.fixture.inputs, parent_deadline=deadline)
            with patch.object(correction, "capture") as capture:
                with self.assertRaisesRegex(RuntimeError, "deadline"):
                    correction.execute("prepare", inputs, self.fixture.proposed)
                capture.assert_not_called()
        self.assertFalse(self.fixture.correction_root.exists())

    def test_late_output_failure_is_fenced_and_replay_never_repairs(self) -> None:
        prepared = self.fixture.correct()
        sent = self.fixture.submission(prepared)
        original_write = store.write_new

        def fail_after_output(path: Path, payload: dict) -> None:
            original_write(path, payload)
            if path.name == "corrected-transcript.json":
                raise RuntimeError("TEST original deadline expired after output")

        with patch.object(store, "write_new", side_effect=fail_after_output):
            with self.assertRaisesRegex(RuntimeError, "deadline expired"):
                self.fixture.correct("record", sent)
        root = self.fixture.correction_root
        self.assertFalse((root / "commit.json").exists())
        self.assertTrue((root / "failure.json").exists())
        before = {path: path.read_bytes() for path in root.iterdir()}
        with self.assertRaisesRegex(RuntimeError, "incomplete|fenced"):
            self.fixture.correct("record", sent)
        self.assertEqual(before, {path: path.read_bytes() for path in root.iterdir()})

    def test_stale_original_parent_and_source_never_return_previous_revision(self) -> None:
        self.committed()
        for path in (self.fixture.plan, self.fixture.manifest, self.fixture.transcript, self.fixture.media):
            raw = path.read_bytes()
            path.write_bytes(raw + b" ")
            with self.assertRaises(RuntimeError):
                self.fixture.correct("status")
            path.write_bytes(raw)

    def test_partial_prepare_and_record_claim_are_never_automatically_repaired(self) -> None:
        self.fixture.correct()
        (self.fixture.correction_root / "record-claim.json").write_text('{"TEST":true}')
        before = {path: path.read_bytes() for path in self.fixture.correction_root.iterdir()}
        with self.assertRaisesRegex(RuntimeError, "incomplete|fenced"):
            self.fixture.correct()
        self.assertEqual(before, {path: path.read_bytes() for path in self.fixture.correction_root.iterdir()})

    def test_inspect_current_borrows_owner_guard_without_installing_wall_timer(self) -> None:
        expected = self.committed()["revision"]
        with patch.object(correction, "wall_budget", side_effect=AssertionError("nested timer")):
            actual = correction.inspect_current(self.fixture.inputs, self.fixture.proposed, lambda: None)
        self.assertEqual(actual["revision"], expected)


if __name__ == "__main__":
    unittest.main()
