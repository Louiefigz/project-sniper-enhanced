"""End to end (requirement revision approved-content-production-2026-09-27): a batch authorized with an approved title
and script -> B1 packets bind the given block from A12's real authority -> B2's submit-prebuild passes unchanged
content and refuses a pass on any departure, accepting a revise that covers it as approved-content-contradiction.

Fixture: ``_approved_content_fixture.ApprovedChainFixture`` (private authority root; TEST media; no renders).
"""
from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _approved_content_fixture import BATCH, CLIP, CONTRADICTION, OCCURRENCES, TITLE, TSX, ApprovedChainFixture
from role_packet_evidence import EvidenceDraftRequest, seal, write_draft
from test_role_packet_evidence import authored


@unittest.skipUnless(shutil.which("node") and TSX.exists(), "the typed submission needs node and the repository tsx")
class PlanChainTests(ApprovedChainFixture, unittest.TestCase):
    """Owner and plan-critic packets carry the authority's approval; the plan gate judges the build against it."""

    def test_packets_bind_the_authoritys_approval_and_omission_is_refused(self) -> None:
        """--batch/--clip bind the same identity the authority holds; leaving them out while it holds the source fails."""
        approval, plan = self.approval(), self.plan_file("q1-plan")
        self.assertEqual(self.authorized["resumed"], False)
        for role, check in (("clip-owner", "OW-19"), ("plan-critic", "PC-19")):
            packet = self.packet(role, ("--plan", plan))["packet"]
            given = packet["given"]
            self.assertEqual((given["status"], given["readFrom"], given["batchId"], given["clipId"]),
                             ("bound", "studio.production.api.read_approval", BATCH, CLIP))
            self.assertEqual((given["identity"], given["scriptSha256"]), (approval["identity"], approval["script"]))
            self.assertEqual((given["title"]["given"], given["title"]["status"], given["title"]["material"]),
                             (TITLE, "exact", False))
            self.assertTrue(all(given[key]["matches"] for key in ("selection", "captionText", "timing")))
            self.assertIn(check, [row["id"] for row in packet["checks"]])
        code, refusal = self.resolve("plan-critic", ("--plan", plan))
        self.assertEqual(code, 2)
        self.assertIn(f"['{BATCH}/{CLIP}']); name its approved title", refusal["error"])

    def test_unchanged_approved_content_submits_a_plan_pass_bound_to_the_approval(self) -> None:
        """The plan critic's pass on the given words is recorded with the authority's approval identity."""
        result = self.packet("plan-critic", ("--plan", self.plan_file("q1-plan")))
        self.observe(result)
        report = self.submitted("submit-prebuild", result)
        self.assertEqual(report["status"], "recorded-independent-plan-pass")
        record = json.loads(Path(result["published"]["record"]).read_text())
        content = record["approvedContent"]
        self.assertEqual((content["approved"]["identity"], content["approved"]["batch"], content["approved"]["clip"]),
                         (self.approval()["identity"], BATCH, CLIP))
        self.assertEqual((content["planChecked"], content["departures"], content["contradictions"]), (True, [], []))

    def test_a_changed_title_word_is_a_departure_a_pass_cannot_hide(self) -> None:
        """The packet reports the different title; a pass is refused; only a covered revise is recorded."""
        result = self.packet("plan-critic", ("--plan", self.plan_file("q1-title", title="TEST press play and share")))
        title = result["packet"]["given"]["title"]
        self.assertEqual((title["status"], title["material"], title["planned"]), ("different", True, "TEST press play and share"))
        self.observe(result)
        refused = self.submit("submit-prebuild", result)
        self.assertEqual(refused.returncode, 1, refused.stdout)
        self.assertIn("A pass cannot be recorded while the subject departs from the operator's given content", refused.stderr)
        self.observe(result, "revise", materialIssues=[{**CONTRADICTION, "scope": "execution"}])
        self.assertIn("cover it with a material issue scoped approved-content-contradiction",
                      self.submit("submit-prebuild", result).stderr)
        self.observe(result, "revise", materialIssues=[CONTRADICTION])
        report = self.submitted("submit-prebuild", result)
        self.assertEqual(report["status"], "recorded-plan-review-requires-revision")
        content = json.loads(Path(result["published"]["record"]).read_text())["approvedContent"]
        self.assertEqual((len(content["departures"]), content["contradictions"]), (1, ["TEST_GIVEN_DEPARTS"]))

    def test_reordered_or_changed_word_text_is_a_departure(self) -> None:
        """Kept words in another order, or a kept word whose text is not the transcript's, refuse a pass."""
        swapped = [OCCURRENCES[0][:2] + [11] + OCCURRENCES[0][3:5] + ["given", 0],
                   OCCURRENCES[1][:2] + [10] + OCCURRENCES[1][3:5] + ["TEST", 0], OCCURRENCES[2]]
        changed = [OCCURRENCES[0], OCCURRENCES[1][:5] + ["gifted", 0], OCCURRENCES[2]]
        for name, occurrences, fact in (("q1-order", swapped, "selection"), ("q1-text", changed, "captionText")):
            with self.subTest(name):
                result = self.packet("plan-critic", ("--plan", self.plan_file(name, occurrences=occurrences)))
                given = result["packet"]["given"]
                self.assertFalse(given[fact]["matches"])
                if fact == "selection":
                    self.assertTrue(given["selection"]["details"]["otherOrder"])
                self.observe(result)
                refused = self.submit("submit-prebuild", result)
                self.assertEqual(refused.returncode, 1, refused.stdout)
                self.assertIn("A pass cannot be recorded while the subject departs", refused.stderr)
                self.observe(result, "revise", materialIssues=[CONTRADICTION])
                self.assertEqual(self.submitted("submit-prebuild", result)["status"], "recorded-plan-review-requires-revision")

    def test_bound_shared_evidence_is_rechecked_through_the_real_context_evidence_check(self) -> None:
        """B2's submission re-runs B1's context.py --evidence-check: a record superseded after resolution is refused."""
        reference = self.put("title-reference/A01.jpg", "TEST jpeg bytes")
        selections = self.put("SELECTIONS.json", {"TEST": "selections"})

        def sealed() -> Path:
            """Draft, author and seal the next shared-evidence version."""
            draft = Path(write_draft(EvidenceDraftRequest(str(self.root / "production"), str(self.manifest), (
                f"title-reference={reference}", f"selections={selections}")))["draft"])
            draft.write_text(json.dumps(authored(json.loads(draft.read_text()))))
            return Path(seal(str(draft))["record"])
        result = self.packet("plan-critic", ("--plan", self.plan_file("q1-evidence")), "--shared-evidence", str(sealed()))
        self.assertIsNotNone(result["packet"]["sharedEvidence"])
        self.observe(result)
        sealed()
        refused = self.submit("submit-prebuild", result)
        self.assertEqual(refused.returncode, 1, refused.stdout)
        self.assertIn("Shared evidence re-check failed", refused.stderr)
        self.assertIn("is superseded by", refused.stderr)  # B1's own refusal text, from the child context.py


if __name__ == "__main__":
    unittest.main()
