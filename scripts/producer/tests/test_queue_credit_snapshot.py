"""Credit reads never take the batch lock; bounded tolerance; named aborts (P1 Step B10, C9; MASTER-PLAN M-053).

Private TEST authority roots only (``_queue_credit_fixture``). The batch clocks are the fixture's, and the read
cache and tolerance run on a patched monotonic clock, so no test waits for them. The lock tests hold the batch's
kernel lock for real: ``lock_held_by_a_thread`` in this process, and in ``LockHolderChildTests`` the plan's
helper child (``sys.executable -c``). That class starts a child, so it runs at M-053's Verify, not in a prefab
lane (PARALLEL-LANES-WAVE2 W2-D2 does not list this module).
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import subprocess
import sys
import time
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest import mock

from _queue_credit_fixture import (
    BATCH, CLAIM, DAMAGE, GRANTED, TORN, CreditCase, clip_row, lock_held_by_a_thread,
)
from studio import native_budget_store as store
from studio.native_budget_clock import allocation_remaining
from studio.native_run_lifecycle import monitor_limits
from studio.production import process, process_watch, queue_credit
from studio.production.process import TaskClaim
from studio.production.queue_credit import CapacityCreditRegressed, CapacityCreditUnavailable

PRODUCER = Path(__file__).resolve().parents[1]
TOLERANCE = queue_credit.CREDIT_READ_TOLERANCE_SECONDS


class CreditReadTests(CreditCase):
    """``queue_authority.credit_delta`` through ``queue_credit.settled_credit``."""

    def test_credit_is_cached_for_one_second(self) -> None:
        """One record read serves every credit read for a second of monotonic time; the next one reads again."""
        self.assertEqual(queue_credit.CREDIT_CACHE_SECONDS, 1.0)
        self.put(self.credit_record(30.0))
        with mock.patch.object(queue_credit, 'read_private_file', wraps=queue_credit.read_private_file) as reads:
            self.assertEqual(self.delta(), 30.0)
            self.put(self.credit_record(60.0))
            for self.now in (0.5, 0.999):
                self.assertEqual(self.delta(), 30.0)
            self.assertEqual(reads.call_count, 1)
            self.now = 1.0
            self.assertEqual(self.delta(), 60.0)
            self.assertEqual(reads.call_count, 2)

    def test_unreadable_within_tolerance_keeps_the_last_value(self) -> None:
        """Every kind of unreadable authority holds the last credit read for the whole tolerance, its boundary
        included; a good read ends the run of failures; failures before any read give the grant's own credit."""
        for kind, damage in DAMAGE.items():
            with self.subTest(kind):
                self.assert_held(damage)
        queue_credit._CREDIT.clear()
        self.put(self.credit_record(30.0))
        self.path.write_bytes(TORN)
        self.now = 50.0
        self.assertEqual(self.delta(), 0.0)
        self.assertEqual(queue_credit.settled_credit({**self.grant['capacityCredit'], 'atGrant': 10.0}), 10.0)

    def assert_held(self, damage: Callable[[Path], None]) -> None:
        """Credit 30 read at 0, damaged from 1 (the first failed read) and held through 1 + tolerance; a repair read
        at 17 (credit 45) starts a new run of failures at 18."""
        queue_credit._CREDIT.clear()
        self.now = 0.0
        self.put(self.credit_record(30.0))
        self.assertEqual(self.delta(), 30.0)
        damage(self.path)
        for self.now in (1.0, 8.0, 1.0 + TOLERANCE):
            self.assertEqual(self.delta(), 30.0)
        self.put(self.credit_record(45.0))
        self.now = 17.0
        self.assertEqual(self.delta(), 45.0)
        damage(self.path)
        for self.now in (18.0, 18.0 + TOLERANCE):
            self.assertEqual(self.delta(), 45.0)

    def test_unreadable_beyond_tolerance_aborts_by_name(self) -> None:
        """Past the tolerance the monitor stops the render by name: ``monitor_limits`` returns True with
        ``capacity-credit-unavailable``; the tolerance is the watchdog's grace past a launch grant."""
        self.assertEqual(TOLERANCE, process.DEADLINE_GRACE_SECONDS)
        self.put(self.credit_record(30.0))
        self.assertEqual(self.delta(), 30.0)
        self.path.write_bytes(TORN)
        self.now = 1.0
        self.assertEqual(self.delta(), 30.0)
        self.now = 1.5 + TOLERANCE
        owner = self.owner()
        self.assertTrue(monitor_limits(owner))
        self.assertEqual(owner.result['failureCategory'], 'capacity-credit-unavailable')
        self.assertEqual(owner.abort_reason, 'Short A capacity credit has been unreadable for 15.5s')
        with self.assertRaises(CapacityCreditUnavailable):
            allocation_remaining(self.grant)

    def test_decreasing_credit_aborts_by_name(self) -> None:
        """Credit lower than the last credit read (a rolled-back or edited authority) stops the render at once with
        ``capacity-credit-regressed``; it is never held as a tolerated failure."""
        self.put(self.credit_record(30.0))
        self.assertEqual(self.delta(), 30.0)
        self.put(self.credit_record(20.0))
        self.now = 1.0
        owner = self.owner()
        self.assertTrue(monitor_limits(owner))
        self.assertEqual(owner.result['failureCategory'], 'capacity-credit-regressed')
        self.assertEqual(owner.abort_reason, 'Short A capacity credit went down from 30.0s to 20.0s; the authority '
                                             'was rolled back or edited')
        self.now = 2.0
        with self.assertRaises(CapacityCreditRegressed):
            self.delta()

    def test_inactive_batch_gives_no_credit(self) -> None:
        """A draining or closed batch, a clip with no clock and a Long give no credit (unchanged semantics); a batch
        that stops being active after credit was read is not a regression."""
        self.put(self.credit_record(30.0))
        self.assertEqual(self.delta(), 30.0)
        for self.now, status in ((1.0, 'draining'), (2.0, 'closed')):
            self.put(self.credit_record(30.0, status))
            self.assertEqual(self.delta(), 0.0)
        no_clock, long = self.credit_record(30.0), self.credit_record(30.0)
        del clip_row(no_clock)['capacityClock']
        clip_row(long)['output'] = {'format': 'long'}
        for self.now, record in ((3.0, no_clock), (4.0, long)):
            self.put(record)
            self.assertEqual(self.delta(), 0.0)
        self.put(self.credit_record(30.0))
        self.now = 5.0
        self.assertEqual(self.delta(), 30.0)

    def test_credit_read_does_not_wait_for_a_lock_held_in_this_process(self) -> None:
        """The in-process companion of the child test: another thread holds the batch lock, and the credit read
        through ``allocation_remaining`` still returns at once with the credit."""
        self.put(self.credit_record(30.0))
        with lock_held_by_a_thread(self.root):
            began = time.monotonic()
            remaining = allocation_remaining(self.grant)
            waited = time.monotonic() - began
        self.assertLess(waited, 0.5)
        self.assertEqual(remaining, GRANTED + 30.0)


class WatchdogTaskRowTests(CreditCase):
    """``process_watch._task_row`` through ``queue_credit.task_row``."""

    def setUp(self) -> None:
        """The watchdog reads this test's private root."""
        super().setUp()
        self.enterContext(mock.patch.object(store, 'default_root', return_value=self.root))

    def test_watchdog_reads_its_task_row_without_the_lock(self) -> None:
        """Another thread holds the batch lock; the watchdog's claim and cancel read returns the row at once."""
        with lock_held_by_a_thread(self.root):
            began = time.monotonic()
            row = process_watch._task_row(CLAIM)
            waited = time.monotonic() - began
        self.assertLess(waited, 0.5)
        self.assertEqual(row, self.record['production']['tasks']['check-1'])

    def test_watchdog_task_row_has_the_same_tolerance(self) -> None:
        """A failed read keeps the last row for the tolerance; past it the watchdog gets None (its existing stop).
        Before any row is read the answer is None at once, as before. A task the readable record lacks is an answer
        (None), never a failed read, so it never becomes 'unreadable' however long it stays absent."""
        row = process_watch._task_row(CLAIM)
        self.path.write_bytes(TORN)
        for self.now in (5.0, 5.0 + TOLERANCE):
            self.assertEqual(process_watch._task_row(CLAIM), row)
        self.now = 5.5 + TOLERANCE
        self.assertIsNone(process_watch._task_row(CLAIM))
        with self.assertRaisesRegex(CapacityCreditUnavailable, rf'^Task check-1 of batch {BATCH} has been unreadable '
                                                               r'for 15\.5s$'):
            queue_credit.task_row(self.root, BATCH, 'check-1')
        queue_credit._TASKS.clear()
        self.assertIsNone(process_watch._task_row(CLAIM))
        self.put(self.record)
        self.assertIsNone(process_watch._task_row(TaskClaim(BATCH, 'check-2', 0, 'TEST-token', 'e' * 64)))
        for self.now in (21.0, 21.0 + 2 * TOLERANCE):
            self.assertIsNone(queue_credit.task_row(self.root, BATCH, 'check-2'))
        self.assertEqual(process_watch._task_row(CLAIM), row)


class LockHolderChildTests(CreditCase):
    """P1 B10's lock test with its helper child (deferred to M-053's Verify: W2-D2 lists no child here)."""

    def test_credit_read_does_not_wait_for_the_batch_lock(self) -> None:
        """A child holds ``locked_batch`` for 4 s on the private root; ``allocation_remaining`` returns in < 0.5 s."""
        self.put(self.credit_record(30.0))
        script = ('import sys, time; from pathlib import Path; sys.path[:0] = [sys.argv[1]]\n'
                  'from studio.native_budget_store import locked_batch\n'
                  'with locked_batch(Path(sys.argv[2]), sys.argv[3]):\n'
                  '    print("held", flush=True); time.sleep(4)\n')
        holder = subprocess.Popen([sys.executable, '-c', script, str(PRODUCER), str(self.root), BATCH],
                                  stdout=subprocess.PIPE, text=True)
        self.addCleanup(holder.stdout.close)
        self.addCleanup(holder.wait)
        self.addCleanup(holder.kill)
        self.assertEqual(holder.stdout.readline().strip(), 'held')
        began = time.monotonic()
        remaining = allocation_remaining(self.grant)
        self.assertLess(time.monotonic() - began, 0.5)
        self.assertEqual(remaining, GRANTED + 30.0)


if __name__ == '__main__':
    unittest.main()
