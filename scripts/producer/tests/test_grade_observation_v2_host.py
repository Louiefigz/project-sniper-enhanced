"""Host early-class/parent-deadline tests; no source decoder or container runs."""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from _grade_observation_v2_fixture import v2_project, v2_request
from _grade_project_fixture import GradeProjectFixture
from color import grade_project as project
from color import grade_project_authority as authority
from color import grade_project_worker as worker
from color.grade_observation_profile import V1, V2, V2_PROFILE
from cut_preview_io import file_hash
from headless import grade_observation_policy as policy


class GradeObservationV2HostTests(unittest.TestCase):
    """Metadata refusal is cheap, but passing metadata is never source authority."""

    def setUp(self) -> None:
        self.fixture = GradeProjectFixture()
        self.addCleanup(self.fixture.cleanup)
        v2_project(self.fixture)

    def test_cheap_frame_or_byte_refusal_precedes_source_set_hash_and_worker(self) -> None:
        self.fixture.manifest({"sourceSizeBytes": 16 * 1024 ** 3 + 1})
        with patch.object(authority, "execution_media_authority_entries") as verify, \
                self.assertRaisesRegex(ValueError, "byte class"):
            authority.observe_project(self.fixture.value)
        verify.assert_not_called()
        self.fixture.manifest({"sourceSizeBytes": 10_280_473_262})
        receipt = self.fixture.producer / self.fixture.entry["admissionReceiptPath"]
        value = json.loads(receipt.read_text())
        value["decoded"]["facts"]["declaredFrames"] = 24_001
        receipt.write_text(json.dumps(value))
        self.fixture.manifest({"admissionReceiptSha256": file_hash(receipt)})
        with patch.object(authority, "execution_media_authority_entries") as verify, self.assertRaises(ValueError):
            authority.observe_project(self.fixture.value)
        verify.assert_not_called()

    def test_unknown_history_observation_retains_exact_original_declaration(self) -> None:
        with patch.object(authority, "execution_media_authority_entries", return_value=[self.fixture.entry]):
            result = authority.observe_project(self.fixture.value)
        self.assertEqual(result["declaration"], self.fixture.value["declaration"])
        self.assertEqual(result["declaration"]["historyState"], "unknown")
        self.assertEqual(result["binding"]["sourceSha256"], self.fixture.entry["sha256"])

    def test_input_version_cannot_enable_v2_without_explicit_owner_flag(self) -> None:
        path = self.fixture.job / "input.json"
        with self.assertRaises(RuntimeError):
            worker._input(path, file_hash(path))
        result = worker._input(path, file_hash(path), V2_PROFILE)
        self.assertEqual(result, self.fixture.value)
        for key, value in (("profile", None), ("schemaVersion", 1), ("policy", V1.project_policy)):
            bad = {**self.fixture.value, key: value}
            path.write_text(json.dumps(bad))
            with self.subTest(key=key), self.assertRaises((RuntimeError, ValueError)):
                worker._input(path, file_hash(path), V2_PROFILE)

    def test_project_passes_only_original_remaining_credit_to_v2_worker(self) -> None:
        original = time.monotonic() + 75
        with ExitStack() as stack:
            stack.enter_context(patch.object(authority, "execution_media_authority_entries", return_value=[self.fixture.entry]))
            stack.enter_context(patch.object(project, "implementation", return_value=[]))
            run = stack.enter_context(patch.object(project, "run_isolated_grade", return_value={"cleanupVerified": True}))
            stack.enter_context(patch.object(project, "read_observation", return_value=self.fixture.observation()))
            result = project.run_project_observation(self.fixture.value, self.fixture.job, original)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["limits"], V2.evidence()["limits"])
        self.assertEqual(run.call_args.args[3], original)
        self.assertLessEqual(run.call_args.args[1]["timeoutSeconds"], 75)
        self.assertGreaterEqual(run.call_args.args[1]["timeoutSeconds"], 73)
        self.assertEqual(run.call_args.args[1]["profile"], V2_PROFILE)
        self.assertFalse(result["gradeApplicable"])

    def test_isolated_cap_is_minimum_of_parent_and_explicit_v2_ceiling(self) -> None:
        for allowance in (45, 2000):
            with tempfile.TemporaryDirectory() as raw:
                root = Path(raw).resolve()
                source, attempt = root / "source", root / "attempt"
                source.write_bytes(b"TEST-only-not-media")
                attempt.mkdir(mode=0o700)
                before = time.monotonic()
                with patch.object(policy, "_execute") as execute:
                    result = policy.run_isolated_grade(str(source), v2_request(), attempt, before + allowance)
                deadline = int(execute.call_args.args[3]["workDeadlineMonotonicNs"]) / 10 ** 9
                self.assertLessEqual(deadline, before + min(allowance, 1200) + .01)
                self.assertEqual(result["limits"], V2.evidence()["limits"])

    def test_launch_embeds_exact_held_worker_bytes_and_keeps_attested_resources(self) -> None:
        prefix = ["docker", "node", "-e", policy.NODE_PROBE, "old-arguments"]
        with patch.object(policy, "container_command", return_value=prefix):
            command, source_sha = policy._launch_command(object(), (Path("/private/tmp/fixed"), "exact-name", "/source"), v2_request())
        self.assertEqual(command[:-2], prefix[:3])
        self.assertEqual(command[-2], policy.WORKER.read_text())
        self.assertEqual(json.loads(command[-1]), v2_request())
        self.assertEqual(source_sha, file_hash(policy.WORKER))
        self.assertNotIn("require('./", command[-2])
        with patch.object(policy, "PROBE_CPUS", 1), self.assertRaisesRegex(RuntimeError, "resource"):
            policy._launch_command(object(), (Path("/unused"), "name", "/source"), v2_request())


if __name__ == "__main__":
    unittest.main()
