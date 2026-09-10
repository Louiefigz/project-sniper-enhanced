"""Real cleanup coordination with virtual clock/daemon; no native operations."""
from __future__ import annotations

import signal
import time
import unittest
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from _grade_batch_cleanup_fixture import GradeBatchCleanupFixture
from headless import grade_batch_cleanup as cleanup
from headless.container_policy import DockerRuntime


class GradeBatchCleanupTests(unittest.TestCase):
    """Whole-set stability, exact original controls and failure diagnostics."""

    def fixture(self, count: int = 2, duration: float = 30.0) -> GradeBatchCleanupFixture:
        """Register cleanup for this exact TEST-root config and simulated native leaves."""
        result = GradeBatchCleanupFixture(count, duration)
        self.addCleanup(result.close)
        return result

    def test_128_names_share_three_seconds_and_one_original_timer(self) -> None:
        """The stable window is shared, not128 separately renewed three-second waits."""
        fixture = self.fixture(128)
        result = fixture.run()
        self.assertEqual(fixture.now, 1003.0)
        self.assertEqual(fixture.timers, [fixture.deadline])
        self.assertEqual(result["stableAbsenceMs"], 3000)
        self.assertEqual(result["passes"], 14)
        self.assertEqual([row["containerName"] for row in result["jobs"]], list(fixture.names))
        self.assertTrue(all(row["canonicalAbsenceProved"] and row["inspections"] == 28 for row in result["jobs"]))
        self.assertEqual(fixture.masks, [(signal.SIG_BLOCK, {signal.SIGUSR1}), (signal.SIG_SETMASK, set())])
        self.assertFalse(any((fixture.config / leaf).exists() for leaf in ("launch-intent.json", "launch-response.json")))

    def test_lost_response_still_removes_every_exact_reserved_name(self) -> None:
        """No intent/response file is needed to reconcile authenticated reserved names."""
        fixture = self.fixture()
        fixture.present.update(fixture.names)
        result = fixture.run()
        self.assertTrue(result["cleanupVerified"])
        self.assertFalse(fixture.present)
        self.assertEqual([row["successfulRemovalResponses"] for row in result["jobs"]], [1, 1])

    def test_create_after_first_pass_resets_shared_window_without_new_timer(self) -> None:
        """Every later pass revisits all names and removes a late virtual create."""
        fixture = self.fixture()
        created = [False]

        def late(name: str) -> None:
            """Simulate a previously submitted daemon create after the first full pass."""
            if fixture.now >= 1001 and name == fixture.names[-1] and not created[0]:
                created[0] = True
                fixture.present.add(name)

        fixture.before_inspect.side_effect = late
        result = fixture.run()
        self.assertEqual(fixture.now, 1004.0)
        self.assertEqual(result["jobs"][-1]["successfulRemovalResponses"], 1)
        self.assertEqual(fixture.timers, [fixture.deadline])

    def test_final_confirmation_create_requires_fresh_full_stability(self) -> None:
        """A create in the extra final sweep cannot reuse the preceding quiet window."""
        fixture = self.fixture()
        created = [False]

        def last_pass(name: str) -> None:
            """Inject only at this name's third inspection at the three-second boundary."""
            matching = sum(event == ("inspect", name, 1003.0) for event in fixture.events)
            if fixture.now == 1003 and name == fixture.names[0] and matching == 3 and not created[0]:
                fixture.present.add(name)
                created[0] = True

        fixture.before_inspect.side_effect = last_pass
        result = fixture.run()
        self.assertTrue(created[0])
        self.assertEqual(fixture.now, 1006.0)
        self.assertEqual(result["stableAbsenceMs"], 3000)
        self.assertFalse(fixture.present)

    def test_reported_rm_success_does_not_claim_observed_presence(self) -> None:
        """Match existing policy: rm success cannot override two canonical absence reads."""
        fixture = self.fixture(1)
        with patch.object(cleanup, "_force_remove", return_value=True):
            result = fixture.run()
        self.assertEqual(result["elapsedMs"], 3000)
        self.assertEqual(result["jobs"][0]["successfulRemovalResponses"], 14)
        self.assertFalse(fixture.present)

    def test_unknown_preinspect_resets_shared_stability_even_when_postinspect_is_absent(self) -> None:
        """An ambiguous pre-removal read cannot borrow a previous absence interval."""
        fixture = self.fixture()
        once = [False]

        def inspect(runtime: object, config: str, name: str) -> bool | None:
            """Simulate one ambiguous native read, then preserve exact normal virtual reads."""
            result = fixture.inspect(runtime, config, name)
            if fixture.now == 1002 and not once[0]:
                once[0] = True
                return None
            return result

        with patch.object(cleanup, "_is_absent", side_effect=inspect):
            result = fixture.run()
        self.assertEqual(result["elapsedMs"], 5000)

    def test_unknown_absence_cannot_start_or_complete_stability(self) -> None:
        """Timeout-like unknowns preserve diagnostics and fail at the original cutoff."""
        fixture = self.fixture(2, 1.0)
        with patch.object(cleanup, "_is_absent", return_value=None):
            with self.assertRaises(cleanup.GradeBatchCleanupError) as caught:
                fixture.run()
        value = caught.exception.diagnostics
        self.assertFalse(value["cleanupVerified"])
        self.assertTrue(all(row["lastObservation"] == "unknown" and not row["canonicalAbsenceProved"] for row in value["jobs"]))
        self.assertEqual(fixture.now, fixture.deadline)

    def test_removal_failure_preserves_partial_rows_and_restores_mask(self) -> None:
        """A daemon failure is never replaced by successful earlier per-name observations."""
        fixture = self.fixture()
        fixture.before_remove.side_effect = lambda name: (_ for _ in ()).throw(RuntimeError("TEST rm failed")) \
            if name == fixture.names[-1] else None
        with self.assertRaises(cleanup.GradeBatchCleanupError) as caught:
            fixture.run()
        value = caught.exception.diagnostics
        self.assertFalse(value["cleanupVerified"])
        self.assertEqual([row["removalAttempts"] for row in value["jobs"]], [1, 1])
        self.assertEqual(value["jobs"][0]["lastObservation"], "absent")
        self.assertFalse(value["jobs"][0]["canonicalAbsenceProved"])
        self.assertEqual(fixture.masks[-1], (signal.SIG_SETMASK, set()))

    def test_first_guard_failure_has_no_native_calls_or_success(self) -> None:
        """Caller settlement/runtime refusal stops before any virtual inspect/remove."""
        fixture = self.fixture()
        fixture.guard.side_effect = RuntimeError("TEST original settlement unresolved")
        with self.assertRaises(cleanup.GradeBatchCleanupError) as caught:
            fixture.run()
        self.assertEqual(fixture.events, [])
        self.assertFalse(caught.exception.diagnostics["cleanupVerified"])

    def test_context_mutations_cannot_supply_new_runtime_or_deadline(self) -> None:
        """Construction and first-callback bindings close original argument substitutions."""
        fixture = self.fixture()
        original = fixture.context.deadline
        object.__setattr__(fixture.context, "deadline", original + 1)
        with self.assertRaisesRegex(ValueError, "original context changed"):
            fixture.run()
        object.__setattr__(fixture.context, "deadline", original)
        fixture.guard.side_effect = lambda: fixture.runtime.approval.update(TEST=False)
        with self.assertRaisesRegex(cleanup.GradeBatchCleanupError, "original controls changed"):
            fixture.run()
        self.assertEqual(fixture.events, [])

    def test_instance_binding_override_cannot_launder_a_replacement_runtime(self) -> None:
        """Never use a caller-replaceable binding method for original-control checks."""
        fixture = self.fixture(1)
        original = fixture.context.binding()
        replacement = DockerRuntime("/TEST/changed-docker", "/TEST/changed-socket", "sha256:" + "b" * 64,
                                    "501:20", {"TEST": "changed"})

        def substitute() -> None:
            """Reproduce the original bypass without any native operations or files."""
            object.__setattr__(fixture.context, "binding", lambda: original)
            object.__setattr__(fixture.context, "runtime", replacement)

        fixture.guard.side_effect = substitute
        with patch.object(cleanup, "_is_absent", return_value=True) as inspected, \
                patch.object(cleanup, "_force_remove", return_value=False) as removed:
            with self.assertRaisesRegex(cleanup.GradeBatchCleanupError, "original controls changed"):
                fixture.run()
        inspected.assert_not_called()
        removed.assert_not_called()

    def test_original_snapshot_replacement_cannot_rebaseline_after_callback(self) -> None:
        """Even equal detached origin metadata cannot replace the actual retained origin."""
        fixture = self.fixture(1)
        fixture.guard.side_effect = lambda: object.__setattr__(fixture.context, "_original", deepcopy(fixture.context._original))
        with self.assertRaisesRegex(cleanup.GradeBatchCleanupError, "original controls changed") as caught:
            fixture.run()
        self.assertFalse(caught.exception.diagnostics["cleanupVerified"])
        self.assertEqual(fixture.events, [])

    def test_actual_original_timer_covers_first_filesystem_setup(self) -> None:
        """A real short POSIX timer interrupts setup before any virtual Docker leaf."""
        fixture = self.fixture(1)
        fixture.stack.close()
        context = replace(fixture.context, deadline=time.monotonic() + 0.03)
        timers, completed = [], []

        def delayed_setup(_path: Path) -> tuple:
            """Delay only a TEST setup leaf, with no mutation or native resource access."""
            timers.append(signal.getitimer(signal.ITIMER_REAL)[0])
            time.sleep(0.08)
            completed.append(True)
            raise RuntimeError("TEST setup exceeded the original cutoff")

        with patch.object(cleanup, "directory_identity", side_effect=delayed_setup), \
                patch.object(cleanup, "_is_absent") as inspected, patch.object(cleanup, "_force_remove") as removed:
            with self.assertRaises(cleanup.GradeBatchCleanupError) as caught:
                cleanup.reconcile_grade_batch(fixture.names, context)
        self.assertTrue(timers and timers[0] > 0)
        self.assertEqual(completed, [])
        self.assertFalse(caught.exception.diagnostics["cleanupVerified"])
        self.assertEqual(caught.exception.diagnostics["jobs"][0]["lastObservation"], "not-observed")
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0)
        fixture.guard.assert_not_called()
        inspected.assert_not_called()
        removed.assert_not_called()

    def test_native_return_guard_expiry_rejects_same_original_clock(self) -> None:
        """A fixed native primitive cannot consume the remaining allowance and pass."""
        fixture = self.fixture()
        fixture.before_inspect.side_effect = lambda _name: setattr(fixture, "now", fixture.deadline)
        with self.assertRaises(cleanup.GradeBatchCleanupError) as caught:
            fixture.run()
        self.assertEqual(len(fixture.events), 1)
        self.assertFalse(caught.exception.diagnostics["cleanupVerified"])

    def test_original_deadline_after_final_report_is_not_renewed(self) -> None:
        """Serializing final evidence remains inside the original protected allowance."""
        fixture = self.fixture()
        original = cleanup._Cleanup.report

        def report(state: object, complete: bool) -> dict:
            """Expire only after producing the hypothetical success report."""
            result = original(state, complete)
            if complete:
                fixture.now = fixture.deadline
            return result

        with patch.object(cleanup._Cleanup, "report", new=report):
            with self.assertRaises(cleanup.GradeBatchCleanupError) as caught:
                fixture.run()
        self.assertFalse(caught.exception.diagnostics["cleanupVerified"])

    def test_bad_names_and_active_timer_fail_before_callbacks_or_signal_changes(self) -> None:
        """No wildcard, UUIDv1, duplicate, empty or unbounded inventory reaches Docker."""
        fixture = self.fixture()
        malformed = ((), fixture.names * 2, (*fixture.names, "*"), list(fixture.names),
                     ("sniper-grade-observation-" + UUID(int=1, version=1).hex,), fixture.names * 65)
        for names in malformed:
            with self.assertRaises(ValueError):
                cleanup.reconcile_grade_batch(names, fixture.context)
        with patch.object(cleanup.signal, "getitimer", return_value=(1.0, 0.0)):
            with self.assertRaisesRegex(RuntimeError, "active wall timer"):
                fixture.run()
        self.assertEqual((fixture.events, fixture.masks, fixture.timers), ([], [], []))
        fixture.guard.assert_not_called()

    def test_original_aggregate_cap_and_private_config_are_required(self) -> None:
        """Only a cleanup remainder at most300 seconds is accepted; no new clock is made."""
        fixture = self.fixture()
        for deadline in (1000.0, 999.0, 1300.01):
            with self.assertRaisesRegex(ValueError, "protected remainder"):
                cleanup.reconcile_grade_batch(fixture.names, replace(fixture.context, deadline=deadline))
        for value in (float("nan"), float("inf"), True):
            with self.assertRaises(ValueError):
                replace(fixture.context, deadline=value)
        with self.assertRaises(ValueError):
            replace(fixture.context, config_dir=Path("relative"))
        fixture.config.chmod(0o755)
        with self.assertRaisesRegex(cleanup.GradeBatchCleanupError, "private and owned") as caught:
            fixture.run()
        self.assertFalse(caught.exception.diagnostics["cleanupVerified"])
        self.assertEqual(fixture.events, [])


if __name__ == "__main__":
    unittest.main()
