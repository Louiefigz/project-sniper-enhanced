"""Private project observation faults, with no mocked media called qualification."""
from __future__ import annotations

import json
import time
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from _grade_project_fixture import GradeProjectFixture
from color import grade_project as project
from color import grade_project_authority as authority
from headless.grade_observation_policy import GradeIsolationError


class GradeProjectAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = GradeProjectFixture()
        self.addCleanup(self.fixture.cleanup)

    def observe(self):
        with patch.object(authority, "execution_media_authority_entries", return_value=[self.fixture.entry]):
            return authority.observe_project(self.fixture.value)

    def test_original_snapshot_and_full_frame_groups_not_retained_cut_only(self) -> None:
        observed = self.observe()
        self.assertEqual(observed["sourcePath"], self.fixture.entry["snapshotPath"])
        self.assertEqual(observed["binding"]["fps"], "2")
        self.assertEqual(observed["binding"]["frameCount"], 180)
        self.assertEqual(observed["declaration"]["lightingGroups"][0]["endFrame"], 180)
        self.assertIn("candidates", observed["clockCaveat"])

    def test_rounded_fps_duration_and_unknown_history_cannot_supply_exact_clock(self) -> None:
        self.fixture.manifest({"frameRate": None, "fps": 2, "duration": 90})
        with self.assertRaisesRegex(RuntimeError, "exact-rate"):
            self.observe()
        self.fixture.manifest({"frameRate": "2/1", "vfr": True})
        with self.assertRaisesRegex(RuntimeError, "non-VFR"):
            self.observe()
        self.fixture.manifest({"vfr": False})
        self.fixture.value["declaration"]["historyState"] = "unknown"
        with self.assertRaisesRegex(ValueError, "known operator"):
            self.observe()

    def test_source_bytes_source_id_and_project_parent_changes_reject(self) -> None:
        self.fixture.value["sourceId"] = "other"
        with self.assertRaisesRegex(RuntimeError, "saved cut"):
            self.observe()
        self.fixture.value["sourceId"] = "raw-1"
        with open(self.fixture.entry["snapshotPath"], "ab") as handle:
            handle.write(b"changed")
        with self.assertRaisesRegex(RuntimeError, "bytes differ"):
            self.observe()


class GradeProjectRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = GradeProjectFixture()
        self.addCleanup(self.fixture.cleanup)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(authority, "execution_media_authority_entries", return_value=[self.fixture.entry]))
        self.stack.enter_context(patch.object(project, "implementation", return_value=[]))
        self.run = self.stack.enter_context(patch.object(project, "run_isolated_grade", return_value={"cleanupVerified": True, "cleanupMs": 7}))
        self.read = self.stack.enter_context(patch.object(project, "read_observation", return_value=self.fixture.observation()))

    def execute(self, deadline=None):
        return project.run_project_observation(self.fixture.value, self.fixture.job, deadline or time.monotonic() + 120)

    def test_same_deadline_and_live_execution_reach_replay_with_no_canonical_writes(self) -> None:
        files = [self.fixture.root / "project.json", self.fixture.producer / "edit_plan.json", self.fixture.producer / "asset_manifest.json"]
        before = [file.read_bytes() for file in files]
        deadline = time.monotonic() + 120
        result = self.execute(deadline)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(self.run.call_args.args[3], deadline)
        self.assertIs(self.read.call_args.args[2], self.run.return_value)
        self.assertEqual([file.read_bytes() for file in files], before)
        self.assertFalse(result["gradeApplicable"])
        self.assertFalse(result["deliveryApproved"])

    def test_unknown_history_blocks_before_decoder_and_preserves_failure(self) -> None:
        self.fixture.value["declaration"]["historyState"] = "unknown"
        result = self.execute()
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["cleanupVerified"])
        self.run.assert_not_called()
        self.assertTrue((self.fixture.job / "observation.json").exists())

    def test_last_parent_observation_exhausts_original_clock_and_cannot_complete(self) -> None:
        clock = [1000.0]
        original = project.observe_project
        calls = [0]
        def observe(value):
            result = original(value)
            calls[0] += 1
            if calls[0] == 2:
                clock[0] += 121
            return result
        self.stack.enter_context(patch.object(project.time, "monotonic", side_effect=lambda: clock[0]))
        self.stack.enter_context(patch.object(project, "observe_project", side_effect=observe))
        result = self.execute(1120.0)
        self.assertEqual(result["status"], "failed")
        self.assertNotIn("observation", result)
        self.assertEqual(result["elapsedMs"], 121000)

    def test_uncertain_cleanup_and_primary_failure_remain_failed(self) -> None:
        evidence = {"cleanupVerified": False, "cleanupMs": 90000}
        self.run.side_effect = GradeIsolationError("exact removal unproved", evidence)
        result = self.execute()
        self.assertFalse(result["cleanupVerified"])
        self.assertEqual(result["cleanupMs"], 90000)
        self.assertEqual(result["status"], "failed")
        self.read.assert_not_called()

    def test_mutated_immutable_declaration_blocks_after_clean_worker(self) -> None:
        def read(*_args):
            path = self.fixture.job / "input.json"
            value = json.loads(path.read_text())
            value["declaration"]["lightingGroups"][0]["intent"] = "neutral"
            path.write_text(json.dumps(value))
            return self.fixture.observation()
        self.read.side_effect = read
        result = self.execute()
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["cleanupVerified"])
        self.assertNotIn("observation", result)


if __name__ == "__main__":
    unittest.main()
