"""Actual thread-directed cancellation with no media, Docker, or user processes."""
from __future__ import annotations

import signal
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from _common import pl  # noqa: F401

from color.deadline import WallBudgetExceeded, defer_owner_cancellation, wall_budget


class CancellationDeferralTests(unittest.TestCase):
    """Protect mandatory cleanup without swallowing cancellation or wall expiry."""

    def setUp(self) -> None:
        """Retain exact process signal state and start one owned unblocked thread."""
        self.previous = signal.getsignal(signal.SIGUSR1)
        self.previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, set())
        self.events = []
        self.stop, self.ready = threading.Event(), threading.Event()
        signal.signal(signal.SIGUSR1, self.cancel)
        self.worker = threading.Thread(target=self.idle)
        self.worker.start()
        self.addCleanup(self.restore)
        self.assertTrue(self.ready.wait(2))

    def cancel(self, _signal: int, _frame: object) -> None:
        """Observe when the original handler actually becomes eligible to execute."""
        self.events.append("cancelled")

    def idle(self) -> None:
        """Only this owned background thread receives the test-directed signal."""
        signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGUSR1})
        self.ready.set()
        self.stop.wait(5)

    def send(self) -> None:
        """Exercise Python's main-thread dispatch of a signal received elsewhere."""
        signal.pthread_kill(self.worker.ident, signal.SIGUSR1)
        time.sleep(0.02)

    def restore(self) -> None:
        """Discard only this test's pending signal before restoring its prior state."""
        signal.signal(signal.SIGUSR1, signal.SIG_IGN)
        signal.pthread_sigmask(signal.SIG_SETMASK, self.previous_mask)
        signal.signal(signal.SIGUSR1, self.previous)
        self.stop.set()
        self.worker.join(2)
        self.assertFalse(self.worker.is_alive())

    def test_background_delivery_waits_for_cleanup_and_restores_state(self) -> None:
        handler = signal.getsignal(signal.SIGUSR1)
        with defer_owner_cancellation():
            self.send()
            self.assertEqual(self.events, [])
            self.events.append("cleanup complete")
        self.assertEqual(self.events, ["cleanup complete", "cancelled"])
        self.assertEqual(signal.getsignal(signal.SIGUSR1), handler)
        self.assertEqual(signal.pthread_sigmask(signal.SIG_BLOCK, set()), self.previous_mask)

    def test_nested_scopes_deliver_only_after_outer_cleanup(self) -> None:
        with defer_owner_cancellation():
            with defer_owner_cancellation():
                self.send()
            self.assertEqual(self.events, [])
            self.events.append("outer complete")
        self.assertEqual(self.events, ["outer complete", "cancelled"])

    def test_preexisting_block_remains_pending_until_original_caller_unblocks(self) -> None:
        signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGUSR1, signal.SIGUSR2})
        with defer_owner_cancellation():
            self.send()
        self.assertEqual(self.events, [])
        self.assertIn(signal.SIGUSR1, signal.sigpending())
        self.assertTrue({signal.SIGUSR1, signal.SIGUSR2}.issubset(
            signal.pthread_sigmask(signal.SIG_BLOCK, set())))
        signal.pthread_sigmask(signal.SIG_SETMASK, self.previous_mask)
        self.assertEqual(self.events, ["cancelled"])

    def test_cleanup_error_is_not_converted_to_success(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "cleanup uncertain"):
            with defer_owner_cancellation():
                self.send()
                raise RuntimeError("cleanup uncertain")
        self.assertEqual(self.events, ["cancelled"])

    def test_alarm_still_interrupts_while_owner_cancellation_is_deferred(self) -> None:
        began = time.monotonic()
        handler = signal.getsignal(signal.SIGUSR1)
        with self.assertRaises(WallBudgetExceeded):
            with defer_owner_cancellation(), wall_budget(began + 0.1):
                self.send()
                time.sleep(2)
        self.assertLess(time.monotonic() - began, 1)
        self.assertEqual(self.events, ["cancelled"])
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0)
        self.assertEqual(signal.getsignal(signal.SIGUSR1), handler)
        self.assertEqual(signal.pthread_sigmask(signal.SIG_BLOCK, set()), self.previous_mask)

    def test_original_ignore_disposition_is_preserved(self) -> None:
        signal.signal(signal.SIGUSR1, signal.SIG_IGN)
        with defer_owner_cancellation():
            self.send()
        self.assertEqual(self.events, [])
        self.assertEqual(signal.getsignal(signal.SIGUSR1), signal.SIG_IGN)

    def boundary_fault(self, boundary: str) -> None:
        """An alarm after the real state mutation must still restore both controls."""
        original_signal, original_mask = signal.signal, signal.pthread_sigmask
        handler, fired = signal.getsignal(signal.SIGUSR1), []

        def set_handler(number: int, value: object) -> object:
            result = original_signal(number, value)
            phase = "restore-handler" if value == handler else "install-handler"
            if number == signal.SIGUSR1 and boundary == phase and not fired:
                fired.append(phase)
                raise WallBudgetExceeded("TEST boundary alarm")
            return result

        def set_mask(action: int, values: set) -> set:
            result = original_mask(action, values)
            phase = "restore-mask" if action == signal.SIG_SETMASK else "block-mask"
            if (values or action == signal.SIG_SETMASK) and boundary == phase and not fired:
                fired.append(phase)
                raise WallBudgetExceeded("TEST boundary alarm")
            return result

        with patch.object(signal, "signal", side_effect=set_handler), \
                patch.object(signal, "pthread_sigmask", side_effect=set_mask):
            with self.assertRaisesRegex(WallBudgetExceeded, "boundary alarm"):
                with defer_owner_cancellation():
                    self.send()
        self.assertEqual(fired, [boundary])
        self.assertEqual(signal.getsignal(signal.SIGUSR1), handler)
        self.assertEqual(signal.pthread_sigmask(signal.SIG_BLOCK, set()), self.previous_mask)

    def test_setup_and_restoration_boundary_exceptions_restore_original_state(self) -> None:
        for boundary in ("install-handler", "block-mask", "restore-mask", "restore-handler"):
            with self.subTest(boundary=boundary):
                self.boundary_fault(boundary)

    def test_raising_owner_handler_runs_after_bookkeeping(self) -> None:
        def expired(_signal: int, _frame: object) -> None:
            self.events.append("cancelled")
            raise RuntimeError("owner deadline")
        signal.signal(signal.SIGUSR1, expired)
        with self.assertRaisesRegex(RuntimeError, "owner deadline"):
            with defer_owner_cancellation():
                self.send()
                self.events.append("bookkeeping complete")
        self.assertEqual(self.events, ["bookkeeping complete", "cancelled"])

    def test_original_default_disposition_terminates_only_after_cleanup(self) -> None:
        code = '''
import os, signal
from color.deadline import defer_owner_cancellation
signal.signal(signal.SIGUSR1, signal.SIG_DFL)
with defer_owner_cancellation():
    os.kill(os.getpid(), signal.SIGUSR1)
    print("cleanup complete", flush=True)
print("unexpected continuation", flush=True)
'''
        result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, -signal.SIGUSR1)
        self.assertEqual(result.stdout.strip(), "cleanup complete")


    def cancel_with_error(self, _signal: int, _frame: object) -> None:
        """The real owning controller cancels by raising from its restored handler."""
        self.events.append("cancelled")
        raise RuntimeError("owner deadline")

    def test_grade_cleanup_finishes_evidence_before_background_cancellation(self) -> None:
        from headless import grade_observation_policy as policy
        evidence = {"cleanupVerified": False}
        def remove(*_args):
            self.send()
            self.events.append("exact absence observed")
            return {"canonicalAbsenceProved": True}
        signal.signal(signal.SIGUSR1, self.cancel_with_error)
        with patch.object(policy, "remove_container", side_effect=remove):
            with self.assertRaisesRegex(RuntimeError, "owner deadline"):
                policy._cleanup((object(), Path("/unused"), "name", "exact-id"), evidence)
        self.assertEqual(self.events, ["exact absence observed", "cancelled"])
        self.assertTrue(evidence["cleanupVerified"])
        self.assertEqual(evidence["cleanupBudgetSeconds"], 90)
        self.assertGreaterEqual(evidence["cleanupMs"], 0)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0)

    def test_batch_reconciliation_finishes_before_background_cancellation(self) -> None:
        from headless import grade_batch_cleanup as cleanup
        state = Mock()
        def reconcile(actual: object) -> None:
            self.assertIs(actual, state)
            self.send()
            self.events.append("whole set reconciled")
        signal.signal(signal.SIGUSR1, self.cancel_with_error)
        with patch.object(cleanup, "_reconcile", side_effect=reconcile):
            with self.assertRaisesRegex(RuntimeError, "owner deadline"), wall_budget(time.monotonic() + 5):
                cleanup._protected_reconcile(state)
        self.assertEqual(self.events, ["whole set reconciled", "cancelled"])
        state.prepare.assert_called_once()
        state.check.assert_called_once()
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
