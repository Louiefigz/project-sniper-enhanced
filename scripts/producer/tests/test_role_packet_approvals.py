"""Given titles and scripts (revision approved-content-production-2026-09-27): read only from the batch authority,
verified by approval-v2 identity and reported as separate title / selection / caption-text / timing facts.

The packet reads unit A1/A2's real `studio.production.api.read_approval`; these unit cases patch that function with
a TEST reader answering from `self.approvals` (the end-to-end chain through the real authority is
test_approved_content_chain.py). Fixtures are TEST-labelled.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import copy
import json
import sys
import unicodedata
import unittest
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import role_packet_approvals as approvals
import role_packet_given as given_module
import role_packet_given_check as given_check
from role_packet_approvals import ApprovalError
from role_packet_transcript import observe_transcript
from role_packets import RoleRequest, resolve_role_packet
from test_role_packet_evidence import REPO, EvidenceFixture

CONTRACT = Path(__file__).resolve().parent / "fixtures" / "role-packet-given-contract.json"
# Computed by unit A1/A2's own studio.native_budget_selection (worktree impl-a12-tasks, approval-v2) and copied here.
A12_VECTOR = {"script": {"sourceSha256": "a" * 64, "transcriptSha256": "b" * 64, "transcriptWords": 25,
                         "wordRanges": [[10, 11], [13, 13]], "wordTexts": ["TEST", "given", "words"],
                         "ranges": [[10.0, 11.5], [13.0, 13.5]]},
              "title": "TEST Café “quoted”",
              "scriptSha256": "4ed23671555fe3d0b6c76aaf3b71e0eba17ae263cc382b0fbc3e6775eca4e76e",
              "titleSha256": "bd1244382869516d50b8a831d9232b7310e090ca63f78e4dc6e244453f44a5ee",
              "identity": "18732dd28bd1c7252ac4b9127bb3222321c23d67657f7bbe9f8ce91d45e649c4",
              "compare": {"TEST Café “quoted”": "normalization-only", " TEST  Café “quoted” ": "normalization-only",
                          "test Café “quoted”": "different", 'TEST Café "quoted"': "different"}}
WORDS = [[0, 0, 10, 0, 15, "TEST", 0], [1, 0, 11, 30, 45, "given", 0], [2, 1, 13, 45, 60, "words", 0]]
CUTS = [{"start": 10.0, "end": 11.5, "speed": 1}, {"start": 13.0, "end": 13.5, "speed": 1}]
SEGMENTS = [{"startFrame": 0, "endFrameExclusive": 45}, {"startFrame": 45, "endFrameExclusive": 60}]


def shape(value: object) -> object:
    """Keys and leaf kinds of a JSON value (lists by their first element)."""
    if isinstance(value, dict):
        return {key: shape(item) for key, item in value.items()}
    if isinstance(value, list):
        return [shape(value[0])] if value else []
    return "null" if value is None else type(value).__name__


class AuthorityFixture(EvidenceFixture):
    """A TEST authority reader, approval-v2 rows derived from the TEST transcript and consistent plans."""

    def setUp(self) -> None:
        """Patch the authority reader the packet calls with a TEST reader (tests only)."""
        super().setUp()
        self.approvals: dict[tuple[str, str], dict] = {}
        self.enterContext(patch.object(given_module.authority, "read_approval", lambda root, batch, clip: self.approvals.get(
            (batch, clip)) or {"batchId": batch, "clipId": clip, "status": "active", "current": None, "history": [],
                               "canonicalForm": approvals.CANONICAL_FORM}))
        self.current = ["batch-test"]  # TEST: the batches the registry reports active or draining
        self.enterContext(patch.object(given_module, "current_batches", lambda root: [(name, {}) for name in self.current]))
        self.resolved: list[tuple] = []  # TEST: packet resolutions the batch trail would record (no real batch here)
        self.enterContext(patch.object(given_check, "record_packet_resolved", lambda root, packet: (
            self.resolved.append((packet.batch, packet.clip, packet.role, packet.sha256)) or {"elapsed": 0.0})))

    def approve(self, given_title: str | None, word_ranges: list | None = None, **fields: object) -> dict:
        """Record batch-test/Q1's current approval as A1/A2's reader returns it (fields override the derived row)."""
        transcript = observe_transcript(str(self.transcript), 60.0)
        row = approvals.approval_row(given_title, approvals.derive_script(json.loads(self.manifest.read_text())["sources"][0]
                                                                     ["sourceSha256"], transcript, word_ranges or [[10, 11], [13, 13]]))
        found = {"batchId": "batch-test", "clipId": "Q1", "status": "active", "current": {**row, "recordedBy": "TEST", **fields},
                 "history": [row], "canonicalForm": approvals.CANONICAL_FORM}
        self.approvals[("batch-test", "Q1")] = found
        return found

    def given_plan(self, title: str | None, words: list, extra_canvas: dict | None = None) -> Path:
        """A TEST plan whose kept words, frames and cuts are consistent with the TEST transcript."""
        plan = self.evidence_plan()
        value = json.loads(plan.read_text())
        value["canvas"] = {**value["canvas"], "occurrences": words, "cuts": CUTS, "segments": SEGMENTS, **(extra_canvas or {})}
        value["catalogTitle"] = {"file": "compositions/title.html", "copy": {"text": title}}
        plan.write_text(json.dumps(value))
        return plan

    def given(self, plan: Path, role: str = "plan-critic", batch: str | None = "batch-test", clip: str | None = "Q1") -> dict:
        """The packet's `given` block."""
        request = RoleRequest(role=role, plan=str(plan), batch=batch, clip=clip)
        return resolve_role_packet(request, REPO)["packet"]["given"]


class CanonicalFormTests(unittest.TestCase):
    """Byte-compatible with the batch authority's approval-v2 form and title rules."""

    def test_identities_and_title_comparison_match_the_authority_vector(self) -> None:
        """Script, title and approval identities and the title comparison states equal A1/A2's own output."""
        self.assertEqual(approvals.script_identity(A12_VECTOR["script"]), A12_VECTOR["scriptSha256"])
        self.assertEqual(approvals.title_identity(A12_VECTOR["title"]), A12_VECTOR["titleSha256"])
        self.assertEqual(approvals.approval_identity(A12_VECTOR["title"], A12_VECTOR["scriptSha256"]), A12_VECTOR["identity"])
        for observed, state in A12_VECTOR["compare"].items():
            self.assertEqual(approvals.compare_titles(A12_VECTOR["title"], observed), state, observed)

    def test_the_merged_authority_computes_the_same_vector(self) -> None:
        """The integrated A1/A2 selection module reproduces the copied vector and B1's form byte for byte."""
        from studio import native_budget_selection as authority_form
        self.assertEqual(authority_form.CANONICAL_FORM, approvals.CANONICAL_FORM)
        self.assertEqual(authority_form.script_identity(A12_VECTOR["script"]), A12_VECTOR["scriptSha256"])
        self.assertEqual(authority_form.title_identity(A12_VECTOR["title"]), A12_VECTOR["titleSha256"])
        self.assertEqual(authority_form.approval_identity(A12_VECTOR["title"], A12_VECTOR["scriptSha256"]),
                         A12_VECTOR["identity"])
        for observed, state in A12_VECTOR["compare"].items():
            self.assertEqual(authority_form.compare_titles(A12_VECTOR["title"], observed), state, observed)

    def test_title_contract_and_range_bounds(self) -> None:
        """createUserTitleCopy limits apply; a huge range is refused before it is expanded."""
        for bad in ("   ", "T" * 121, "TEST\nline", "TEST line", "TEST\x7f"):
            self.assertIsNotNone(approvals.title_problem(bad), repr(bad))
        self.assertIsNone(approvals.title_problem("🎬" * 60))
        self.assertIn("at most 1024 words", approvals.ranges_problem([[0, 10 ** 12]], 10 ** 13))
        self.assertIn("do not overlap", approvals.ranges_problem([[1, 3], [2, 4]], 10))


class GivenFactsTests(AuthorityFixture):
    """Title, selection, caption text and timing are separate facts computed from the authority's approval."""

    def test_exact_given_content_matches_the_contract_shape(self) -> None:
        """All facts match; the block has exactly the documented shape; PC-19 joins the checks."""
        self.approve("TEST given title")
        plan = self.given_plan("TEST given title", WORDS, {"captionCorrections": [
            {"occurrenceId": 1, "expectedSourceText": "given", "displayText": "Given", "reason": "TEST operator spelling"}]})
        packet = resolve_role_packet(RoleRequest(role="plan-critic", plan=str(plan), batch="batch-test", clip="Q1"),
                                     REPO)["packet"]
        given = packet["given"]
        self.assertEqual((given["title"]["status"], given["title"]["material"]), ("exact", False))
        self.assertEqual([given[key]["matches"] for key in ("selection", "captionText", "timing")], [True, True, True])
        correction = given["captionText"]["details"]["displayCorrections"][0]
        self.assertEqual((correction["givenText"], correction["displayText"], correction["changesGivenSpelling"]),
                         ("given", "Given", True))
        self.assertIn("PC-19", [row["id"] for row in packet["checks"]])
        contract = json.loads(CONTRACT.read_text())["examples"]
        self.assertEqual(shape({**given, "identity": "x", "scriptSha256": "x", "titleSha256": "x"}),
                         shape({**contract["bound"], "identity": "x", "scriptSha256": "x", "titleSha256": "x"}))
        self.assertEqual(self.given(plan, batch=None, clip=None), contract["notSupplied"])

    def test_changed_text_and_moved_frames_on_same_indices_never_match(self) -> None:
        """Verifier P1: occurrence 0's text and frames change while indices stay; caption text and timing fail."""
        self.approve("TEST given title")
        changed = copy.deepcopy(WORDS)
        changed[0][5], changed[0][3], changed[0][4] = "UNAPPROVED_CHANGED_TEXT", 15, 29
        given = self.given(self.given_plan("TEST given title", changed))
        self.assertTrue(given["selection"]["matches"])
        self.assertEqual((given["captionText"]["matches"], given["captionText"]["details"]["mismatchedOccurrences"]),
                         (False, [0]))
        self.assertEqual((given["timing"]["matches"], given["timing"]["details"]["frameMismatches"]), (False, [0]))

    def test_order_repeats_bounds_and_segment_mapping_are_reported_apart(self) -> None:
        """Reordering, a repeated word, an out-of-range index and a word mapped to the wrong segment each show."""
        self.approve("TEST given title")
        self.assertTrue(self.details([WORDS[1], WORDS[0], WORDS[2]], "selection")["otherOrder"])
        self.assertEqual(self.details([*WORDS, [3, 1, 13, 45, 60, "words", 0]], "selection")["repeatedWords"], [13])
        self.assertEqual(self.details([*WORDS[:2], [2, 1, 99, 45, 60, "words", 0]], "selection")["outOfRangeWords"], [99])
        self.assertEqual(self.details([WORDS[0], WORDS[1], [2, 0, 13, 45, 60, "words", 0]], "timing")["segmentMismatches"],
                         [2])

    def details(self, words: list, key: str) -> dict:
        """One fact's details for a plan keeping these words."""
        return self.given(self.given_plan("TEST given title", words))[key]["details"]

    def test_titles_compare_exact_normalization_only_or_different_and_titlecard_wins(self) -> None:
        """NFD and whitespace are not material; one character, case or quotes are; the titleCard copy is read first."""
        title = unicodedata.normalize("NFC", "TEST Café “given”")
        self.approve(title)
        for planned, state in ((unicodedata.normalize("NFD", title), "normalization-only"),
                               (" " + title.replace(" ", "  ") + " ", "normalization-only"),
                               (title.replace("é", "e"), "different"), (title.upper(), "different"),
                               (title.replace("“", '"'), "different")):
            facts = self.given(self.given_plan(planned, WORDS))["title"]
            self.assertEqual((facts["status"], facts["material"]), (state, state == "different"), repr(planned))
        card = self.given(self.given_plan("TEST other", WORDS, {"titleCard": {"copy": {"text": title}}}))["title"]
        self.assertEqual((card["planned"], card["status"]), (title, "exact"))


class AuthorityRefusalTests(AuthorityFixture):
    """Every way to skip, forge or mismatch the authority's approval is refused with a specific error."""

    def test_missing_approval_forged_row_or_foreign_short_is_refused(self) -> None:
        """No current approval, a recomputation mismatch, an unbuildable title or another Short's selection."""
        plan = self.given_plan("TEST given title", WORDS)
        with self.assertRaisesRegex(ApprovalError, "batch batch-test clip Q1 has no approved title/script"):
            self.given(plan)
        self.approve("TEST given title", script="0" * 64)
        with self.assertRaisesRegex(ApprovalError, "identities do not recompute"):
            self.given(plan)
        self.approve("TEST given title", wordTexts=["TEST", "given", "forged"])
        with self.assertRaisesRegex(ApprovalError, "observed transcript"):
            self.given(plan)
        self.approve("TEST given title", title="TEST line\nbreak")
        with self.assertRaisesRegex(ApprovalError, "single-line"):
            self.given(plan)
        self.approve("TEST given title", [[20, 24]])
        with self.assertRaisesRegex(ApprovalError, "not batch batch-test clip Q1's Short"):
            self.given(plan)

    def test_only_the_current_active_or_draining_batch_binds_given_content(self) -> None:
        """Another current batch, no current batch, or a closed status refuses the packet (probe p16)."""
        plan = self.given_plan("TEST given title", WORDS)
        self.approve("TEST given title")
        for current in ([], ["batch-newer"], ["batch-test", "batch-newer"]):
            self.current = current
            with self.subTest(current=current), self.assertRaisesRegex(ApprovalError, "not the current active or draining"):
                self.given(plan)
        self.current = ["batch-test"]
        self.approvals[("batch-test", "Q1")]["status"] = "closed"
        with self.assertRaisesRegex(ApprovalError, "batch batch-test is closed"):
            self.given(plan)

    def test_a_missing_approved_title_is_a_material_departure(self) -> None:
        """A legacy approval row without a title never lets the plan's own title pass as given."""
        found = self.approve("TEST given title")
        found["current"] = {**found["current"], **approvals.approval_row(None, {**{key: found["current"][key] for key in (
            "wordRanges", "wordTexts", "ranges")}, "sourceSha256": found["current"]["source"],
            "transcriptSha256": found["current"]["transcript"], "transcriptWords": found["current"]["transcriptWords"]})}
        title = self.given(self.given_plan("TEST agent-authored title", WORDS))["title"]
        self.assertEqual((title["given"], title["status"], title["material"]), (None, "different", True))

    def test_omission_is_refused_while_a_live_batch_holds_the_source(self) -> None:
        """Without --batch/--clip a packet is refused whenever a batch holds the plan's recording; half a pair too."""
        plan = self.given_plan("TEST given title", WORDS)
        self.assertEqual(self.given(plan, batch=None, clip=None)["status"], "not-supplied")
        source = json.loads(self.manifest.read_text())["sources"][0]["sourceSha256"]
        record = {"clips": {"Q1": {"projects": [{"selection": {"source": source, "ranges": [[10.0, 11.5], [13.0, 13.5]]}}]}}}
        with patch.object(given_module, "live_records", return_value=[("batch-test", record)]):
            with self.assertRaisesRegex(ApprovalError, r"\['batch-test/Q1'\]\); name its approved title"):
                self.given(plan, batch=None, clip=None)
        with self.assertRaisesRegex(ApprovalError, "--batch and --clip name one clip together"):
            self.given(plan, clip=None)

    def test_a_real_batch_claiming_the_recording_forbids_omission(self) -> None:
        """A batch started in the (private) authority with this recording among its claims refuses an unnamed packet."""
        from studio.native_budget_batches import create_batch
        from studio.native_budget_clock import start_anchor
        from studio.native_budget_policy import BatchSpec, new_batch_record
        source = json.loads(self.manifest.read_text())["sources"][0]["sourceSha256"]
        from studio import native_budget_store
        create_batch(native_budget_store.default_root(), new_batch_record(BatchSpec("batch-test", ("Q1", "Q2"), (source,), 1),
                                                             start_anchor()))
        with self.assertRaisesRegex(ApprovalError, r"\['batch-test/\*'\]\); name its approved title"):
            self.given(self.given_plan("TEST given title", WORDS), batch=None, clip=None)

    def test_owner_packet_carries_the_verbatim_title_rule(self) -> None:
        """OW-19 tells the author to use the given title verbatim and skip the Director hook fill."""
        self.approve("TEST given title")
        packet = resolve_role_packet(RoleRequest(role="clip-owner", plan=str(self.given_plan("TEST given title", WORDS)),
                                                 batch="batch-test", clip="Q1"), REPO)["packet"]
        rule = next(row["check"] for row in packet["checks"] if row["id"] == "OW-19")
        self.assertIn("skip the Director hook fill and title critique", rule)


class IndexSpaceTests(AuthorityFixture):
    """One index space: a transcript where the writer would drop or reorder words is refused."""

    def test_zero_duration_late_or_reordered_words_and_other_formats_are_refused(self) -> None:
        """The writer's kept-word numbering must equal the raw numbering, or the transcript is refused."""
        from role_packet_files import ArtifactError
        payload = json.loads(self.transcript.read_text())
        cases = ((lambda words: words[5].update(end=words[5]["start"]), "drops words \\[5\\]"),
                 (lambda words: words[6].update(start=4.9, end=5.2), "reorders words \\[6\\]"),
                 (lambda words: words[24].update(start=60.0, end=61.0), "drops words \\[24\\]"))
        for change, message in cases:
            value = copy.deepcopy(payload)
            change(value["transcript"][0]["words"])
            self.transcript.write_text(json.dumps(value))
            with self.subTest(message), self.assertRaisesRegex(ArtifactError, message):
                observe_transcript(str(self.transcript), 60.0)
        self.transcript.write_text(json.dumps({"words": payload["transcript"][0]["words"]}))
        with self.assertRaisesRegex(ArtifactError, "not an utterance transcript"):
            observe_transcript(str(self.transcript), 60.0)


if __name__ == "__main__":
    unittest.main()
