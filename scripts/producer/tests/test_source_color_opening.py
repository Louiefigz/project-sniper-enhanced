"""Real opening metadata/owned handoff with explicitly synthetic native leaves."""
from __future__ import annotations

import signal
import unittest
from unittest.mock import patch

from _source_color_batch_fixture import current_batch_test_pins
from _source_color_opening_fixture import SourceColorOpeningFixture
import guided_source_color_opening as opening
from headless.grade_observation_policy import GradeIsolationError


class SourceColorOpeningTests(unittest.TestCase):
    """The original opening budget and admitted identities span every source job."""

    @classmethod
    def setUpClass(cls) -> None:
        """Hold actual implementation pins once for this source-stable TEST cohort."""
        cls.pins = current_batch_test_pins()

    def setUp(self) -> None:
        """Use fresh named TEST metadata and existing stub admission/native leaves."""
        self.fixture = SourceColorOpeningFixture(self.pins)
        self.addCleanup(self.fixture.cleanup)

    def test_actual_objects_order_original_clock_and_false_flags(self) -> None:
        """Return the exact completed batch without cloning observations or renewing time."""
        captured = []
        actual = opening.run_source_color_batch

        def run(batch: object) -> object:
            """Capture the actual runner return and inspect the untimed batch boundary."""
            self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0)
            result = actual(batch)
            captured.append(result)
            return result

        original_events = self.fixture.clock.events
        with patch.object(opening, "run_source_color_batch", side_effect=run):
            result = self.fixture.execute()
        self.assertIs(result, captured[0])
        self.assertIs(result.preparation.inputs, self.fixture.inputs)
        self.assertEqual([row.source_id for row in result.timings], ["raw-b", "raw-a"])
        self.assertEqual([row.elapsed_ms for row in result.timings], [1000, 1000])
        self.assertIs(self.fixture.clock.events, original_events)
        self.assertEqual([row["stage"] for row in original_events], [f"source-color-{name}" for name in
                         ("staging", "preparation", "preflight", "observation", "completion")])
        self.assertTrue(all(row["status"] == "complete" for row in original_events))
        for prepared, row, call in zip(result.preparation.jobs, result.observations, self.fixture.calls):
            self.assertIs(row.context.source, prepared.source)
            self.assertIs(row.observation, self.fixture.returned_by_source[prepared.binding.source_id])
            self.assertEqual(call[3].owner.deadline, self.fixture.clock.end)
        self.assertEqual([result.executable, result.grade_applicable, result.delivery_approved], [False, False, False])
        result.assert_current()

    def test_persistent_completed_lifetime_survives_retired_reservation(self) -> None:
        """Retired launch claims do not invalidate the original source/project evidence."""
        result = self.fixture.execute()
        self.fixture.retired_reservation()
        self.fixture.clock.events.append({"stage": "TEST later base phase", "status": "not executed"})
        result.assert_current()
        with self.assertRaises(RuntimeError):
            self.fixture.calls[0][3].owner.guard()
        self.fixture.now = self.fixture.clock.end
        with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
            result.assert_current()

    def test_metadata_phases_own_hard_timer_without_wrapping_batch(self) -> None:
        """Original guards and metadata IO run under the same finite phase timer."""
        actual = opening.read_source_color_staging
        seen = []

        def read(reference: tuple, context: object) -> object:
            """Inspect an actual reader entry, not a test-only replacement result."""
            seen.append(signal.getitimer(signal.ITIMER_REAL)[0])
            self.assertEqual(context.deadline, self.fixture.clock.end)
            return actual(reference, context)

        with patch.object(opening, "read_source_color_staging", side_effect=read):
            self.fixture.execute()
        self.assertTrue(seen and 0 < seen[0] <= 300)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0)

    def test_second_source_failure_preserves_actual_attempt_timings(self) -> None:
        """Retain real owner failure diagnostics without exposing a partial batch."""
        actual = self.fixture.native_stub

        def fail(source: str, request: dict, directory: object, phase: object) -> dict:
            """Fail only the second synthetic native leaf, keeping real failure publication."""
            if len(self.fixture.calls) == 1:
                self.fixture.now += 3
                raise GradeIsolationError("TEST second source failed", {"cleanupVerified": True, "cleanupMs": 7})
            return actual(source, request, directory, phase)

        self.fixture.worker.side_effect = fail
        with self.assertRaises(opening.SourceColorOpeningError) as caught:
            self.fixture.execute()
        error = caught.exception
        self.assertEqual(error.stage, "observation")
        self.assertEqual([row.status for row in error.timings], ["complete", "failed"])
        self.assertEqual([row.elapsed_ms for row in error.timings], [1000, 3000])
        self.assertIs(error.timings, error.__cause__.timings)
        self.assertFalse(hasattr(error, "observations"))
        self.assertEqual(self.fixture.clock.events[-1]["status"], "failed")

    def test_final_expiry_preserves_completed_job_timings_not_success(self) -> None:
        """Original time consumed after native completion still prevents adapter success."""
        actual = opening.run_source_color_batch

        def expire(batch: object) -> object:
            """Return the actual completed object, then exhaust only the original TEST clock."""
            result = actual(batch)
            self.fixture.now = self.fixture.clock.end
            return result

        with patch.object(opening, "run_source_color_batch", side_effect=expire), \
                self.assertRaises(opening.SourceColorOpeningError) as caught:
            self.fixture.execute()
        self.assertEqual(caught.exception.stage, "completion")
        self.assertEqual(len(caught.exception.timings), 2)
        self.assertEqual(self.fixture.clock.events[-1]["status"], "failed")

    def test_original_source_is_not_late_captured_by_adapter(self) -> None:
        """An absent initial verification capture cannot be repaired by hashing later."""
        object.__setattr__(self.fixture.inputs, "verified_media", None)
        with self.assertRaisesRegex(opening.SourceColorOpeningError, "actual opening inputs and capture"):
            self.fixture.execute()
        self.fixture.worker.assert_not_called()


if __name__ == "__main__":
    unittest.main()
