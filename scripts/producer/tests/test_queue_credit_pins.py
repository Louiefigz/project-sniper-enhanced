"""C9 pins after P1-RP5 (X218): a credit grace never pauses the batch deadline, and a credit reference is checked.

F-m5: during a named credit error's grace the watchdog still stops a child whose batch deadline has passed, read
without credit (``native_budget_clock.uncredited_remaining``); only D-O10's claim, cancel and acknowledgement checks
wait for the grace (``reviews/P1-RP5B-evidence/probe_rp5b_watch.py`` showed the deadline stop waiting too). F-m6:
``credit_delta`` refuses a malformed reference before its unlocked read (the reviewer's pin, mutant N3). Private
TEST authority roots and mocked clocks; no child process is started or signalled.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import unittest
from unittest import mock

from _queue_credit_fixture import CreditCase
from studio import native_budget_clock as clock
from studio.native_budget_clock import allocation_remaining, uncredited_remaining
from studio.production import process_watch
from test_queue_credit_aborts import GRACE, WatchCase

LATER = 10_000.0                         # seconds past the fixture's clocks: the batch deadline is long gone


def past_deadline() -> tuple:
    """Both clocks ``LATER`` seconds on, as context managers."""
    return (mock.patch.object(clock.time, 'time', lambda: 1_800_000_000.0 + LATER),
            mock.patch.object(clock, 'continuous_now', lambda: 5_000.0 + LATER))


class DeadlineDuringGraceTests(WatchCase):
    """A batch deadline long past is stopped at once, on readable credit and inside a credit grace alike."""

    def test_the_deadline_stops_the_child_inside_a_credit_grace(self) -> None:
        wall, continuous = past_deadline()
        with wall, continuous:
            self.now = 2.0
            self.assertEqual(process_watch._reason(self.watch, self.stops),
                             (process_watch.DEADLINE, 'the export ran past its batch deadline'))
            self.put(self.credit_record(10.0))                     # the authority rolled back: a credit error
            for now in (4.0, 4.0 + GRACE - 0.5, 4.0 + GRACE + 0.5):
                self.now = now
                self.assertEqual(process_watch._reason(self.watch, self.stops)[0], process_watch.DEADLINE)

    def test_inside_the_deadline_the_grace_still_runs(self) -> None:
        self.put(self.credit_record(10.0))
        for now in (1.0, 1.0 + GRACE):
            self.now = now
            self.assertIsNone(process_watch._reason(self.watch, self.stops))
        self.now = 1.5 + GRACE
        self.assertEqual(process_watch._reason(self.watch, self.stops)[0], 'capacity-credit-regressed')

    def test_the_uncredited_remaining_never_exceeds_the_credited(self) -> None:
        self.assertLessEqual(uncredited_remaining(self.grant), allocation_remaining(self.grant))
        self.assertEqual(allocation_remaining(self.grant) - uncredited_remaining(self.grant), 30.0)


class ReferenceTests(CreditCase):
    """F-m6 (N3): a malformed reference is refused, never read."""

    def test_a_negative_at_grant_is_refused(self) -> None:
        self.grant = self.bind(self.credit_record(40.0), 'A')
        self.grant['capacityCredit']['atGrant'] = -100.0
        with self.assertRaisesRegex(ValueError, 'Malformed capacity-credit allocation reference'):
            self.delta()


if __name__ == '__main__':
    unittest.main()
