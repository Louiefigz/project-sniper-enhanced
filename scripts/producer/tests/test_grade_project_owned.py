"""Typed handoff fault tests; stubbed decoder output is NOT source qualification."""
from __future__ import annotations

import json
import signal
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from _grade_project_owned_fixture import OwnedGradeFixture
from color import grade_project as project
from color.grade_observation_profile import V2
from color.grade_project_owned import GradeProjectOwnedContext, OwnedProjectObservationError
from cut_preview_io import digest, file_hash
from headless.grade_observation_policy import GradeIsolationError


class OwnedGradeTests(unittest.TestCase):
    """Only clean publication returns the same actual typed reader object."""

    def setUp(self) -> None:
        """Keep every test on a fresh tiny private metadata tree."""
        self.fixture = OwnedGradeFixture()
        self.addCleanup(self.fixture.cleanup)

    def test_return_is_actual_reader_value_after_immutable_historical_json(self) -> None:
        """No JSON reconstruction, new approval flag, or clock renewal is allowed."""
        owned = self.fixture.execute()
        self.assertIs(owned.observation, self.fixture.returned)
        self.assertIs(owned.context, self.fixture.context)
        self.assertEqual(owned.deadline, self.fixture.context.deadline)
        self.assertEqual(self.fixture.worker.call_args.args[3], owned.deadline)
        self.assertIs(self.fixture.reader.call_args.args[2], self.fixture.execution)
        result = json.loads(owned.result_path.read_bytes())
        self.assertEqual(result["artifactHash"], digest({k: v for k, v in result.items() if k != "artifactHash"}))
        self.assertEqual(owned.result_sha256, file_hash(owned.result_path))
        self.assertEqual(owned.result_path.stat().st_mode & 0o777, 0o400)
        self.assertEqual(result["schemaVersion"], 1)
        self.assertNotIn("profile", result)
        self.assertNotIn("owned", result)
        self.assertFalse(result["gradeApplicable"])
        self.assertFalse(result["deliveryApproved"])
        owned.assert_current()

    def test_invalid_context_shape_never_calls_guard_or_worker(self) -> None:
        """Reject coercions and fake identities before starting observation work."""
        for invalid in (True, float("inf"), float("nan"), "120"):
            with self.subTest(deadline=invalid), self.assertRaises(ValueError):
                GradeProjectOwnedContext(invalid, self.fixture.guard, self.fixture.identity)
        for source in (None, {}, replace(self.fixture.identity, size_bytes=True),
                       replace(self.fixture.identity, stat_identity=(1,)), replace(self.fixture.identity, sha256="x")):
            with self.subTest(source=source), self.assertRaises(ValueError):
                GradeProjectOwnedContext(time.monotonic() + 120, self.fixture.guard, source)
        self.fixture.guard.assert_not_called()
        self.fixture.worker.assert_not_called()

    def test_expired_entry_and_active_parent_timer_never_start_worker(self) -> None:
        """The original timer refusal remains, without touching another timer."""
        self.fixture.context = replace(self.fixture.context, deadline=time.monotonic() - 1)
        with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
            self.fixture.execute()
        self.fixture.context = replace(self.fixture.context, deadline=time.monotonic() + 120)
        signal.setitimer(signal.ITIMER_REAL, 10)
        try:
            with self.assertRaisesRegex(RuntimeError, "another active wall timer"):
                self.fixture.execute()
            self.assertGreater(signal.getitimer(signal.ITIMER_REAL)[0], 0)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
        self.fixture.worker.assert_not_called()

    def test_original_source_drift_rejects_before_decoder(self) -> None:
        """Do not attach fresh stat identity to changed original source bytes."""
        Path(self.fixture.identity.path).write_bytes(b"changed source")
        with self.assertRaisesRegex(RuntimeError, "source identity changed"):
            self.fixture.execute()
        self.fixture.worker.assert_not_called()

    def test_wrong_original_hash_rejects_before_decoder(self) -> None:
        """The initially held source and current admitted binding must join."""
        self.fixture.context = replace(self.fixture.context, source=replace(self.fixture.identity, sha256="0" * 64))
        with self.assertRaisesRegex(OwnedProjectObservationError, "initial verified identity"):
            self.fixture.execute()
        self.fixture.worker.assert_not_called()

    def test_fake_reader_shape_never_becomes_owned_completion(self) -> None:
        """Historical test namespaces are not accepted by the new typed seam."""
        self.fixture.reader.side_effect = None
        self.fixture.reader.return_value = self.fixture.observation()
        with self.assertRaisesRegex(OwnedProjectObservationError, "actual returned BoundGradeObservation") as error:
            self.fixture.execute()
        self.assertNotIn("observation", error.exception.result)
        self.assertTrue(error.exception.result["cleanupVerified"])

    def test_invalid_nested_record_type_is_not_accepted_as_typed_evidence(self) -> None:
        """An outer dataclass cannot launder unvalidated record-shaped objects."""
        original = self.fixture.read_stub

        def read(*args: object) -> object:
            """Inject a malformed inner record while retaining the real outer type."""
            actual = original(*args)
            return replace(actual, records=self.fixture.observation().records)

        self.fixture.reader.side_effect = read
        with self.assertRaisesRegex(OwnedProjectObservationError, "actual returned BoundGradeObservation"):
            self.fixture.execute()

    def test_unknown_history_and_uncertain_cleanup_never_return_typed_result(self) -> None:
        """Missing declarations do not receive fabricated known history."""
        self.fixture.value["declaration"]["historyState"] = "unknown"
        with self.assertRaisesRegex(OwnedProjectObservationError, "known operator"):
            self.fixture.execute()
        self.fixture.worker.assert_not_called()

    def test_worker_cleanup_failure_preserves_actual_cleanup_evidence(self) -> None:
        """A failed worker never grants the pending reader value to a consumer."""
        self.fixture.worker.side_effect = GradeIsolationError("cleanup unproved", {"cleanupVerified": False, "cleanupMs": 90000})
        with self.assertRaises(OwnedProjectObservationError) as error:
            self.fixture.execute()
        self.assertFalse(error.exception.result["cleanupVerified"])
        self.assertEqual(error.exception.result["cleanupMs"], 90000)
        self.fixture.reader.assert_not_called()

    def test_returned_worker_without_affirmative_cleanup_cannot_handoff(self) -> None:
        """Even a stub reader success cannot override an unproved cleanup flag."""
        original = self.fixture.run_stub

        def run(*args: object) -> dict:
            """Return failed cleanup through the normal runner return seam."""
            result = original(*args)
            result["cleanupVerified"] = False
            return result

        self.fixture.worker.side_effect = run
        with self.assertRaisesRegex(OwnedProjectObservationError, "clean non-approval completion") as error:
            self.fixture.execute()
        self.assertFalse(error.exception.result["cleanupVerified"])

    def test_returned_value_retains_original_lifetime_and_byte_identity(self) -> None:
        """A completed handoff does not remain current after source/evidence drift."""
        owned = self.fixture.execute()
        (self.fixture.job / "execution/result/probe.json").write_bytes(b"changed")
        with self.assertRaisesRegex(RuntimeError, "held publication or evidence changed"):
            owned.assert_current()

    def test_context_construction_does_not_invoke_guard(self) -> None:
        """Only the bounded running phase calls the borrowed guard, never a consumer callback."""
        guard = Mock()
        context = GradeProjectOwnedContext(time.monotonic() + 120, guard, self.fixture.identity)
        guard.assert_not_called()
        context.check()
        guard.assert_called_once_with()

    def test_v2_retains_explicit_xvycc_and_unknown_history_without_upgrade(self) -> None:
        """Typed V2 output never becomes a BT709 observation or grade approval."""
        self.fixture.enable_v2()
        before = json.loads((self.fixture.job / "input.json").read_bytes())
        owned = self.fixture.execute()
        result = json.loads(owned.result_path.read_bytes())
        self.assertEqual(result["schemaVersion"], 2)
        self.assertEqual(result["limits"], V2.evidence()["limits"])
        self.assertEqual(result["profile"], V2.token)
        self.assertEqual(owned.observation.records.stream.source_metadata.record()["transfer"], "iec61966-2-4")
        self.assertIs(owned.observation, self.fixture.returned)
        self.assertEqual(before, json.loads((self.fixture.job / "input.json").read_bytes()))
        self.assertEqual(before["declaration"]["historyState"], "unknown")
        self.assertFalse(owned.observation.grade_applicable)
        self.assertEqual(self.fixture.worker.call_args.args[3], self.fixture.context.deadline)

    def test_original_v1_profile_cap_also_limits_returned_context(self) -> None:
        """A long caller lifetime cannot widen the fixed V1 engineering bound."""
        clock = [1000.0]
        self.fixture.context = replace(self.fixture.context, deadline=2000.0)
        with patch.object(time, "monotonic", side_effect=lambda: clock[0]):
            owned = self.fixture.execute()
            self.assertEqual(owned.deadline, 1120.0)
            self.assertEqual(self.fixture.worker.call_args.args[3], 1120.0)
            clock[0] = 1121.0
            with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
                owned.assert_current()

    def test_bounded_input_and_wrong_context_type_never_start_worker(self) -> None:
        """The new typed entry cannot perform unbounded input hashing before its timer."""
        with self.assertRaisesRegex(ValueError, "actual original context"):
            project.run_project_observation_owned(self.fixture.value, self.fixture.job, {})
        (self.fixture.job / "input.json").write_bytes(b" " * (128 * 1024 + 1))
        with self.assertRaisesRegex(RuntimeError, "over budget"):
            self.fixture.execute()
        self.fixture.worker.assert_not_called()


if __name__ == "__main__":
    unittest.main()
