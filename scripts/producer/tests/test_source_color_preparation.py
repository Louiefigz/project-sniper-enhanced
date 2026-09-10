"""All-source eligibility tests; inert source bytes and TEST-stubbed admission only."""
from __future__ import annotations

import time
import unittest
from copy import deepcopy
from unittest.mock import patch

from _source_color_preparation_fixture import SourceColorPreparationFixture
from color import grade_project_authority as authority
from color.grade_observation_profile import V1, V2, V2_PROFILE
from cut_preview_io import digest
from guided_source_color_preparation import prepare_source_color_jobs


class SourceColorPreparationTests(unittest.TestCase):
    """One complete explicit source map or no prepared records at all."""

    def setUp(self) -> None:
        """Keep the entire metadata test under one fixed original fake clock."""
        clock = patch.object(time, "monotonic", return_value=1000.0)
        clock.start()
        self.addCleanup(clock.stop)
        self.fixture = SourceColorPreparationFixture()
        self.addCleanup(self.fixture.cleanup)

    def run_preparation(self) -> tuple:
        """Call the real preparation helper, never a decoder or job writer."""
        fixture = self.fixture
        return prepare_source_color_jobs(fixture.inputs, fixture.declarations, fixture.context)

    def test_first_occurrence_order_and_same_original_capture_objects(self) -> None:
        """Repeated cuts share source preparation; manifest/map order is not source order."""
        rows = self.run_preparation()
        self.assertEqual([row.binding.source_id for row in rows], ["raw-b", "raw-a"])
        captured = {row.path: row for row in self.fixture.inputs.verified_media.snapshots}
        for row in rows:
            self.assertIs(row.source, captured[row.source.path])
            self.assertIs(row.profile, V1)
            self.assertIs(row.executable, False)
            self.assertIs(row.grade_applicable, False)
            self.assertIs(row.delivery_approved, False)
        self.assertFalse((self.fixture.producer / ".sniper-grade-observations").exists())

    def test_binding_matches_existing_real_grade_authority_math_and_history_domain(self) -> None:
        """The actual authority parser is reused with only its admission leaf TEST-stubbed."""
        for prepared in self.run_preparation():
            metadata = prepared.record()
            value = {"schemaVersion": 1, "policy": V1.project_policy, "producerDir": str(self.fixture.producer),
                     "sourceId": metadata["sourceId"], "declaration": metadata["declaration"], "expected": metadata["expected"]}
            with patch.object(authority, "execution_media_authority_entries", return_value=self.fixture.entries):
                held = authority.observe_project(value)
            self.assertEqual(metadata["binding"], held["binding"])
        self.assertEqual(prepared.binding.project_history_sha256, digest({
            "projectSha256": self.fixture.context.parents.expected["projectSha256"], "history": self.fixture.project["history"]}))

    def test_explicit_v2_remains_observational_not_a_bt709_substitute(self) -> None:
        """Unknown history is accepted only by the explicitly selected existing V2 parser."""
        row = self.fixture.declarations["raw-a"]
        row.update(profile=V2_PROFILE)
        row["declaration"].update(schemaVersion=2, sourceProfile="unknown", historyState="unknown")
        prepared = self.run_preparation()[1]
        self.assertIs(prepared.profile, V2)
        self.assertEqual(prepared.record()["profile"], V2_PROFILE)
        self.assertEqual(prepared.record()["declaration"]["historyState"], "unknown")
        self.assertIs(prepared.executable, False)

    def test_v1_unknown_history_is_not_filled_or_changed(self) -> None:
        """A missing history fact must not become a fabricated known declaration."""
        self.fixture.declarations["raw-a"]["declaration"]["historyState"] = "unknown"
        with self.assertRaisesRegex(ValueError, "known operator-declared history"):
            self.run_preparation()

    def test_missing_or_extra_source_declarations_reject_before_parent_reads(self) -> None:
        """Map coverage must be exact, not an implicit first-source default."""
        self.fixture.declarations.pop("raw-a")
        with patch("guided_source_color_preparation.read_bytes", side_effect=AssertionError("no parent work")), \
                self.assertRaisesRegex(RuntimeError, "exactly every used source"):
            self.run_preparation()
        self.fixture.declarations["raw-a"] = self.fixture.declaration("raw-a")
        self.fixture.declarations["unused"] = self.fixture.declaration("unused")
        with self.assertRaisesRegex(RuntimeError, "exactly every used source"):
            self.run_preparation()

    def test_omitted_or_unknown_profile_rejects_without_job_or_parent_work(self) -> None:
        """Even V1 selection is explicit; no default from missing profile or declaration."""
        self.fixture.declarations["raw-a"].pop("profile")
        with self.assertRaisesRegex(ValueError, "missing or unknown fields"):
            self.run_preparation()
        self.fixture.declarations["raw-a"]["profile"] = "large-bt709-invented"
        with patch("guided_source_color_preparation.read_bytes", side_effect=AssertionError("no parent work")), \
                self.assertRaisesRegex(ValueError, "unsupported"):
            self.run_preparation()

    def test_extra_declaration_selection_payload_is_not_ignored(self) -> None:
        """No override/timeout/automatic-policy field may cross the closed map boundary."""
        self.fixture.declarations["raw-a"]["timeoutSeconds"] = 9999
        with self.assertRaisesRegex(ValueError, "missing or unknown fields"):
            self.run_preparation()

    def test_incomplete_source_groups_cannot_be_inferred(self) -> None:
        """Every full-source frame belongs to the explicit declared coverage."""
        self.fixture.declarations["raw-a"]["declaration"]["lightingGroups"][0]["endFrame"] = 23
        with self.assertRaisesRegex(ValueError, "cover the complete source"):
            self.run_preparation()

    def test_empty_or_malformed_cut_cannot_create_empty_success(self) -> None:
        """No used source is a malformed preparation request, not successful observation."""
        self.fixture.inputs.documents["acceptedPlan"]["cutTrack"] = []
        with self.assertRaisesRegex(RuntimeError, "bounded nonempty cut"):
            self.run_preparation()

    def test_changed_candidate_or_saved_cut_rejects_exact_numeric_type_drift(self) -> None:
        """A changed source/cut or 0→0.0 coercion is not the identical accepted cut."""
        self.fixture.inputs.documents["candidatePlan"]["cutTrack"][0]["start"] = 0.0
        with self.assertRaisesRegex(RuntimeError, "saved/accepted/candidate cut differs"):
            self.run_preparation()

    def test_saved_cut_source_change_rejects_without_mutating_accepted_inputs(self) -> None:
        """The explicit current saved parents cannot quietly move to different sources."""
        accepted = deepcopy(self.fixture.inputs.documents["acceptedPlan"])
        self.fixture.plan["cutTrack"][0]["end"] = 0.5
        self.fixture.refresh()
        self.fixture.inputs.documents["acceptedPlan"] = accepted
        with self.assertRaisesRegex(RuntimeError, "saved/accepted/candidate cut differs"):
            self.run_preparation()

    def test_current_manifest_sha_and_original_opening_manifest_must_agree(self) -> None:
        """A current separately hashed manifest is not enough when original input differs."""
        self.fixture.inputs.value["documents"]["manifest"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(RuntimeError, "current manifest differs"):
            self.run_preparation()

    def test_manifest_admission_lane_and_exact_source_size_are_checked(self) -> None:
        """Source selection cannot borrow a broll lane or a numerically coerced size."""
        self.fixture.entries[0]["lane"] = "broll"
        self.fixture.refresh()
        with self.assertRaisesRegex(RuntimeError, "original admitted snapshot"):
            self.run_preparation()
        self.fixture.entries[0]["lane"] = "source"
        self.fixture.rows[0]["sourceSizeBytes"] = float(self.fixture.rows[0]["sourceSizeBytes"])
        self.fixture.refresh()
        with self.assertRaisesRegex(RuntimeError, "manifest/admission size differs"):
            self.run_preparation()

    def test_manifest_source_sha_does_not_override_initial_hash_capture(self) -> None:
        """A source row must retain the exact original admission identity."""
        self.fixture.rows[0]["sourceSha256"] = "0" * 64
        self.fixture.refresh()
        with self.assertRaisesRegex(RuntimeError, "disagrees with admission authority"):
            self.run_preparation()

    def test_duplicate_used_manifest_id_is_ambiguous(self) -> None:
        """No first-match selection from repeated source IDs."""
        self.fixture.manifest["sources"].append(deepcopy(self.fixture.rows[0]))
        self.fixture.refresh()
        with self.assertRaisesRegex(RuntimeError, "missing or duplicated"):
            self.run_preparation()

    def test_whole_program_pixel_budget_is_not_widened_for_long_raw(self) -> None:
        """20-minute 1080p30 is outside unchanged V1, even with a short accepted cut."""
        facts = self.fixture.receipts["raw-a"]["decoded"]["facts"]
        facts.update(width=1920, height=1080, declaredFrames=36000, durationSeconds=1200)
        self.fixture.rows[0].update(frameRate="30/1", fps=30)
        self.fixture.declarations["raw-a"]["declaration"]["lightingGroups"][0]["endFrame"] = 36000
        self.fixture.refresh()
        with self.assertRaisesRegex(ValueError, "frame/pixel budget exceeded"):
            self.run_preparation()
        self.assertFalse((self.fixture.producer / ".sniper-grade-observations").exists())

    def test_boolean_frame_expectation_is_not_an_integer(self) -> None:
        """Do not let bool/int equality qualify malformed admission expectations."""
        self.fixture.receipts["raw-a"]["decoded"]["facts"]["declaredFrames"] = True
        self.fixture.refresh()
        with self.assertRaises((ValueError, RuntimeError)):
            self.run_preparation()

    def test_failed_admission_flags_are_preserved_as_failure_not_upgraded(self) -> None:
        """TEST-stubbed false decoder flags must not produce eligible preparations."""
        self.fixture.receipts["raw-a"]["decoded"]["decoded"] = False
        self.fixture.refresh()
        with self.assertRaises(RuntimeError):
            self.run_preparation()

    def test_records_are_independent_metadata_copies_without_job_authority(self) -> None:
        """Original raw receipt SHA and declaration survive without exposing mutable originals."""
        prepared = self.run_preparation()[0]
        value = prepared.record()
        self.assertEqual(value["admissionExpectation"]["receiptSha256"], self.fixture.entries[1]["admissionReceiptSha256"])
        self.assertEqual(value["admissionExpectation"]["decoded"], self.fixture.receipts["raw-b"]["decoded"])
        self.assertNotIn("jobId", value)
        self.assertNotIn("ownerPid", value)
        value["declaration"]["historyState"] = "changed copy"
        self.assertEqual(prepared.record()["declaration"]["historyState"], "known")


if __name__ == "__main__":
    unittest.main()
