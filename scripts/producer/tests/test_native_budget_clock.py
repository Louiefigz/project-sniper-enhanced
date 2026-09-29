"""The batch clock never grants time back: sleep, wall rollback and reboot are charged."""
from __future__ import annotations

import unittest

from _budget_fixture import FakeClock, fake_clock
from studio import native_budget_clock as clock


class BudgetClockTests(unittest.TestCase):
    """Elapsed time is the larger of wall and boot-continuous deltas, floored by the anchor."""

    def test_elapsed_advances_with_both_clocks(self) -> None:
        with fake_clock(FakeClock()) as now:
            anchor = clock.start_anchor()
            now.advance(90)
            self.assertAlmostEqual(clock.observe(anchor, anchor.epoch).elapsed, 90)

    def test_wall_clock_rollback_does_not_grant_time(self) -> None:
        with fake_clock(FakeClock()) as now:
            anchor = clock.start_anchor()
            now.advance(600, wall=-3600)  # clock set back an hour while 10 minutes passed
            self.assertAlmostEqual(clock.observe(anchor, anchor.epoch).elapsed, 600)

    def test_sleep_counts_through_the_continuous_clock(self) -> None:
        with fake_clock(FakeClock()) as now:
            anchor = clock.start_anchor()
            now.advance(1200, wall=0)  # wall frozen/rolled, continuous clock kept counting in sleep
            self.assertAlmostEqual(clock.observe(anchor, anchor.epoch).elapsed, 1200)

    def test_reboot_keeps_high_water_and_charges_wall_downtime(self) -> None:
        with fake_clock(FakeClock()) as now:
            start = clock.start_anchor()
            now.advance(1000)
            anchor = clock.observe(start, start.epoch)
            now.reboot(downtime=300)
            after = clock.observe(anchor, start.epoch)
            self.assertAlmostEqual(after.elapsed, 1300)
            now.wall -= 5000  # and a rollback after reboot still cannot go below the high-water mark
            self.assertAlmostEqual(clock.observe(after, start.epoch).elapsed, 1300)

    def test_wall_behind_the_last_observation_after_reboot_fails_closed(self) -> None:
        with fake_clock(FakeClock()) as now:
            start = clock.start_anchor()
            now.advance(1000)
            anchor = clock.observe(start, start.epoch)
            now.reboot(downtime=-2000)  # the wall clock went backwards across the restart
            with self.assertRaises(clock.BudgetClockError):
                clock.observe(anchor, start.epoch)

    def test_allocation_expires_on_either_clock(self) -> None:
        with fake_clock(FakeClock()) as now:
            grant = clock.allocation(clock.start_anchor(), 100, 10)
            request = {'productionBudget': {'allocation': grant}}
            now.advance(40, wall=0)
            self.assertAlmostEqual(clock.remaining_seconds(request), 60)
            now.advance(0, wall=90)
            self.assertAlmostEqual(clock.remaining_seconds(request), 10)

    def test_the_export_watchdog_deadline_ignores_a_wall_rollback(self) -> None:
        """The watchdog stops an export at its grant even when the wall clock is set back (unit A4)."""
        import time
        from pathlib import Path
        from types import SimpleNamespace
        from studio.production import process_watch
        stops = SimpleNamespace(reason=None)
        with fake_clock(FakeClock()) as now:
            grant = clock.allocation(clock.start_anchor(), 100, 45)
            watch = process_watch.ExportWatch(None, Path('/nonexistent'), grant, time.monotonic(), time.time())
            now.advance(60, wall=-3600)           # an hour back on the wall while a minute passed
            self.assertIsNone(process_watch._reason(watch, stops))
            now.advance(41, wall=0)
            self.assertEqual(process_watch._reason(watch, stops)[0], process_watch.DEADLINE)

    def test_other_boot_has_no_remaining_allocation(self) -> None:
        with fake_clock(FakeClock()) as now:
            request = {'productionBudget': {'allocation': clock.allocation(clock.start_anchor(), 100, 10)}}
            now.reboot(downtime=1)
            self.assertLessEqual(clock.remaining_seconds(request), 0)

    def test_stage_allowance_is_bounded_and_exhausts(self) -> None:
        with fake_clock(FakeClock()) as now:
            request = {'productionBudget': {'allocation': clock.allocation(clock.start_anchor(), 300, 45)}}
            self.assertEqual(clock.stage_allowance(request, 600), 255)
            self.assertEqual(clock.stage_allowance(request, 60), 60)
            now.advance(255)
            with self.assertRaises(clock.BudgetExhausted):
                clock.stage_allowance(request, 600)

    def test_unbudgeted_requests_keep_their_stage_limit(self) -> None:
        self.assertIsNone(clock.remaining_seconds({}))
        self.assertEqual(clock.stage_allowance({}, 600), 600)

    def test_malformed_anchor_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            clock.ClockAnchor.from_record({'boot': 'x', 'continuous': float('nan'), 'epoch': 1, 'elapsed': 0})
        with self.assertRaises(ValueError):
            clock.ClockAnchor.from_record({'boot': 'x', 'continuous': 1, 'epoch': 1, 'elapsed': -1})


if __name__ == '__main__':
    unittest.main()
