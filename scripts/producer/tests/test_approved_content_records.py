"""A record's submission is recorded on the batch clock, and check-final reads a record as submitted.

``review-submitted`` names the record's own canonical bytes at the submission time it states: every reader needs
it, so a record edited after submission is refused; ``check-final`` re-derives the approved content from the
approval in force at that recorded time, so a record submitted on an active batch still verifies after the batch
closed, and a later operator change is reported as superseding it. The real packet resolver, typed submission and
gate commands run through the TEST harness in this test's private authority root
(``_approved_content_fixture.GateFixture``); TEST media only.
"""
from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _approved_content_fixture import BATCH, CLIP, TSX, GateFixture
from studio import native_budget_store


@unittest.skipUnless(shutil.which("node") and TSX.exists(), "the typed submission needs node and the repository tsx")
class RecordedSubmissionTests(GateFixture, unittest.TestCase):
    """review-submitted: every reader needs the trail's event for the record's own bytes, and check-final reads an
    existing record as submitted, so it still verifies after its batch closed."""

    def final_record(self, name: str) -> Path:
        """A final-critic record submitted while the batch is active (stills-only TEST observations)."""
        attempt, _project = self.checked_export(name)
        result = self.packet("final-critic", ("--export", attempt))
        self.observe(result)
        self.submitted("submit-final", result)
        return Path(result["published"]["record"])

    def check_final(self, record: Path) -> dict:
        """The read-only verification status uses: `native-review.ts check-final` on an existing record."""
        checked = self.gate("review", "check-final", str(record))
        self.assertEqual(checked.returncode, 0, checked.stderr)
        return json.loads(checked.stdout)

    def submissions(self) -> list[dict]:
        """The batch trail's review-submitted events."""
        trail = native_budget_store.default_root() / "batches" / BATCH / "events.jsonl"
        return [row for row in map(json.loads, trail.read_text().splitlines()) if row.get("event") == "review-submitted"]

    def test_a_submission_is_recorded_on_the_batch_clock_and_an_edited_record_finds_none(self) -> None:
        """The event names the record's own bytes at its stated time; moving that time leaves the record unrecorded."""
        plan, result = self.passed("q1-edited")
        record_path = Path(result["published"]["record"])
        record = json.loads(record_path.read_text())
        timing = record["submission"]["timing"]
        self.assertEqual([(row["role"], row["clipId"], row["elapsed"]) for row in self.submissions()],
                         [("plan-critic", CLIP, timing["submittedElapsed"])])
        timing["submittedElapsed"] = timing["resolvedElapsed"]
        edited = record_path.with_name("EDITED-record.json")
        edited.write_text(json.dumps(record))
        refused = self.bind(plan, str(edited), "bound-edited.json")
        self.assertEqual(refused.returncode, 1, refused.stdout)
        self.assertIn("did not record the submission of record", refused.stderr)
        admitted = self.bind(plan, str(record_path), "bound-original.json")
        self.assertEqual(admitted.returncode, 0, admitted.stderr)

    def test_check_final_still_verifies_a_record_after_its_batch_closed(self) -> None:
        """Submitted on an active batch, closed, and check-final verifies it against the approval then in force."""
        record = self.final_record("q1-closed")
        before = self.check_final(record)
        self.assertEqual(before["approvalAsSubmitted"]["authorityStatus"], "active")
        self.close_batch()
        after = self.check_final(record)
        self.assertEqual(after["approvalAsSubmitted"]["authorityStatus"], "closed")
        self.assertEqual((after["status"], after["approvedContent"], after["missing"]),
                         (before["status"], before["approvedContent"], before["missing"]))
        self.assertEqual((after["approvalAsSubmitted"]["approvalIdentity"], after["approvalAsSubmitted"]["supersededBy"]),
                         (self.approval()["identity"], None))

    def test_check_final_reports_an_approval_that_superseded_the_review(self) -> None:
        """A later operator change is reported, never hidden and never read as the record's approval."""
        record = self.final_record("q1-superseded")
        answered = self.approval()["identity"]
        self.change_title("TEST operator changed title")
        report = self.check_final(record)
        self.assertEqual(report["approvalAsSubmitted"]["approvalIdentity"], answered)
        self.assertEqual(report["approvalAsSubmitted"]["supersededBy"]["identity"], self.approval()["identity"])
        self.assertEqual(report["editorialFinal"], "not-established")
        self.assertTrue(any("superseded at" in row for row in report["missing"]), report["missing"])


if __name__ == "__main__":
    unittest.main()
