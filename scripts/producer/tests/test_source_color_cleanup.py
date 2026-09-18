"""Actual split cleanup adapter/coordinator with TEST-only metadata and virtual daemon."""
from __future__ import annotations

from dataclasses import replace
import unittest
from unittest.mock import patch

from _source_color_cleanup_fixture import SourceColorCleanupFixture
from guided_source_color_cleanup import prepare_opening_source_color_cleanup
from guided_opening_execution import OpeningExecutionClock
from headless.grade_batch_cleanup import GradeBatchCleanupError
import guided_source_color_cleanup as adapter
import guided_source_color_reservation_read as reservation_reader


class SourceColorCleanupTests(unittest.TestCase):
    """Complete names, original controls/time and actual return/failure provenance."""

    def fixture(self) -> SourceColorCleanupFixture:
        """Allocate original TEST metadata and completely replace native leaves."""
        value = SourceColorCleanupFixture()
        self.addCleanup(value.close)
        return value

    def test_partial_staging_split_uses_real_coordinator_and_grade_absence_last(self) -> None:
        """No sidecar/jobs or process settlement are invented by the adapter."""
        f = self.fixture()
        prepared = f.prepare()
        self.assertEqual(f.daemon.events, [])
        f.clock.phase("reconcile-graphic-0", lambda: None)
        f.clock.phase("cleanup-controls-after", lambda: None)
        result = prepared.reconcile()
        self.assertEqual(set(result), {"reservation", "sourceColorHash", "batch"})
        self.assertEqual(result["reservation"], {"path": str(f.files.reference[0]), "sha256": f.files.reference[1],
                                                "sizeBytes": f.files.reservation_path.stat().st_size})
        self.assertIs(result["batch"]["cleanupVerified"], True)
        self.assertEqual(tuple(row["containerName"] for row in result["batch"]["jobs"]), f.daemon.names)
        self.assertEqual([row["stage"] for row in f.clock.events], ["source-color-reservation-read", "reconcile-graphic-0",
                         "cleanup-controls-after", "reconcile-source-color-batch", "source-color-reservation-after"])
        self.assertTrue(all(row["status"] == "complete" for row in f.clock.events))
        self.assertEqual(f.timer_events, [("phase", f.clock.end)] * 3 + [("batch", f.clock.end), ("phase", f.clock.end)])
        self.assertFalse(f.files.staging.sidecar_path.exists())
        self.assertGreaterEqual(f.clock.events[-2]["elapsedMs"], result["batch"]["elapsedMs"])

    def test_initial_three_file_captures_precede_first_original_callback(self) -> None:
        """First callback remains inside original read phase after all original identities."""
        f = self.fixture()
        with patch.object(reservation_reader, "capture_staging_file", wraps=reservation_reader.capture_staging_file) as captures:
            f.guard.side_effect = lambda: self.assertEqual(captures.call_count, 3)
            f.prepare()
        self.assertGreater(f.guard.call_count, 0)
        self.assertEqual(f.daemon.events, [])

    def test_actual_runtime_must_match_original_four_claim_controls_before_read(self) -> None:
        """A typed different daemon/image cannot be passed to the cleanup coordinator."""
        f = self.fixture()
        changed = replace(f.context, runtime=replace(f.context.runtime, socket="/TEST/other-socket"))
        with patch.object(adapter, "read_source_color_reservation") as read:
            with self.assertRaisesRegex(RuntimeError, "runtime differs"):
                prepare_opening_source_color_cleanup(f.files.reference, changed)
        read.assert_not_called()
        self.assertEqual(f.daemon.events, [])

    def test_changed_reserved_bytes_after_prepare_fail_before_any_daemon_inspection(self) -> None:
        """The full originally held planned set is not refreshed after caller graphics checks."""
        f = self.fixture()
        prepared = f.prepare()
        f.files.reservation["jobs"].reverse()
        f.files.publish()
        with self.assertRaises(GradeBatchCleanupError) as raised:
            prepared.reconcile()
        self.assertIs(raised.exception.diagnostics["cleanupVerified"], False)
        self.assertEqual(f.daemon.events, [])
        self.assertEqual(f.clock.events[-1]["status"], "failed")

    def test_context_and_original_clock_replacements_cannot_gain_another_allowance(self) -> None:
        """Post-prepare context drift rejects before native work and records failed time."""
        f = self.fixture()
        prepared = f.prepare()
        f.clock.end += 1
        with self.assertRaisesRegex(RuntimeError, "original context"):
            prepared.reconcile()
        self.assertEqual(f.daemon.events, [])
        self.assertEqual(f.clock.events[-1]["status"], "failed")

    def test_expired_original_clock_does_not_launch_coordinator_work(self) -> None:
        """Preparation plus caller work spends the same protected end before reconciliation."""
        f = self.fixture()
        prepared = f.prepare()
        f.daemon.now = f.clock.end
        with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
            prepared.reconcile()
        self.assertEqual(f.daemon.events, [])
        self.assertEqual(f.clock.events[-1]["status"], "failed")

    def test_unknown_daemon_failure_retains_real_partial_diagnostics_and_timing(self) -> None:
        """The original coordinator error is not normalized to a successful empty batch."""
        f = self.fixture()
        prepared = f.prepare()

        def unknown() -> None:
            """Use one actual virtual inspection before exhausting the original clock."""
            f.daemon.now = f.clock.end

        f.daemon.before_inspect.side_effect = lambda _: unknown()
        with self.assertRaises(GradeBatchCleanupError) as raised:
            prepared.reconcile()
        self.assertIs(raised.exception.diagnostics["cleanupVerified"], False)
        self.assertEqual(raised.exception.diagnostics["jobs"][0]["inspections"], 1)
        self.assertEqual(f.clock.events[-1]["elapsedMs"], 30_000)
        self.assertEqual(f.clock.events[-1]["status"], "failed")

    def test_final_original_callback_cannot_mutate_actual_batch_return(self) -> None:
        """Bind actual coordinator metadata before final reservation phase callbacks."""
        f, actual, captured = self.fixture(), adapter.reconcile_grade_batch, []

        def observe(names: tuple[str, ...], context: object) -> dict:
            """Capture the actual coordinator result from entirely virtual native leaves."""
            result = actual(names, context)
            captured.append(result)
            return result

        f.guard.side_effect = lambda: captured[0].update(cleanupVerified=False) if captured else None
        with patch.object(adapter, "reconcile_grade_batch", side_effect=observe):
            with self.assertRaisesRegex(RuntimeError, "actual batch result changed"):
                f.run()
        self.assertIs(captured[0]["cleanupVerified"], False)

    def test_final_callback_runtime_drift_and_repeat_reconcile_are_refused(self) -> None:
        """Successful absence never allows refreshing actual controls or starting twice."""
        f = self.fixture()
        prepared = f.prepare()
        prepared.reconcile()
        count = len(f.daemon.events)
        with self.assertRaisesRegex(RuntimeError, "cannot repeat"):
            prepared.reconcile()
        self.assertEqual(len(f.daemon.events), count)
        f = self.fixture()
        prepared = f.prepare()
        f.guard.side_effect = lambda: object.__setattr__(f.context, "runtime", replace(f.context.runtime))
        with self.assertRaises(GradeBatchCleanupError):
            prepared.reconcile()
        self.assertEqual(f.daemon.events, [])

    def test_clock_method_substitution_is_not_a_protected_phase(self) -> None:
        """An actual class name alone cannot replace the original timer-bearing methods."""
        f = self.fixture()
        clock = OpeningExecutionClock(f.clock.end)
        clock.phase = lambda name, operation, limit=None: operation()
        with self.assertRaisesRegex(ValueError, "actual original clock methods"):
            replace(f.context, clock=clock)
        self.assertEqual(f.daemon.events, [])

    def test_oversized_cleanup_allowance_is_not_used_even_for_preparation(self) -> None:
        """The adapter cannot use a wider work clock before the coordinator's own cap."""
        f = self.fixture()
        context = replace(f.context, clock=OpeningExecutionClock(f.daemon.now + 301))
        with patch.object(adapter, "read_source_color_reservation") as read:
            with self.assertRaisesRegex(ValueError, "at most300"):
                prepare_opening_source_color_cleanup(f.files.reference, context)
        read.assert_not_called()

    def test_prepared_execution_fields_cannot_be_replaced_independently_of_context(self) -> None:
        """The retained daemon, callback and cutoff are bound before their invocation."""
        f = self.fixture()
        prepared = f.prepare()
        prepared.runtime = replace(prepared.runtime, socket="/TEST/other")
        with self.assertRaisesRegex(RuntimeError, "original execution/config"):
            prepared.reconcile()
        self.assertEqual(f.daemon.events, [])

    def test_private_config_identity_remains_original_between_prepare_and_reconcile(self) -> None:
        """An explicit TEST config mode change cannot become a new cleanup baseline."""
        f = self.fixture()
        prepared = f.prepare()
        config = f.daemon.config
        self.assertEqual(config.parent, f.daemon.root)
        self.assertEqual(config.resolve(), config)
        config.chmod(0o750)
        with self.assertRaises(GradeBatchCleanupError):
            prepared.reconcile()
        self.assertEqual(f.daemon.events, [])

    def test_final_reservation_file_change_cannot_follow_successful_grade_absence(self) -> None:
        """Last guarded metadata mutation fails, rather than returning old-name cleanup."""
        f, actual, complete = self.fixture(), adapter.reconcile_grade_batch, []

        def observe(names: tuple[str, ...], context: object) -> dict:
            """Mark actual coordinator return; do not substitute cleanup observations."""
            result = actual(names, context)
            complete.append(True)
            return result

        def mutate() -> None:
            """Write only the original named TEST reservation after native leaves finish."""
            if complete:
                f.files.write(f.files.reservation_path, f.files.reservation_path.read_bytes())

        f.guard.side_effect = mutate
        with patch.object(adapter, "reconcile_grade_batch", side_effect=observe):
            with self.assertRaisesRegex(RuntimeError, "file or ancestry changed"):
                f.run()
        self.assertEqual(f.clock.events[-2]["status"], "complete")
        self.assertEqual(f.clock.events[-1]["stage"], "source-color-reservation-after")
        self.assertEqual(f.clock.events[-1]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
