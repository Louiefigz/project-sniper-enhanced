"""Original batch lifetime faults; writes restricted to explicit TEST-owned files."""
from __future__ import annotations

import os
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from _source_color_batch_fixture import SourceColorBatchFixture, current_batch_test_pins
from color import grade_project
from guided_source_color_batch import PreparedSourceColorBatch
from guided_source_color_batch_files import BatchCodeInventory
from headless.grade_launch_files import HeldLaunchFile


class SourceColorBatchFaultTests(unittest.TestCase):
    """Callbacks and later files cannot replace the original all-source baseline."""

    @classmethod
    def setUpClass(cls) -> None:
        """Bind actual current implementation once for this metadata-only TEST cohort."""
        cls.pins = current_batch_test_pins()

    def setUp(self) -> None:
        """Keep every mutation and generated file inside one explicit canonical fixture."""
        self.fixture = SourceColorBatchFixture(self.pins)
        self.addCleanup(self.fixture.cleanup)
        self.fixture.guard.reset_mock()

    def test_first_persistent_callback_cannot_change_original_job_ref(self) -> None:
        """The batch captures original refs before preparation invokes its guard."""
        ref = self.fixture.refs[0]
        self.fixture.guard.side_effect = lambda: object.__setattr__(ref, "input_sha256", "a" * 64)
        with self.assertRaisesRegex(RuntimeError, "original arguments changed"):
            self.fixture.prepare()

    def test_first_callback_cannot_extend_original_launch_cutoff(self) -> None:
        """Launch fields remain independent of the persistent preparation's own checks."""
        launch = self.fixture.refs[0].launch
        self.fixture.guard.side_effect = lambda: object.__setattr__(launch, "deadline", 1301.0)
        with self.assertRaisesRegex(RuntimeError, "original arguments changed"):
            self.fixture.prepare()

    def test_later_job_reader_cannot_substitute_already_prepared_source_data(self) -> None:
        """An unchanged disk input cannot authorize a mutated returned parsed object."""
        from guided_source_color_batch import read_grade_project_input

        def altered(*args: object) -> dict:
            """Mutate only the TEST parsed result after the real shared raw-SHA read."""
            value = read_grade_project_input(*args)
            value["declaration"]["historyState"] = "unknown"
            return value

        with patch("guided_source_color_batch.read_grade_project_input", side_effect=altered):
            with self.assertRaisesRegex(RuntimeError, "actual job input projection changed"):
                self.fixture.prepare()

    def test_late_raw_input_and_preclaim_changes_fail_existing_batch(self) -> None:
        """Original file identities survive success without a new digest baseline."""
        result = self.fixture.prepare()
        ref = self.fixture.refs[1]
        self.fixture.change(ref.launch.claim_path, b"TEST changed preclaim")
        with self.assertRaisesRegex(RuntimeError, "held metadata identity changed"):
            result.assert_current()

    def test_implementation_callback_cannot_rebaseline_parsed_input(self) -> None:
        """Retain the real parsed return before any later verifier callback runs."""
        from guided_source_color_batch import verify_grade_project_implementation

        def changed(directory: Path, value: dict) -> None:
            """Change only the TEST parsed object after actual code verification."""
            verify_grade_project_implementation(directory, value)
            value["ownerPid"] = 0

        with patch("guided_source_color_batch.verify_grade_project_implementation", side_effect=changed):
            with self.assertRaisesRegex(RuntimeError, "original held record changed"):
                self.fixture.prepare()

    def test_last_file_check_input_mutation_fails_pure_final_comparison(self) -> None:
        """No preparation callback after the filesystem sweep is needed to catch drift."""
        result = self.fixture.prepare()
        original, target = HeldLaunchFile.check, self.fixture.refs[-1].input_path
        changed = [False]

        def check(row: HeldLaunchFile) -> None:
            """Change only fixture input metadata after its actual final file check."""
            original(row)
            if row.path == target and not changed[0]:
                changed[0] = True
                self.fixture.inputs.documents["candidatePlan"]["TEST-late-input"] = True

        with patch.object(HeldLaunchFile, "check", new=check):
            with self.assertRaisesRegex(RuntimeError, "original arguments changed"):
                result.assert_current()

    def test_last_code_check_mutation_fails_pure_final_comparison(self) -> None:
        """The actual parsed job cannot change after its persistent caller guard."""
        result = self.fixture.prepare()
        original = BatchCodeInventory.assert_current

        def check(code: BatchCodeInventory, deadline: float) -> None:
            """Change only the retained TEST job after checking its actual code stats."""
            original(code, deadline)
            result.jobs[0].value["declaration"]["historyState"] = "unknown"

        with patch.object(BatchCodeInventory, "assert_current", new=check):
            with self.assertRaisesRegex(RuntimeError, "original held record changed"):
                result.assert_current()

    def test_final_preparation_callback_cannot_mutate_retained_job(self) -> None:
        """The persistent preparation guard cannot authorize a replacement job record."""
        result = self.fixture.prepare()
        self.fixture.guard.side_effect = lambda: result.jobs[0].value.update(ownerPid=0)
        with self.assertRaisesRegex(RuntimeError, "original held record changed"):
            result.assert_current()

    def test_changed_job_order_and_private_file_inventory_cannot_be_rebaselined(self) -> None:
        """Private list replacement cannot remove the original byte/stat obligations."""
        result = self.fixture.prepare()
        original = result.jobs
        object.__setattr__(result, "jobs", result.jobs[::-1])
        with self.assertRaisesRegex(RuntimeError, "original lifetime changed"):
            result.assert_current()
        object.__setattr__(result, "jobs", original)
        result._read.retained = []
        with self.assertRaisesRegex(RuntimeError, "original lifetime changed"):
            result.assert_current()

    def test_equal_source_clone_and_approval_flag_changes_are_rejected(self) -> None:
        """New objects or booleans cannot upgrade exact batch records into authority."""
        result = self.fixture.prepare()
        row = result.jobs[0]
        object.__setattr__(row, "source", replace(row.source))
        with self.assertRaisesRegex(RuntimeError, "original held record changed"):
            result.assert_current()
        object.__setattr__(result, "executable", True)
        with self.assertRaisesRegex(RuntimeError, "original lifetime changed"):
            result.assert_current()

    def test_original_deadline_after_last_argument_serialization_is_enforced(self) -> None:
        """Finite comparison work cannot consume the cutoff and still return success."""
        result = self.fixture.prepare()
        kind, original = type(result._read), type(result._read).unchanged
        calls = [0]

        def unchanged(read: object) -> None:
            """Advance only the original TEST clock after its final metadata comparison."""
            original(read)
            calls[0] += 1
            if calls[0] == 4:
                self.fixture.now = 1300.0

        with patch.object(kind, "unchanged", new=unchanged):
            with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
                result._read.check()

    def test_original_deadline_after_last_batch_binding_is_enforced(self) -> None:
        """The exposed batch's own final comparison also consumes the same clock."""
        result = self.fixture.prepare()
        original, calls = PreparedSourceColorBatch.binding, [0]

        def binding(batch: PreparedSourceColorBatch) -> tuple:
            """Advance only original TEST time after the second outer comparison."""
            value = original(batch)
            calls[0] += 1
            if calls[0] == 2:
                self.fixture.now = 1300.0
            return value

        with patch.object(PreparedSourceColorBatch, "binding", new=binding):
            with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
                result.assert_current()

    def test_fault_writer_rejects_external_dependencies_and_hardlinks(self) -> None:
        """No membership in a read inventory permits mutation of a production dependency."""
        with self.assertRaisesRegex(RuntimeError, "explicitly TEST-owned"):
            self.fixture.change(Path(grade_project.__file__).resolve(), b"NEVER WRITTEN")
        alias = self.fixture.root / "TEST-hardlink"
        os.link(self.fixture.extra_code, alias)
        with self.assertRaisesRegex(RuntimeError, "regular single-link TEST"):
            self.fixture.change(self.fixture.extra_code, b"NEVER WRITTEN")


if __name__ == "__main__":
    unittest.main()
