"""End to end (requirement revision approved-content-production-2026-09-27), rendered stages: motion and final critic
packets bind the batch authority's approval (MC-13/FC-12), B2's submissions refuse a pass on a departure, and B3's
hand-off of the same TEST export records the same approval identity, lists caption display corrections without
counting them as departures and keeps the review player's label neutral.

Fixture: ``_approved_content_fixture.ApprovedChainFixture`` (private authority root; placeholder media; no renders).
"""
from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _approved_content_fixture import (BATCH, CHECKED, CLIP, OCCURRENCES, RENDERED_CONTRADICTION, TSX,
                                       ApprovedChainFixture)
from studio import native_handoff as handoff
from studio import review_player_inventory as inventory
from studio.native_handoff_confirm import Confirmation, confirm
from studio.review_player_inventory import Attempt

CORRECTION = {"occurrenceId": 1, "expectedSourceText": "given", "displayText": "Given",
              "reason": "TEST operator spelling for the display"}


@unittest.skipUnless(shutil.which("node") and TSX.exists(), "the typed submission needs node and the repository tsx")
class RenderedChainTests(ApprovedChainFixture, unittest.TestCase):
    """Motion and final critics judge the build against the given content; a departure never passes."""

    def setUp(self) -> None:
        """Checked TEST exports verify (receipt reader patched to pass): only approved content is under test."""
        super().setUp()
        self.enterContext(mock.patch.dict(inventory.RECEIPT_READERS, {CHECKED: lambda export: None}))

    def departing(self, role: str, subject: tuple[str, Path], operation: str) -> None:
        """A departure the packet reports: a pass is refused, a revise covering it is recorded."""
        result = self.packet(role, subject)
        self.assertEqual(result["packet"]["given"]["title"]["status"], "different")
        self.observe(result)
        refused = self.submit(operation, result)
        self.assertEqual(refused.returncode, 1, refused.stdout)
        self.assertIn("A pass cannot be recorded while the subject departs", refused.stderr)
        self.observe(result, "revise", materialIssues=[RENDERED_CONTRADICTION])
        report = self.submitted(operation, result)
        self.assertEqual(report["approvedContent"]["contradictions"], ["TEST_GIVEN_DEPARTS"])

    def test_motion_critic_mc13_binds_the_approval_and_refuses_a_departing_pass(self) -> None:
        """Unchanged content: a stills-only pass is recorded (picture only, admits nothing); a changed title is refused."""
        project = self.staged_project("q1-native-v1")
        result = self.packet("motion-critic", ("--preview", self.preview(project)))
        packet = result["packet"]
        self.assertIn("MC-13", [row["id"] for row in packet["checks"]])
        self.assertEqual(packet["given"]["identity"], self.approval()["identity"])
        self.assertIn("motion-playback", packet["obligations"]["playbackListening"]["statement"])
        self.observe(result)
        report = self.submitted("submit-motion", result)
        self.assertEqual(report["status"], "recorded-motion-review-picture-only")
        record = json.loads(Path(result["published"]["record"]).read_text())
        approved = record["reviews"][0]["approvedContent"]["approved"]
        self.assertEqual((approved["identity"], approved["clip"]), (self.approval()["identity"], CLIP))
        changed = self.staged_project("q1-native-v2", title="TEST press play and share")
        self.departing("motion-critic", ("--preview", self.preview(changed)), "submit-motion")

    def test_final_critic_fc12_binds_the_approval_and_refuses_a_departing_pass(self) -> None:
        """Unchanged content: a stills-only pass is recorded, never an editorial final; changed words are refused."""
        attempt, _project = self.checked_export("Final")
        result = self.packet("final-critic", ("--export", attempt))
        self.assertIn("FC-12", [row["id"] for row in result["packet"]["checks"]])
        self.observe(result)
        report = self.submitted("submit-final", result)
        self.assertEqual((report["status"], report["editorialFinal"]),
                         ("recorded-independent-rendered-pass-not-final", "not-established"))
        self.assertEqual(report["approvedContent"]["approved"]["identity"], self.approval()["identity"])
        changed, _project = self.checked_export("Final-v2", title="TEST press play and share")
        self.departing("final-critic", ("--export", changed), "submit-final")

    def test_handoff_records_the_same_approval_and_a_caption_correction_is_not_a_departure(self) -> None:
        """Packet, final review and hand-off carry one identity; the correction is listed; the label stays neutral."""
        attempt, project = self.checked_export("Corrected", corrections=[CORRECTION])
        identity = self.approval()["identity"]
        result = self.packet("final-critic", ("--export", attempt))
        caption = result["packet"]["given"]["captionText"]
        self.assertTrue(caption["matches"])
        self.assertEqual([(row["occurrenceId"], row["displayText"], row["changesGivenSpelling"])
                          for row in caption["details"]["displayCorrections"]], [(1, "Given", True)])
        self.observe(result)
        self.assertEqual(self.submitted("submit-final", result)["approvedContent"]["departures"], [])
        player = self.serve_player([Attempt("Q1", "TEST Q1", attempt)])
        record = handoff.hand_off(self.request("handoff-q1.json", attempt=attempt, player=player))
        self.assertEqual((record["status"], record["failures"]), ("views-ready", []))
        content = record["content"]
        self.assertEqual((content["operatorApproval"]["status"], content["operatorApproval"]["approval"]["identity"]),
                         ("supplied", identity))
        self.assertEqual((content["operatorApproval"]["batchId"], content["operatorApproval"]["clipId"]), (BATCH, CLIP))
        self.assertEqual([content[key] for key in ("title", "wordsMatchApproval", "wordTextsMatchApproval",
                                                   "clipMatchesApproval")], ["exact", True, True, True])
        self.assertEqual([(row["occurrenceId"], row["sourceText"], row["displayText"]) for row in content["displayCorrections"]],
                         [(1, "given", "Given")])
        self.assertEqual((record["output"]["reviewState"], record["output"]["label"]), ("checked", inventory.CHECKED_LABEL))
        self.assertNotIn("FINAL", record["output"]["label"])
        self.assertEqual(record["project"]["path"], str(project))
        self.assertEqual(self.page_playback(player, record["reviewPlayer"]["route"]), 204)
        pages = (record["reviewPlayer"]["url"], record["studio"]["url"], "TEST Chrome", "TEST coordinator session")
        visible = confirm(Confirmation(self.root / "handoff-q1.json", self.root / "visible-q1.json", pages, 10.0))
        self.assertEqual((visible["status"], visible["failures"]), ("visible-handoff", []))

    def test_handoff_of_a_build_that_departs_names_it_and_changes_nothing(self) -> None:
        """Other word order in the build: the hand-off records the mismatch against the same authority approval."""
        swapped = [OCCURRENCES[0][:2] + [11] + OCCURRENCES[0][3:5] + ["given", 0],
                   OCCURRENCES[1][:2] + [10] + OCCURRENCES[1][3:5] + ["TEST", 0], OCCURRENCES[2]]
        attempt, project = self.checked_export("Swapped", occurrences=swapped)
        before = (project / "SHORT-PROJECT.json").read_bytes()
        player = self.serve_player([Attempt("Q1", "TEST Q1", attempt)])
        record = handoff.hand_off(self.request("handoff-swapped.json", attempt=attempt, player=player))
        self.assertEqual([row["code"] for row in record["failures"]], ["APPROVED_CONTENT_DIFFERS_FROM_BUILD"])
        self.assertTrue(record["content"]["sameWordsOtherOrder"])
        self.assertEqual(record["content"]["operatorApproval"]["approval"]["identity"], self.approval()["identity"])
        self.assertEqual((project / "SHORT-PROJECT.json").read_bytes(), before)

    def test_p17_an_export_the_batch_charged_needs_its_folder_binding(self) -> None:
        """The export names batch-test/Q1: an unbound folder, or the same path recreated, is APPROVAL_BINDING_MISSING."""
        attempt, _project = self.checked_export("Unbound", bind=False)
        record = handoff.hand_off(self.request("handoff-unbound.json", attempt=attempt,
                                               player=self.serve_player([Attempt("Q1", "TEST Q1", attempt)])))
        self.assertEqual([row["code"] for row in record["failures"]], ["APPROVAL_BINDING_MISSING"])
        self.assertEqual(record["content"]["operatorApproval"]["approval"]["identity"], self.approval()["identity"])
        bound, project = self.checked_export("Recreated")
        copy = project.with_name(project.name + "-copy")
        shutil.copytree(project, copy)
        shutil.rmtree(project)
        copy.rename(project)  # same path and bytes, a new folder identity the batch never bound
        record = handoff.hand_off(self.request("handoff-recreated.json", attempt=bound,
                                               player=self.serve_player([Attempt("Q1", "TEST Q1", bound)])))
        self.assertIn("APPROVAL_BINDING_MISSING", [row["code"] for row in record["failures"]])

    def test_p12_shifted_cut_seconds_differ_from_the_approval_at_hand_off(self) -> None:
        """The same words behind cut seconds the operator did not approve are reported, never repaired."""
        self.enterContext(mock.patch("_approved_content_fixture.CUTS", [{"start": 10.0, "end": 11.6, "speed": 1},
                                                                        {"start": 13.0, "end": 13.5, "speed": 1}]))
        attempt, _project = self.checked_export("Shifted")
        record = handoff.hand_off(self.request("handoff-shifted.json", attempt=attempt,
                                               player=self.serve_player([Attempt("Q1", "TEST Q1", attempt)])))
        self.assertEqual([row["code"] for row in record["failures"]], ["APPROVED_CONTENT_DIFFERS_FROM_BUILD"])
        self.assertEqual((record["content"]["secondsMatchApproval"], record["content"]["wordsMatchApproval"]), (False, True))


if __name__ == "__main__":
    unittest.main()
