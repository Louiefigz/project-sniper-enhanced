"""Optional grade launch plumbing with TEST metadata, no daemon or admission claim.

The existing fixture owns every generated file and stubs decoder/admission
leaves. Faults below change only in-memory TEST objects, never dependencies.
"""
from __future__ import annotations

import json
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from _grade_project_owned_fixture import OwnedGradeFixture
from color import grade_project as project
from color.grade_observation_profile import V2
from color.grade_project_completion import seal_completed_project_observation
from color.grade_project_owned import GradeProjectOwnedContext, OwnedProjectObservationError
from headless.grade_launch_intent import OwnedGradeLaunch
from headless import grade_observation_policy as policy
from headless.grade_observation_phase import OwnedGradePhase
from headless.grade_observation_policy import GradeIsolationError


class OwnedGradeLaunchTests(unittest.TestCase):
    """Keep optional ownership separate from unchanged reader/publication authority."""

    def setUp(self) -> None:
        """Use one fixed original TEST clock and inert private fixture per case."""
        self.fixture = OwnedGradeFixture()
        self.addCleanup(self.fixture.cleanup)
        self.now = 1000.0
        self.time_patch = patch.object(time, "monotonic", side_effect=lambda: self.now)
        self.time_patch.start()
        self.addCleanup(self.time_patch.stop)
        self.fixture.context = GradeProjectOwnedContext(1300.0, self.fixture.guard, self.fixture.identity)
        self.launch_guard = Mock()
        self.launch = OwnedGradeLaunch(self.fixture.job / "TEST-unread-claim.json", "a" * 64,
                                       1100.0, self.launch_guard)
        self.owned_worker = self.fixture.stack.enter_context(
            patch.object(project, "run_owned_isolated_grade", side_effect=self.run_stub))

    def run_stub(self, source: str, request: dict, directory: Path, phase: OwnedGradePhase) -> dict:
        """Substitute only the lower native seam; its separate claim tests stay distinct."""
        self.assertIs(type(phase), OwnedGradePhase)
        self.assertIs(phase.owner, self.launch)
        return self.fixture.run_stub(source, request, directory, phase.deadline)

    def execute(self) -> object:
        """Invoke the actual optional route with the same original typed context."""
        return project.run_project_observation_owned(self.fixture.value, self.fixture.job,
                                                     self.fixture.context, self.launch)

    def test_explicit_none_keeps_legacy_routing(self) -> None:
        """The old signature remains usable without consulting launch ownership."""
        owned = project.run_project_observation_owned(self.fixture.value, self.fixture.job,
                                                      self.fixture.context, None)
        self.fixture.worker.assert_called_once()
        self.owned_worker.assert_not_called()
        self.assertIs(owned.context, self.fixture.context)
        self.assertEqual(owned.deadline, 1120.0)
        self.assertNotIn("launch", json.loads(owned.result_path.read_bytes()))

    def test_actual_launch_return_and_shorter_cutoff_survive_publication(self) -> None:
        """Hold real TEST bytes and the same reader object without replacing caller time."""
        owned = self.execute()
        self.fixture.worker.assert_not_called()
        self.owned_worker.assert_called_once()
        source, request, directory, phase = self.owned_worker.call_args.args
        self.assertEqual((source, directory), (self.fixture.identity.path, self.fixture.job / "execution"))
        self.assertIs(phase.owner, self.launch)
        self.assertEqual(phase.deadline, 1100.0)
        self.assertEqual(request, {"sourceSha256": self.fixture.identity.sha256,
                                  "frameCount": self.fixture.returned.records.decoded_record_count,
                                  "timeoutSeconds": 100})
        self.assertIs(owned.context, self.fixture.context)
        self.assertIs(owned.context.source, self.fixture.identity)
        self.assertIs(owned.observation, self.fixture.returned)
        self.assertEqual((owned.deadline, owned.context.deadline), (1100.0, 1300.0))
        self.assertEqual(owned.result_path.stat().st_mode & 0o777, 0o400)
        self.assertFalse(json.loads(owned.result_path.read_bytes())["gradeApplicable"])
        self.launch_guard.assert_not_called()

    def test_sealed_data_keeps_original_overall_lifetime_not_launch_lifetime(self) -> None:
        """Immediate sealing never renews the phase or borrows a retired resource guard."""
        owned = self.execute()
        completed = seal_completed_project_observation(owned)
        self.assertIs(completed.context, self.fixture.context)
        self.assertIs(completed.observation, owned.observation)
        self.assertIs(completed.files, owned.files)
        self.now = 1101.0
        with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
            owned.assert_current()
        completed.assert_current()
        self.now = 1301.0
        with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
            completed.assert_current()

    def test_original_profile_cap_is_not_widened_by_equal_overall_launch_cutoff(self) -> None:
        """V1's existing 120-second class remains stricter than a longer caller window."""
        self.launch = replace(self.launch, deadline=1300.0)
        owned = self.execute()
        self.assertEqual(owned.deadline, 1120.0)
        self.assertEqual(self.owned_worker.call_args.args[1]["timeoutSeconds"], 120)
        self.assertEqual(owned.context.deadline, 1300.0)

    def test_dispatch_delay_preserves_actual_parent_phase_in_real_policy_entry(self) -> None:
        """Scheduling cannot turn the existing phase end1120 into a new entry-based1130."""
        self.launch = replace(self.launch, deadline=1300.0)
        held_launch = object()

        def delayed(source: str, request: dict, directory: Path, phase: OwnedGradePhase) -> dict:
            """Advance the original TEST clock before the real low-level phase selector."""
            self.now += 10
            return policy.run_owned_isolated_grade(source, request, directory, phase)

        def isolated(source: str, request: dict, directory: Path, invocation: object) -> dict:
            """Stub only native execution after inspecting the actual selected cutoff."""
            self.assertEqual(invocation.deadline, 1120.0)
            self.assertIs(invocation.launch, held_launch)
            return self.fixture.run_stub(source, request, directory, invocation.deadline)

        self.owned_worker.side_effect = delayed
        with patch.object(policy, "hold_grade_launch", return_value=held_launch) as hold, \
                patch.object(policy, "_run_isolated_grade", side_effect=isolated):
            owned = self.execute()
        self.assertIs(hold.call_args.args[0], self.launch)
        self.assertEqual(hold.call_args.args[2]["timeoutSeconds"], 120)
        self.assertEqual((self.now, owned.deadline, owned.context.deadline), (1010.0, 1120.0, 1300.0))

    def test_invalid_launch_or_widened_cutoff_rejects_before_first_callback(self) -> None:
        """No guard, reader or native seam may run for an invalid optional context."""
        for invalid in ({}, True, replace(self.launch, deadline=1301.0)):
            with self.subTest(launch=invalid), self.assertRaises(ValueError):
                project.run_project_observation_owned(self.fixture.value, self.fixture.job,
                                                     self.fixture.context, invalid)
        self.fixture.guard.assert_not_called()
        self.fixture.reader.assert_not_called()
        self.owned_worker.assert_not_called()

    def assert_entry_mutation_rejects(self, target: object, name: str, value: object) -> None:
        """Restore only the explicitly supplied in-memory TEST field after rejection."""
        original = getattr(target, name)
        object.__setattr__(target, name, value)
        try:
            with self.assertRaisesRegex(RuntimeError, "changed before invocation"):
                self.execute()
        finally:
            object.__setattr__(target, name, original)

    def test_preentry_launch_and_context_mutations_cannot_be_rebaselined(self) -> None:
        """Existing construction bindings precede the new private options capture."""
        self.assert_entry_mutation_rejects(self.launch, "deadline", 1099.0)
        self.assert_entry_mutation_rejects(self.launch, "deadline", 1100)
        self.assert_entry_mutation_rejects(self.launch, "guard", Mock())
        self.assert_entry_mutation_rejects(self.launch, "claim_sha256", "b" * 64)
        self.assert_entry_mutation_rejects(self.fixture.context, "deadline", 1400.0)
        self.assert_entry_mutation_rejects(self.fixture.context, "guard", Mock())
        self.fixture.guard.assert_not_called()
        self.owned_worker.assert_not_called()

    def test_expired_original_launch_rejects_before_first_callback(self) -> None:
        """A positive overall budget cannot revive an exhausted supplied launch cutoff."""
        self.launch = replace(self.launch, deadline=999.0)
        with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
            self.execute()
        self.fixture.guard.assert_not_called()
        self.owned_worker.assert_not_called()

    def test_first_context_callback_cannot_swap_launch(self) -> None:
        """Capture launch fields before the existing bounded input-hash guard."""
        self.fixture.guard.side_effect = lambda: object.__setattr__(self.launch, "deadline", 1200.0)
        with self.assertRaisesRegex(OwnedProjectObservationError, "launch or context changed"):
            self.execute()
        self.owned_worker.assert_not_called()
        self.fixture.reader.assert_not_called()

    def test_first_callback_cannot_replace_equal_valued_original_source(self) -> None:
        """The opt-in request retains the actual same-pass source object, not only its fields."""
        self.fixture.guard.side_effect = lambda: object.__setattr__(
            self.fixture.context, "source", replace(self.fixture.identity))
        with self.assertRaisesRegex(OwnedProjectObservationError, "launch or context changed"):
            self.execute()
        self.owned_worker.assert_not_called()

    def test_postworker_mutation_keeps_cleanup_but_never_reaches_reader(self) -> None:
        """A returned clean worker cannot authorize changed optional launch metadata."""
        def worker(*args: object) -> dict:
            """Change only an in-memory TEST launch after writing original stub receipts."""
            result = self.run_stub(*args)
            object.__setattr__(self.launch, "guard", Mock())
            return result

        self.owned_worker.side_effect = worker
        with self.assertRaisesRegex(OwnedProjectObservationError, "launch or context changed") as error:
            self.execute()
        self.assertTrue(error.exception.result["cleanupVerified"])
        self.assertEqual(error.exception.result["cleanupMs"], 7)
        self.fixture.reader.assert_not_called()

    def test_cleanup_error_evidence_is_not_replaced_by_optional_plumbing(self) -> None:
        """Unknown actual cleanup remains fenced with its original diagnostic duration."""
        self.owned_worker.side_effect = GradeIsolationError("TEST cleanup unproved", {
            "cleanupVerified": False, "cleanupMs": 90000})
        with self.assertRaises(OwnedProjectObservationError) as error:
            self.execute()
        self.assertFalse(error.exception.result["cleanupVerified"])
        self.assertEqual(error.exception.result["cleanupMs"], 90000)
        self.fixture.reader.assert_not_called()

    def test_postreader_launch_mutation_never_becomes_typed_completion(self) -> None:
        """The actual reader return cannot rebaseline launch arguments before publication."""
        original = self.fixture.read_stub

        def read(*args: object) -> object:
            """Change only a TEST launch field after producing the actual typed reader value."""
            value = original(*args)
            object.__setattr__(self.launch, "claim_sha256", "d" * 64)
            return value

        self.fixture.reader.side_effect = read
        with self.assertRaisesRegex(OwnedProjectObservationError, "launch or context changed") as error:
            self.execute()
        self.assertIsNotNone(self.fixture.returned)
        self.assertNotIn("observation", error.exception.result)
        self.assertTrue(error.exception.result["cleanupVerified"])

    def test_final_publication_callback_mutation_never_returns_owned_value(self) -> None:
        """Recheck optional originals after finish_owned's last source/owner callback."""
        published = [False]
        original = project.write_new

        def write(path: Path, value: dict) -> None:
            """Arm only after the real immutable-result bytes have been written."""
            original(path, value)
            published[0] = path == self.fixture.job / "observation.json"

        def guard() -> None:
            """Mutate only the TEST launch after the publication boundary."""
            if published[0]:
                object.__setattr__(self.launch, "claim_sha256", "c" * 64)

        self.fixture.guard.side_effect = guard
        with patch.object(project, "write_new", side_effect=write):
            with self.assertRaisesRegex(RuntimeError, "launch or context changed"):
                self.execute()
        self.assertEqual((self.fixture.job / "observation.json").stat().st_mode & 0o777, 0o400)

    def test_last_callback_original_cutoff_expiry_never_returns_owned_value(self) -> None:
        """A later overall deadline cannot hide expiry of the actual observation cutoff."""
        original = project.finish_owned

        def finish(*args: object) -> object:
            """Advance only the original TEST clock after the actual publication checks."""
            owned = original(*args)
            self.now = 1100.0
            return owned

        with patch.object(project, "finish_owned", side_effect=finish):
            with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
                self.execute()

    def test_v2_stays_explicit_observation_only_on_the_new_launch_route(self) -> None:
        """Unknown history and xvYCC observations never become grade or delivery approval."""
        self.fixture.enable_v2()
        owned = self.execute()
        request = self.owned_worker.call_args.args[1]
        self.assertEqual((request["schemaVersion"], request["profile"]), (2, V2.token))
        self.assertEqual(owned.observation.records.stream.source_metadata.record()["transfer"], V2.transfer)
        self.assertFalse(owned.observation.grade_applicable)
        self.assertEqual(self.fixture.value["declaration"]["historyState"], "unknown")


if __name__ == "__main__":
    unittest.main()
