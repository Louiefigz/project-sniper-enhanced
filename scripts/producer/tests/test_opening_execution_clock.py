"""Bounded real timer interruption and failure evidence for opening work."""
from __future__ import annotations

import signal
import time
import unittest
from unittest.mock import patch

from guided_opening_execution import OpeningExecutionClock, opening_clock, work_timer


class OpeningExecutionClockTests(unittest.TestCase):
    """These host timers do not replace server lease/group/container cleanup."""

    def test_real_blocking_work_is_interrupted_and_timer_disarmed(self) -> None:
        clock = opening_clock(0.03)
        started = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, "deadline"):
            clock.phase("TEST blocking work", lambda: time.sleep(2))
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0)
        self.assertEqual(clock.events[0]["status"], "failed")
        self.assertGreaterEqual(clock.events[0]["elapsedMs"], 20)
        self.assertIn("deadline", clock.events[0]["error"])

    def test_post_operation_time_check_cannot_return_late_success(self) -> None:
        clock = OpeningExecutionClock(10)
        with patch("guided_opening_execution.time.monotonic", side_effect=[0, 0, 11, 11]):
            with self.assertRaisesRegex(RuntimeError, "deadline"):
                clock.phase("TEST late return", lambda: "not approved")
        self.assertEqual(clock.events[0]["status"], "failed")

    def test_no_phase_renews_the_original_budget(self) -> None:
        clock = OpeningExecutionClock(10)
        with patch("guided_opening_execution.time.monotonic", return_value=8):
            self.assertEqual(clock.remaining(), 2)
        with patch("guided_opening_execution.time.monotonic", return_value=11):
            with self.assertRaisesRegex(RuntimeError, "deadline"):
                clock.remaining()

    def test_invalid_budgets_and_nested_wall_timer_are_rejected(self) -> None:
        for timeout in (True, 0, -1, float("nan"), float("inf"), 1500.001):
            with self.subTest(timeout=timeout), self.assertRaisesRegex(RuntimeError, "budget"):
                opening_clock(timeout)
        with work_timer(opening_clock(2)):
            with self.assertRaisesRegex(RuntimeError, "another active timer"):
                with work_timer(opening_clock(1)):
                    self.fail("nested timer must not replace its owner")


if __name__ == "__main__":
    unittest.main(verbosity=2)
