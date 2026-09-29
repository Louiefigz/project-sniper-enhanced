"""Approved content is re-checked at every gate, not only at submission (adversarial probes p02-p09, p16, p19).

Each case runs the real packet resolver, the real typed submission and the real gate command (`bind-prebuild`,
`check-final`, `native-short.ts check-motion-reviews`) through the TEST harness that points the engine given check
at this test's private authority root. Fixture: ``_approved_content_fixture.GateFixture``; TEST media only.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _approved_content_fixture import BATCH, CLIP, CONTRADICTION, DEPARTED, TITLE, TSX, ApprovedChainFixture, GateFixture
from studio.native_runtime import digest


@unittest.skipUnless(shutil.which("node") and TSX.exists(), "the typed submission needs node and the repository tsx")
class ApprovalChangeGateTests(GateFixture, unittest.TestCase):
    """An approval change after a review, a closed batch, or a forged record never admits a build."""

    def test_p02_approval_changed_between_packet_and_submission_refuses_the_submission(self) -> None:
        """The packet's given block is stale once the operator changed the title; a fresh packet binds the new one."""
        plan = self.plan_file("q1-p02")
        result = self.packet("plan-critic", ("--plan", plan))
        self.change_title("TEST operator changed title")
        self.observe(result)
        refused = self.submit("submit-prebuild", result)
        self.assertEqual(refused.returncode, 1, refused.stdout)
        self.assertIn('departs from the operator\'s given content (title: the subject shows \\"TEST press play and post\\", '
                      'given \\"TEST operator changed title\\"', refused.stderr)
        fresh = self.packet("plan-critic", ("--plan", plan))["packet"]["given"]
        self.assertEqual((fresh["identity"], fresh["title"]["status"]), (self.approval()["identity"], "different"))

    def test_p03_a_recorded_pass_stops_admitting_after_the_approval_changes(self) -> None:
        """bind-prebuild admits the pass while the approval stands and refuses it after the operator's change."""
        plan, result = self.passed("q1-p03")
        record = result["published"]["record"]
        admitted = self.bind(plan, record, "bound-before.json")
        self.assertEqual(admitted.returncode, 0, admitted.stderr)
        self.change_title("TEST operator changed title")
        refused = self.bind(plan, record, "bound-after.json")
        self.assertEqual(refused.returncode, 1, refused.stdout)
        self.assertIn("A pass cannot be recorded while the subject departs", refused.stderr)

    def test_p16_a_closed_batch_binds_nothing_at_packet_time_or_at_the_gate(self) -> None:
        """Once the batch is no longer current, its approval neither binds a packet nor admits an old pass."""
        plan, result = self.passed("q1-p16")
        self.close_batch()
        refused = self.bind(plan, result["published"]["record"], "bound-closed.json")
        self.assertEqual(refused.returncode, 1, refused.stdout)
        self.assertIn("is not the current active or draining batch", refused.stderr)
        code, packet = self.resolve("plan-critic", ("--plan", plan), "--batch", BATCH, "--clip", CLIP)
        self.assertEqual(code, 2)
        self.assertIn("is not the current active or draining batch", packet["error"])

    def test_p07_a_hand_edited_record_that_drops_its_departure_is_refused_at_the_gate(self) -> None:
        """A revise record rewritten into a pass (observations re-hashed) is re-derived and refused."""
        plan = self.plan_file("q1-p07", title=DEPARTED)
        result = self.packet("plan-critic", ("--plan", plan))
        self.observe(result, "revise", materialIssues=[CONTRADICTION])
        self.submitted("submit-prebuild", result)
        record_path = Path(result["published"]["record"])
        record = json.loads(record_path.read_text())
        observations = json.loads(Path(record["evidence"][0]["path"]).read_text())
        observations.update(verdict="pass", materialIssues=[])
        hand = record_path.with_name("HAND-observations.json")
        hand.write_text(json.dumps(observations))
        record["evidence"][0] = {"path": str(hand), "sha256": digest(hand)}
        record["review"].update(verdict="pass", materialIssues=[])
        record["approvedContent"].update(departures=[], contradictions=[])
        forged = record_path.with_name("HAND-record.json")
        forged.write_text(json.dumps(record))
        refused = self.bind(plan, str(forged), "bound-p07.json")
        self.assertEqual(refused.returncode, 1, refused.stdout)
        self.assertIn("did not record the submission of record", refused.stderr)
        self.assertEqual(self.record_submitted(result["published"]["packet"], record), 0)  # the trail is unkeyed
        refused = self.bind(plan, str(forged), "bound-p07-recorded.json")
        self.assertEqual(refused.returncode, 1, refused.stdout)
        self.assertIn("A pass cannot be recorded while the subject departs", refused.stderr)

    def test_p04_p06_a_forged_or_emptied_given_block_in_a_copied_packet_is_refused(self) -> None:
        """A copied packet claiming an exact title, or not-supplied, is re-derived: its departure (or the batch) stands."""
        plan = self.plan_file("q1-p04", title=DEPARTED)
        real = self.packet("plan-critic", ("--plan", plan))
        for tag, change in (("FORGED", lambda given: given["title"].update(status="exact", material=False, planned=TITLE)),
                            ("NOTSUP", lambda given: (given.clear(), given.update(status="not-supplied", meaning="TEST")))):
            with self.subTest(tag):
                forged = self.forged_packet(real, change, tag)
                self.observe(forged)
                refused = self.submit("submit-prebuild", forged)
                self.assertEqual(refused.returncode, 1, refused.stdout)
                self.assertRegex(refused.stderr, "did not record the resolution|name its approved title|departs")

    def test_p08_a_schema_1_legacy_record_never_admits_a_short_build(self) -> None:
        """Schema 1 stays readable for display; the Short build gate refuses it."""
        plan = self.plan_file("q1-p08", title=DEPARTED)
        result = self.packet("plan-critic", ("--plan", plan))
        evidence = Path(result["published"]["packet"])
        legacy = {"schemaVersion": 1, "scope": "native-short-full-plan", "planHash": result["packet"]["subject"]["plan"]["planHash"],
                  "reviewer": {"identity": "TEST", "sessionId": "TEST-critic", "plannerSessionId": "TEST-author", "independent": True},
                  "coverage": {key: "TEST" for key in json.loads(Path(result["published"]["observations"]).read_text())["coverage"]},
                  "evidence": [{"path": str(evidence), "sha256": digest(evidence)}],
                  "review": {"schemaVersion": 1, "stage": "plan", "verdict": "pass", "summary": "TEST legacy",
                             "materialIssues": [], "findings": []}}
        file = evidence.with_name("LEGACY-record.json")
        file.write_text(json.dumps(legacy))
        refused = self.bind(plan, str(file), "bound-p08.json")
        self.assertEqual(refused.returncode, 1, refused.stdout)
        self.assertIn("needs a schema-2 plan review", refused.stderr)


@unittest.skipUnless(shutil.which("node") and TSX.exists(), "the typed submission needs node and the repository tsx")
class PreBatchReviewTests(GateFixture, unittest.TestCase):
    """p19: a pass recorded before the batch existed stops admitting once the batch holds the source."""

    def authorize_batch(self) -> dict:
        """No batch yet: the review below is recorded before production authorization."""
        return {}

    def test_p19_a_review_before_batch_start_no_longer_admits_after_authorization(self) -> None:
        plan = self.plan_file("q1-p19", title=DEPARTED)
        code, result = self.resolve("plan-critic", ("--plan", plan))
        self.assertEqual((code, result["packet"]["given"]["status"]), (0, "not-supplied"))
        self.observe(result)
        self.submitted("submit-prebuild", result)
        admitted = self.bind(plan, result["published"]["record"], "bound-before.json")
        self.assertEqual(admitted.returncode, 0, admitted.stderr)
        ApprovedChainFixture.authorize_batch(self)
        refused = self.bind(plan, result["published"]["record"], "bound-after.json")
        self.assertEqual(refused.returncode, 1, refused.stdout)
        self.assertIn("name its approved title and script with --batch", refused.stderr)


@unittest.skipUnless(shutil.which("node") and TSX.exists(), "the typed submission needs node and the repository tsx")
class BatchClockTimingTests(GateFixture, unittest.TestCase):
    """p09/p10: playback claims are timed on the batch clock from the recorded packet resolution."""

    def claim_playback(self, result: dict) -> None:
        """Declared whole-program playback of every target (nothing was played), approving picture and motion."""
        path = Path(result["published"]["observations"])
        draft = json.loads(path.read_text())
        draft["inspection"] += [{"kind": "motion-playback", "artifact": {"path": row["path"], "sha256": row["sha256"]},
                                 "span": "whole", "method": "TEST declared; nothing was played"}
                                for row in result["packet"]["submission"]["inspection"]["targets"]]
        draft["approves"] = ["picture", "motion"]
        path.write_text(json.dumps(draft))

    def test_p09_a_backdated_packet_gains_nothing_and_honest_elapsed_time_admits(self) -> None:
        """Rewriting resolvedAt an hour back is a new, unrecorded packet; the real one must wait out its claims."""
        result = self.packet("motion-critic", ("--preview", self.preview(self.staged_project("q1-p09"))))
        self.observe(result)
        self.claim_playback(result)
        early = self.submit("submit-motion", result)
        self.assertEqual(early.returncode, 1, early.stdout)
        self.assertIn("Implausible completion", early.stderr)
        back = self.forged_packet(result, lambda given: None, "BACKDATED")
        packet = json.loads(Path(back["published"]["packet"]).read_text())
        packet["resolvedAt"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        Path(back["published"]["packet"]).write_text(json.dumps(packet))
        draft = json.loads(Path(back["published"]["observations"]).read_text())
        draft["rolePacketSha256"] = digest(Path(back["published"]["packet"]))
        Path(back["published"]["observations"]).write_text(json.dumps(draft))
        forged = self.submit("submit-motion", {**back, "packet": packet})
        self.assertEqual(forged.returncode, 1, forged.stdout)
        self.assertIn("did not record the resolution", forged.stderr)
        time.sleep(2.2)  # the TEST program is 60 frames (2 s) of declared playback
        report = self.submitted("submit-motion", result)
        self.assertTrue(report["admitsFullRendering"])
        record = json.loads(Path(result["published"]["record"]).read_text())["reviews"][0]
        self.assertEqual(record["submission"]["timing"]["basis"], "batch-authority")
        packet_file = self.root / "production" / "p09-region.json"
        packet_file.write_text(json.dumps(json.loads(Path(result["packet"]["subject"]["preview"]["path"]).read_text())["packet"]))
        admitted = self.gate("short", "check-motion-reviews", result["published"]["record"], str(packet_file))
        self.assertEqual(admitted.returncode, 0, admitted.stderr)
        self.change_title("TEST operator changed title")
        refused = self.gate("short", "check-motion-reviews", result["published"]["record"], str(packet_file))
        self.assertEqual(refused.returncode, 1, refused.stdout)
        self.assertIn("A pass cannot be recorded while the subject departs", refused.stderr)


if __name__ == "__main__":
    unittest.main()
