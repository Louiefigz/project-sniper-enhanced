"""All-used-source preflight with real metadata helpers, never runnable admission."""
from __future__ import annotations

import copy
import json
import os
import signal
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

from _source_color_batch_fixture import SourceColorBatchFixture, current_batch_test_pins
from color import grade_project
from color.grade_observation_profile import V2_PROFILE
from cut_preview_io import digest, file_hash, write_new
from guided_source_color_batch import PreparedSourceColorBatch, prepare_source_color_batch


class SourceColorBatchTests(unittest.TestCase):
    """Every source must match before exposing a complete data-only batch."""

    @classmethod
    def setUpClass(cls) -> None:
        """Retain one actual current code inventory for this metadata-only cohort."""
        cls.pins = current_batch_test_pins()

    def setUp(self) -> None:
        """Use one canonical fresh TEST tree and genuine initial tiny hash-pass identities."""
        self.fixture = SourceColorBatchFixture(self.pins)
        self.addCleanup(self.fixture.cleanup)
        self.fixture.guard.reset_mock()

    def test_exact_order_original_identities_and_false_flags(self) -> None:
        """Preserve first used-source order, original context, source and launch objects."""
        fixture = self.fixture
        result = fixture.prepare()
        self.assertIs(result.preparation, fixture.held)
        self.assertEqual(tuple(row.source_id for row in result.jobs), ("raw-b", "raw-a"))
        for row, ref, prepared in zip(result.jobs, fixture.refs, fixture.held.jobs):
            self.assertIs(row.source, prepared.source)
            self.assertIs(row.launch, ref.launch)
            self.assertEqual(row.directory, ref.input_path.parent)
            self.assertEqual(row.value, fixture.input_values[row.source_id])
            self.assertFalse((row.directory / "execution").exists())
        self.assertEqual((result.executable, result.grade_applicable, result.delivery_approved), (False, False, False))
        result.assert_current()

    def test_no_native_timers_directories_transient_guard_or_second_source_read(self) -> None:
        """Only original metadata is read; the batch does not own a lease or decoder."""
        sources = {row.source.path for row in self.fixture.held.jobs}
        original_open = os.open

        def open_checked(path: object, *args: object, **kwargs: object) -> int:
            """Fail if production preflight attempts any original source-byte read."""
            if str(path) in sources:
                raise AssertionError("TEST original source was read twice")
            return original_open(path, *args, **kwargs)

        for ref in self.fixture.refs:
            ref.launch.guard.side_effect = AssertionError("TEST transient launch guard was invoked")
        with patch.object(os, "open", side_effect=open_checked), patch.object(signal, "setitimer") as timer, \
                patch.object(Path, "mkdir") as mkdir, patch.object(grade_project, "run_project_observation_owned") as runner:
            result = self.fixture.prepare()
            result.assert_current()
        for mock in (timer, mkdir, runner):
            mock.assert_not_called()

    def test_explicit_mixed_profiles_remain_exact_without_legacy_upgrade(self) -> None:
        """Use actual shared V2 input/preclaim parsing beside unchanged V1 metadata."""
        original = SourceColorBatchFixture.declaration

        def declaration(source_id: str) -> dict:
            """Author explicit TEST V2 intent before its original preparation hold."""
            value = original(source_id)
            if source_id == "raw-b":
                value["profile"] = V2_PROFILE
                value["declaration"].update(schemaVersion=2, sourceProfile="unknown", historyState="unknown")
            return value

        with patch.object(SourceColorBatchFixture, "declaration", new=staticmethod(declaration)):
            fixture = SourceColorBatchFixture(self.pins)
        self.addCleanup(fixture.cleanup)
        result = fixture.prepare()
        self.assertEqual(result.jobs[0].value["profile"], V2_PROFILE)
        self.assertEqual(result.jobs[0].value["declaration"]["historyState"], "unknown")
        self.assertNotIn("profile", result.jobs[1].value)
        self.assertEqual([row.value["schemaVersion"] for row in result.jobs], [2, 1])
        self.assertEqual([row.launch.deadline for row in result.jobs], [1300.0, 1300.0])

    def test_job_profile_cannot_override_original_prepared_class(self) -> None:
        """A fresh raw SHA does not silently upgrade the original V1 source class."""
        self.fixture.rewrite_job(0, {"profile": V2_PROFILE})
        with self.assertRaises((RuntimeError, ValueError)):
            self.fixture.prepare()

    def test_missing_reordered_extra_or_duplicate_refs_reject_before_callbacks(self) -> None:
        """No prefix-only preparation can silently omit a later used source."""
        refs = self.fixture.refs
        invalid = ((), refs[:1], refs[::-1], (*refs, refs[0]), (refs[0], refs[0]), list(refs))
        for rows in invalid:
            with self.subTest(rows=type(rows).__name__), self.assertRaises(RuntimeError):
                prepare_source_color_batch(self.fixture.held, rows)
        self.fixture.guard.assert_not_called()

    def test_ref_paths_and_raw_hashes_are_not_coerced(self) -> None:
        """Reject malformed held references before opening any prospective input."""
        row = self.fixture.refs[0]
        invalid = (replace(row, source_id=True), replace(row, input_sha256=None),
                   replace(row, input_path=str(row.input_path)), replace(row, input_path=Path("input.json")))
        for changed in invalid:
            with self.subTest(row=changed), self.assertRaises((RuntimeError, ValueError)):
                prepare_source_color_batch(self.fixture.held, (changed, self.fixture.refs[1]))
        self.fixture.guard.assert_not_called()

    def test_launches_require_same_typed_original_overall_cutoff(self) -> None:
        """A shorter phase belongs in the runner, never in persistent batch lifetime."""
        row = self.fixture.refs[0]
        for deadline in (1299.0, 1301.0, 1300):
            launch = replace(row.launch, deadline=deadline)
            with self.subTest(deadline=deadline), self.assertRaisesRegex(RuntimeError, "overall cutoff"):
                prepare_source_color_batch(self.fixture.held, (replace(row, launch=launch), self.fixture.refs[1]))
        self.fixture.guard.assert_not_called()

    def test_wrong_source_declaration_and_parent_hash_reject(self) -> None:
        """Even newly hashed input bytes must match the exact original preparation."""
        original = self.fixture.input_values["raw-a"]
        declaration = {**original["declaration"], "historyState": "unknown"}
        for changes in ({"sourceId": "raw-b"}, {"declaration": declaration},
                        {"expected": {**original["expected"], "planSha256": "a" * 64}}):
            self.fixture.rewrite_job(1, changes)
            with self.subTest(changes=changes), self.assertRaisesRegex(RuntimeError, "prepared source"):
                self.fixture.prepare()

    def test_source_field_numeric_spelling_drift_cannot_match_preparation(self) -> None:
        """Equal numeric values in nested declarations retain their original JSON types."""
        original = self.fixture.input_values["raw-a"]
        declaration = copy.deepcopy(original["declaration"])
        declaration["lightingGroups"][0]["startFrame"] = 0.0
        self.fixture.rewrite_job(1, {"declaration": declaration})
        with self.assertRaisesRegex(RuntimeError, "prepared source"):
            self.fixture.prepare()

    def test_actual_parent_pid_and_inventory_sha_remain_required(self) -> None:
        """Shared validation is not bypassed by earlier preparation or caller types."""
        for changes in ({"ownerPid": os.getpid()}, {"implementationSha256": None}):
            self.fixture.rewrite_job(0, changes)
            with self.subTest(changes=changes), self.assertRaisesRegex(RuntimeError, "held owner|implementation hash"):
                self.fixture.prepare()

    def test_wrong_preclaim_source_or_container_identity_rejects(self) -> None:
        """All preclaim fields still pass the real closed metadata helper."""
        for changes in ({"sourceSha256": "a" * 64}, {"frameCount": 25}, {"containerName": "TEST-wrong-name"}):
            self.fixture.rewrite_claim(1, changes)
            with self.subTest(changes=changes), self.assertRaises((RuntimeError, ValueError)):
                self.fixture.prepare()

    def test_other_valid_opening_preclaim_cannot_borrow_prepared_sources(self) -> None:
        """Same project/source/job is insufficient without this exact opening input."""
        fixture = self.fixture
        directory = fixture.root / "TEST-other-opening"
        directory.mkdir(mode=0o700)
        value = {**fixture.inputs.value, "executionId": str(uuid4())}
        value["executionInputHash"] = digest({key: row for key, row in value.items() if key != "executionInputHash"})
        path = directory / "input.json"
        write_new(path, value)
        claim = json.loads(fixture.opening_claim.read_bytes())
        claim.update(inputPath=str(path), inputSha256=file_hash(path), executionId=value["executionId"],
                     executionInputHash=value["executionInputHash"], outputRoot=str(directory))
        claim_path = directory / "claim.json"
        write_new(claim_path, claim)
        fixture.rewrite_claim(1, {"openingClaimPath": str(claim_path), "openingClaimSha256": file_hash(claim_path)})
        with self.assertRaisesRegex(RuntimeError, "different original inputs"):
            fixture.prepare()

    def test_changed_raw_input_cannot_be_resealed_from_matching_json(self) -> None:
        """Original input SHA, not domain-equivalent JSON, is authoritative."""
        ref = self.fixture.refs[1]
        self.fixture.change(ref.input_path, self.fixture.input_values[ref.source_id])
        with self.assertRaisesRegex(RuntimeError, "raw metadata hash"):
            self.fixture.prepare()

    def test_assert_current_uses_code_stats_not_repeated_implementation_hashes(self) -> None:
        """The original implementation verification is not repeated by later data guards."""
        result = self.fixture.prepare()
        with patch.object(grade_project, "implementation", side_effect=AssertionError("TEST repeated code hash")):
            result.assert_current()
        self.fixture.change(self.fixture.extra_code, b"TEST changed declared code")
        with self.assertRaisesRegex(RuntimeError, "implementation file changed"):
            result.assert_current()

    def test_json_constructor_and_clone_cannot_create_batch_lifetime(self) -> None:
        """A dataclass-shaped value is not a prepared same-process batch."""
        with self.assertRaises(TypeError):
            PreparedSourceColorBatch()
        result = self.fixture.prepare()
        clone = object.__new__(PreparedSourceColorBatch)
        for name, value in result.__dict__.items():
            object.__setattr__(clone, name, value)
        with self.assertRaisesRegex(RuntimeError, "original lifetime"):
            clone.assert_current()


if __name__ == "__main__":
    unittest.main()
