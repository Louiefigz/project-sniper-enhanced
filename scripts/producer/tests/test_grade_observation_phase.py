"""Original phase handoff tests with private TEST files and no native launch.

PolicyFixture replaces the claim/native leaves; the two real-claim callback
cases retain the actual metadata reader. No fixture gains grade authority.
"""
from __future__ import annotations

import signal
import tempfile
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

from _grade_launch_fixture import GradeLaunchFixture
from color.deadline import wall_budget
from headless import grade_observation_phase as phases
from headless import grade_observation_policy as policy
from test_grade_owned_launch_policy import PolicyFixture, REQUEST


class GradeObservationPhaseTests(unittest.TestCase):
    """Keep exact owners and original clocks through scheduling and callbacks."""

    def setUp(self) -> None:
        """Create only inert source and empty attempt under one owned TEST root."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.fixture = PolicyFixture(Path(temporary.name).resolve())
        self.started = time.monotonic()

    def run_phase(self, phase: object) -> dict:
        """Run real policy flow while replacing only named fixture/native leaves."""
        with ExitStack() as stack:
            self.fixture.install(stack, REQUEST)
            return policy.run_owned_isolated_grade(
                str(self.fixture.source), REQUEST, self.fixture.attempt, phase)

    def test_owner_selection_retains_identity_and_entry_cap(self) -> None:
        """Historical owned calls derive one phase, never a new owner or guard."""
        phase, deadline = phases.select_grade_phase(self.fixture.owner, self.started, 120)
        self.assertIs(phase.owner, self.fixture.owner)
        self.assertEqual(deadline, self.started + 120)
        self.assertEqual(phase.deadline, deadline)

    def test_explicit_phase_survives_delayed_worker_scheduling(self) -> None:
        """Fifty seconds before policy entry remain charged to the original phase."""
        phase = phases.OwnedGradePhase(self.fixture.owner, self.started + 120)
        with patch.object(policy.time, "monotonic", return_value=self.started + 50):
            result = self.run_phase(phase)
        recorded = int(result["workDeadlineMonotonicNs"]) / 1e9
        self.assertAlmostEqual(recorded, self.started + 120, places=6)
        self.assertIs(phase.owner, self.fixture.owner)
        self.assertEqual(self.fixture.events.count("launch"), 1)

    def test_explicit_wider_phase_cannot_widen_request_maximum(self) -> None:
        """A longer original owner phase still honors the fixed V1 request cap."""
        phase = phases.OwnedGradePhase(self.fixture.owner, self.started + 200)
        selected, deadline = phases.select_grade_phase(phase, self.started, 120)
        self.assertIs(selected, phase)
        self.assertEqual(deadline, self.started + 120)
        self.assertEqual(phase.deadline, self.started + 200)

    def test_phase_cutoff_requires_exact_finite_numeric_type(self) -> None:
        """Boolean, string, null, nonfinite and widened cutoffs fail before IO."""
        invalid = [True, False, "120", None, float("nan"), float("inf"),
                   -float("inf"), self.fixture.owner.deadline + 1]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                phases.OwnedGradePhase(self.fixture.owner, value)

    def test_phase_owner_and_policy_context_require_actual_types(self) -> None:
        """Lookalike dictionaries cannot become an owned launch or phase."""
        for value in (None, {}, {"owner": self.fixture.owner}, object()):
            with self.subTest(value=type(value)), self.assertRaises(ValueError):
                phases.OwnedGradePhase(value, self.started + 10)
            with self.subTest(selection=type(value)), self.assertRaises(ValueError):
                phases.select_grade_phase(value, self.started, 120)

    def test_expired_phase_starts_no_claim_or_native_work(self) -> None:
        """The original cutoff is checked before invoking the metadata callback."""
        phase = phases.OwnedGradePhase(self.fixture.owner, self.started - 1)
        self.fixture.on_hold = Mock()
        with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
            self.run_phase(phase)
        self.fixture.on_hold.assert_not_called()
        self.assertEqual(self.fixture.events, [])
        self.assertEqual(list(self.fixture.attempt.iterdir()), [])

    def test_same_fields_replacement_owner_is_not_original_owner(self) -> None:
        """A fresh dataclass with equal fields does not replace original identity."""
        phase = phases.OwnedGradePhase(self.fixture.owner, self.started + 10)
        owner = self.fixture.owner
        replacement = policy.OwnedGradeLaunch(owner.claim_path, owner.claim_sha256, owner.deadline, owner.guard)
        object.__setattr__(phase, "owner", replacement)
        with self.assertRaisesRegex(RuntimeError, "original binding changed"):
            phase.check()

    def test_original_owner_guard_replacement_is_rejected(self) -> None:
        """Changing the callback cannot silently change the source/claim owner."""
        phase = phases.OwnedGradePhase(self.fixture.owner, self.started + 10)
        object.__setattr__(self.fixture.owner, "guard", lambda: None)
        with self.assertRaisesRegex(RuntimeError, "original binding changed"):
            phase.check()

    def test_numeric_equal_cutoff_type_change_is_rejected(self) -> None:
        """An int-to-float replacement is not the original exact scalar binding."""
        cutoff = int(self.started) + 10
        phase = phases.OwnedGradePhase(self.fixture.owner, cutoff)
        object.__setattr__(phase, "deadline", float(cutoff))
        with self.assertRaisesRegex(RuntimeError, "original binding changed"):
            phase.check()

    def test_phase_check_does_not_invoke_or_replace_owner_guard(self) -> None:
        """Phase metadata checks do not claim independent source verification."""
        guard = Mock()
        original = self.fixture.owner
        owner = policy.OwnedGradeLaunch(original.claim_path, original.claim_sha256, original.deadline, guard)
        phase = phases.OwnedGradePhase(owner, self.started + 10)
        phase.check()
        guard.assert_not_called()

    def test_post_clock_check_mutation_is_rejected(self) -> None:
        """Recheck phase metadata after the existing original-clock callback seam."""
        phase = phases.OwnedGradePhase(self.fixture.owner, self.started + 10)
        with patch.object(phases, "require_time", side_effect=lambda _: object.__setattr__(phase, "deadline", self.started + 20)):
            with self.assertRaisesRegex(RuntimeError, "original binding changed"):
                phase.check()

    def assert_real_claim_callback_mutation(self, field: str) -> None:
        """Use actual held metadata; mutate only the live TEST phase in memory."""
        fixture = GradeLaunchFixture()
        self.addCleanup(fixture.close)
        phase = phases.OwnedGradePhase(fixture.owner, fixture.owner.deadline - 1)
        replacement = phase.deadline - 1 if field == "deadline" else self.fixture.owner
        fixture.guard.side_effect = lambda: object.__setattr__(phase, field, replacement)
        with patch.object(policy, "_launch") as launch:
            with self.assertRaisesRegex(RuntimeError, "original binding changed"):
                policy.run_owned_isolated_grade(str(fixture.source), fixture.request, fixture.directory, phase)
        launch.assert_not_called()
        self.assertEqual(list(fixture.directory.iterdir()), [])

    def test_real_hold_callback_cannot_change_phase_cutoff(self) -> None:
        """Actual claim/source guard mutation is rejected before directory work."""
        self.assert_real_claim_callback_mutation("deadline")

    def test_real_hold_callback_cannot_replace_phase_owner(self) -> None:
        """Returning from a real claim hold cannot adopt another original owner."""
        self.assert_real_claim_callback_mutation("owner")

    def test_original_thirty_ms_cutoff_interrupts_eighty_ms_setup(self) -> None:
        """The retained no-PID reproduction must interrupt, not merely fail later."""
        phase = phases.OwnedGradePhase(self.fixture.owner, time.monotonic() + 0.03)
        timers, completed = [], []
        def delayed_directory(path: Path) -> None:
            """Block only the exact private fixture setup, never a dependency path."""
            self.assertEqual(path, self.fixture.attempt)
            timers.append(signal.getitimer(signal.ITIMER_REAL)[0])
            time.sleep(0.08)
            completed.append(True)
        with patch.object(policy, "_directory", side_effect=delayed_directory):
            with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
                self.run_phase(phase)
        self.assertEqual(len(timers), 1)
        self.assertGreater(timers[0], 0)
        self.assertEqual(completed, [])
        self.assertNotIn("launch", self.fixture.events)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0)

    def test_result_directory_creation_uses_the_same_active_phase(self) -> None:
        """Creating the result directory must not fall between owned timers."""
        phase = phases.OwnedGradePhase(self.fixture.owner, self.started + 10)
        original = policy.os.mkdir
        timers = []
        def observe(path: Path, mode: int) -> None:
            """Observe only the new exact fixture result directory before creation."""
            self.assertEqual(path, self.fixture.attempt / "result")
            timers.append(signal.getitimer(signal.ITIMER_REAL)[0])
            original(path, mode)
        with patch.object(policy.os, "mkdir", side_effect=observe):
            self.run_phase(phase)
        self.assertEqual(len(timers), 1)
        self.assertGreater(timers[0], 0)
        self.assertLessEqual(timers[0], 10)

    def test_final_publication_callback_cannot_change_phase_before_return(self) -> None:
        """A written receipt and proved cleanup cannot authorize a changed phase."""
        phase = phases.OwnedGradePhase(self.fixture.owner, self.started + 10)
        original = self.fixture.held.check
        def mutate_after_publication() -> None:
            """Change only in-memory TEST phase after the exact fixture file exists."""
            original()
            if (self.fixture.attempt / "execution.json").exists():
                object.__setattr__(phase, "deadline", phase.deadline + 1)
        with patch.object(self.fixture.held, "check", side_effect=mutate_after_publication):
            with self.assertRaisesRegex(RuntimeError, "original binding changed"):
                self.run_phase(phase)
        self.assertTrue((self.fixture.attempt / "execution.json").exists())
        self.assertEqual(self.fixture.events.count("remove"), 1)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0)

    def test_existing_parent_timer_is_refused_not_replaced(self) -> None:
        """The phase bridge preserves existing no-nested-ALRM refusal."""
        phase = phases.OwnedGradePhase(self.fixture.owner, self.started + 10)
        self.fixture.on_hold = Mock()
        with wall_budget(self.started + 20):
            with self.assertRaisesRegex(RuntimeError, "another active wall timer"):
                self.run_phase(phase)
            self.assertGreater(signal.getitimer(signal.ITIMER_REAL)[0], 10)
        self.fixture.on_hold.assert_not_called()
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0)

    def test_expired_work_does_not_replace_separate_cleanup_budget(self) -> None:
        """Virtual cleanup may cross work cutoff, but cannot publish success."""
        phase = phases.OwnedGradePhase(self.fixture.owner, self.started + 1)
        now, timers = [self.started], []
        original = self.fixture.remove
        def delayed_remove(runtime: object, directory: str, reference: str) -> dict:
            """Observe the unchanged cleanup clock and advance virtual work time."""
            timers.append(signal.getitimer(signal.ITIMER_REAL)[0])
            now[0] += 2
            return original(runtime, directory, reference)
        self.fixture.remove = delayed_remove
        with patch.object(policy.time, "monotonic", side_effect=lambda: now[0]):
            with self.assertRaises(policy.GradeIsolationError) as raised:
                self.run_phase(phase)
        self.assertIs(raised.exception.cleanup_verified, True)
        self.assertEqual(raised.exception.evidence["cleanupBudgetSeconds"], 90)
        self.assertGreater(timers[0], 80)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0)


if __name__ == "__main__":
    unittest.main()
