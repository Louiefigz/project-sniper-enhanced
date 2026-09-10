"""Real batch ordering/publication/sealing with explicit TEST native leaves only."""
from __future__ import annotations

import unittest
from dataclasses import replace
from unittest.mock import patch

from _source_color_batch_fixture import current_batch_test_pins
from _source_color_execution_fixture import SourceColorExecutionFixture
import guided_source_color_execution as execution
from headless.grade_observation_policy import GradeIsolationError


class SourceColorExecutionTests(unittest.TestCase):
    """The complete original source set or a failure with exact attempted work timings."""

    @classmethod
    def setUpClass(cls) -> None:
        """Capture actual code pins once for this stable TEST cohort, never production reuse."""
        cls.pins = current_batch_test_pins()

    def setUp(self) -> None:
        """Create fresh private jobs/source holds; no existing artifact is overwritten."""
        self.fixture = SourceColorExecutionFixture(self.pins)
        self.addCleanup(self.fixture.cleanup)

    def test_same_original_sources_order_and_actual_observations_are_returned(self) -> None:
        """No typed observation is reconstructed from result JSON or a different source."""
        result = self.fixture.execute()
        self.assertIs(result.preparation, self.fixture.held)
        self.assertEqual([row.source_id for row in result.timings], ["raw-b", "raw-a"])
        self.assertEqual([row.started_ms for row in result.timings], [0, 1000])
        self.assertEqual([row.elapsed_ms for row in result.timings], [1000, 1000])
        self.assertEqual(result.elapsed_ms, 2000)
        for prepared, observed in zip(self.fixture.batch.jobs, result.observations):
            self.assertIs(observed.context.source, prepared.source)
            self.assertIs(observed.observation, self.fixture.returned_by_source[prepared.source_id])
            self.assertEqual(observed.context.deadline, self.fixture.context.deadline)
        self.assertTrue(all(row.cleanup_verified is True for row in result.timings))
        self.assertIs(result.executable, False)
        self.assertIs(result.grade_applicable, False)
        self.assertIs(result.delivery_approved, False)
        result.assert_current()

    def test_first_source_phase_can_expire_during_second_without_renewal(self) -> None:
        """Immediate sealing retains completed data while another original source is observed."""
        self.fixture.work_seconds = 90.0
        result = self.fixture.execute()
        self.assertEqual(self.fixture.now, 1180.0)
        self.assertEqual([row.phase_deadline for row in result.observations], [1120.0, 1210.0])
        self.assertEqual([row.started_ms for row in result.timings], [0, 90000])
        self.assertEqual([row.elapsed_ms for row in result.timings], [90000, 90000])
        result.assert_current()
        with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
            result.observations[0]._owned.assert_current()

    def test_completed_data_does_not_reacquire_transient_launch_guards(self) -> None:
        """Later evidence checks use persistent project/source/tool ownership only."""
        result = self.fixture.execute()
        for ref in self.fixture.refs:
            ref.launch.guard.side_effect = AssertionError("TEST resource claim retired")
        result.assert_current()
        for ref in self.fixture.refs:
            ref.launch.guard.assert_not_called()

    def test_second_source_failure_retains_first_timing_but_no_partial_result(self) -> None:
        """A clean earlier source does not make an incomplete batch successful."""
        actual = self.fixture.native_stub

        def fail_second(source: str, request: dict, directory: object, phase: object) -> dict:
            """Fail only the second TEST native call, keeping actual project failure publication."""
            if len(self.fixture.calls) == 1:
                self.fixture.now += 3
                raise GradeIsolationError("TEST second source decode failed", {"cleanupVerified": True, "cleanupMs": 7})
            return actual(source, request, directory, phase)

        self.fixture.worker.side_effect = fail_second
        with self.assertRaises(execution.SourceColorExecutionError) as caught:
            self.fixture.execute()
        self.assertEqual([row.status for row in caught.exception.timings], ["complete", "failed"])
        self.assertEqual([row.elapsed_ms for row in caught.exception.timings], [1000, 3000])
        self.assertTrue(caught.exception.timings[1].cleanup_verified)
        self.assertFalse(hasattr(caught.exception, "observations"))

    def test_first_source_unknown_cleanup_stops_before_second_launch(self) -> None:
        """No retry, second job or shared resource release is implied by a failure report."""
        self.fixture.worker.side_effect = GradeIsolationError("TEST cleanup unresolved", {"cleanupVerified": False, "cleanupMs": 90})
        with self.assertRaises(execution.SourceColorExecutionError) as caught:
            self.fixture.execute()
        self.fixture.worker.assert_called_once()
        self.assertEqual(len(caught.exception.timings), 1)
        self.assertIs(caught.exception.timings[0].cleanup_verified, False)
        self.assertFalse((self.fixture.batch.jobs[1].directory / "execution").exists())

    def test_expired_entry_performs_no_native_work(self) -> None:
        """The original overall time, not source count, controls batch eligibility."""
        self.fixture.now = self.fixture.context.deadline
        with self.assertRaises(execution.SourceColorExecutionError) as caught:
            self.fixture.execute()
        self.assertEqual(caught.exception.timings, ())
        self.fixture.worker.assert_not_called()

    def test_last_source_clock_expiry_never_publishes_batch_success(self) -> None:
        """Time consumed by actual worker setup and publication remains in the same phase."""
        self.fixture.work_seconds = 120.0
        with self.assertRaisesRegex(execution.SourceColorExecutionError, "deadline exceeded") as caught:
            self.fixture.execute()
        self.assertEqual(len(caught.exception.timings), 1)
        self.assertEqual(caught.exception.timings[0].elapsed_ms, 120000)
        self.fixture.worker.assert_called_once()

    def test_completed_data_still_expires_at_original_overall_time(self) -> None:
        """Completion is not an indefinitely reusable authority or a new source capture."""
        result = self.fixture.execute()
        self.fixture.now = self.fixture.context.deadline
        with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
            result.assert_current()

    def test_changed_later_job_rejects_before_any_native_work(self) -> None:
        """All prepared jobs stay checked, including a second source not yet observed."""
        self.fixture.batch.jobs[1].value["declaration"]["historyState"] = "unknown"
        with self.assertRaises(execution.SourceColorExecutionError):
            self.fixture.execute()
        self.fixture.worker.assert_not_called()

    def test_timing_or_source_context_clone_cannot_become_completed_current(self) -> None:
        """The result holds actual timing rows and original typed source contexts."""
        result = self.fixture.execute()
        object.__setattr__(result, "timings", tuple(replace(row) for row in result.timings))
        with self.assertRaisesRegex(RuntimeError, "original references or metadata changed"):
            result.assert_current()

    def test_last_callback_cannot_modify_earlier_observation(self) -> None:
        """One final non-callback metadata check covers all previously read observations."""
        result = self.fixture.execute()
        self.fixture.guard.reset_mock()
        result.assert_current()
        total = self.fixture.guard.call_count
        self.fixture.guard.reset_mock()

        def mutate() -> None:
            """Modify only actual synthetic TEST observation metadata at the final callback."""
            if self.fixture.guard.call_count == total:
                object.__setattr__(result.observations[0].observation, "grade_applicable", True)

        self.fixture.guard.side_effect = mutate
        with self.assertRaisesRegex(RuntimeError, "original references or metadata changed"):
            result.assert_current()

    def test_no_new_outer_timer_wraps_the_native_cleanup_phase(self) -> None:
        """The existing per-source policy alone owns work and protected cleanup timers."""
        with patch("guided_opening_execution.OpeningExecutionClock.phase", side_effect=AssertionError("no nested phase")):
            self.assertEqual(len(self.fixture.execute().observations), 2)

    def test_last_callback_cannot_change_an_earlier_source_evidence_file(self) -> None:
        """A callback-free final file sweep covers every completed source's publications."""
        result = self.fixture.execute()
        target = self.fixture.batch.jobs[0].directory / "execution/result/probe.json"
        self.fixture.allowed_faults.add(target)
        self.fixture.guard.reset_mock()
        result.assert_current()
        total = self.fixture.guard.call_count
        self.fixture.guard.reset_mock()

        def mutate() -> None:
            """Write only the exact first job's explicit synthetic TEST probe file."""
            if self.fixture.guard.call_count == total:
                self.fixture.change(target, b"TEST late first-source probe mutation\n")

        self.fixture.guard.side_effect = mutate
        with self.assertRaisesRegex(RuntimeError, "held publication or evidence changed"):
            result.assert_current()

    def test_duplicate_execution_does_not_launch_any_source_again(self) -> None:
        """New-only original job publications fail before repeat decoder dispatch."""
        self.fixture.execute()
        original_calls = self.fixture.worker.call_count
        with self.assertRaises(execution.SourceColorExecutionError):
            self.fixture.execute()
        self.assertEqual(self.fixture.worker.call_count, original_calls)

    def test_completed_json_cannot_construct_a_live_batch(self) -> None:
        """There is no record, deadline or callback constructor for completed evidence."""
        with self.assertRaisesRegex(TypeError, "requires run_source_color_batch"):
            execution.CompletedSourceColorBatch()
        with self.assertRaisesRegex(ValueError, "actual all-source batch preflight"):
            execution.run_source_color_batch({"complete": True})

    def test_total_elapsed_includes_completed_data_validation(self) -> None:
        """Final held-result checks must not disappear from the batch's elapsed timing."""
        original = execution.CompletedSourceColorBatch.assert_current

        def delay(value: execution.CompletedSourceColorBatch) -> None:
            """Run real validation, then consume five seconds of the same TEST clock."""
            original(value)
            self.fixture.now += 5.0

        with patch.object(execution.CompletedSourceColorBatch, "assert_current", delay):
            result = self.fixture.execute()
        self.assertEqual([row.elapsed_ms for row in result.timings], [1000, 1000])
        self.assertEqual(result.elapsed_ms, 7000)

    def test_final_timing_measurement_cannot_rebaseline_observation_mutation(self) -> None:
        """Only the elapsed scalar may change; original result metadata is not recaptured."""
        original = execution.CompletedSourceColorBatch.assert_current

        def mutate(value: execution.CompletedSourceColorBatch) -> None:
            """Mutate only synthetic TEST observation data after actual final validation."""
            original(value)
            object.__setattr__(value.observations[0].observation, "grade_applicable", True)

        with patch.object(execution.CompletedSourceColorBatch, "assert_current", mutate), \
                self.assertRaisesRegex(execution.SourceColorExecutionError, "original references or metadata changed"):
            self.fixture.execute()

    def test_final_timing_measurement_keeps_original_overall_cutoff(self) -> None:
        """A final completion-check delay does not create time for a successful timestamp."""
        original = execution.CompletedSourceColorBatch.assert_current

        def expire(value: execution.CompletedSourceColorBatch) -> None:
            """Use only the original TEST cutoff, without a replacement context or timer."""
            original(value)
            self.fixture.now = self.fixture.context.deadline

        with patch.object(execution.CompletedSourceColorBatch, "assert_current", expire), \
                self.assertRaisesRegex(execution.SourceColorExecutionError, "deadline exceeded"):
            self.fixture.execute()

    def test_final_timing_measurement_cannot_adopt_a_replacement_origin(self) -> None:
        """The original completion binding is held before final validation callbacks."""
        original = execution.CompletedSourceColorBatch.assert_current

        def replace_origin(value: execution.CompletedSourceColorBatch) -> None:
            """Replace only the private TEST seal after real validation returns."""
            original(value)
            object.__setattr__(value, "_origin", tuple(list(value._origin)))

        with patch.object(execution.CompletedSourceColorBatch, "assert_current", replace_origin), \
                self.assertRaisesRegex(execution.SourceColorExecutionError, "original references or metadata changed"):
            self.fixture.execute()


if __name__ == "__main__":
    unittest.main()
