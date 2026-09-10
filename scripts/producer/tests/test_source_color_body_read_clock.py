"""Borrowed body clock tests with actual TEMP metadata, no native work or approval."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from _source_color_read_scope_fixture import ColdReadScopeFixture
from guided_body_execution import body_clock
from guided_opening_execution import OpeningExecutionClock
from guided_source_color_read_clock import source_color_read_remaining
from guided_source_color_read_entry import capture_source_color_read_entry, assert_source_color_read_entry


class BodyReadClockTests(unittest.TestCase):
    """Original wall/cutoff/entry identity survives body source metadata replay."""

    def setUp(self) -> None:
        """Use explicit TEST clocks and original inert controls before scope capture."""
        self.mono, self.wall = [1000.0], [2_000_000]
        for timer in (patch("time.monotonic", side_effect=lambda: self.mono[0]),
                      patch("time.time_ns", side_effect=lambda: self.wall[0] * 1_000_000)):
            timer.start()
            self.addCleanup(timer.stop)
        self.f = ColdReadScopeFixture()
        self.addCleanup(self.f.cleanup)
        self.clock = body_clock(300)
        self.clock.bind_wall(2_200_000, 2_000_000)
        self.f.clock = self.clock
        self.f.entry = capture_source_color_read_entry((self.f.inputs.path, self.f.output),
            self.f.authority, self.f.transport, self.clock)
        self.leaves = self.f.leaves()
        self.addCleanup(self.leaves.close)

    def test_real_scope_borrows_original_body_clock_and_observation_replay(self) -> None:
        """Actual bounded observation replay adds no clock and grants no consumption proof."""
        scope = self.f.scope()
        self.assertIs(scope.controls[2], self.clock)
        scope.replay_observations()
        self.assertEqual(scope.observations.record, self.f.section)
        self.wall[0] += 50_000
        self.assertEqual(scope.runtime.remaining(), 150)
        self.assertEqual(self.clock.end, 1200)
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            scope.final_check()

    def test_wall_expiry_rejects_while_monotonic_budget_remains(self) -> None:
        """The old base-class remaining call would incorrectly allow this read."""
        scope = self.f.scope()
        self.wall[0] = 2_200_000
        with self.assertRaisesRegex(RuntimeError, "wall clock"):
            scope.assert_metadata()

    def test_original_clock_cannot_be_substituted_or_extended(self) -> None:
        """Matching fields in another clock and a changed cutoff both reject."""
        other = body_clock(300)
        other.bind_wall(2_200_000, 2_000_000)
        with self.assertRaisesRegex(RuntimeError, "entry clock"):
            assert_source_color_read_entry(self.f.entry, other)
        self.clock.end += 1
        with self.assertRaisesRegex(RuntimeError, "entry clock"):
            assert_source_color_read_entry(self.f.entry, self.clock)

    def test_wall_bound_cannot_expand_and_watermark_cannot_move_back(self) -> None:
        """Moving either side of the original body wall interval cannot buy time."""
        self.clock.wall_deadline_ms += 1
        with self.assertRaisesRegex(RuntimeError, "entry clock"):
            assert_source_color_read_entry(self.f.entry, self.clock)
        self.clock.wall_deadline_ms -= 1
        self.wall[0] += 1000
        assert_source_color_read_entry(self.f.entry, self.clock)
        self.clock.previous_wall_ms -= 1
        with self.assertRaisesRegex(RuntimeError, "watermark"):
            assert_source_color_read_entry(self.f.entry, self.clock)

    def test_custom_remaining_or_unbound_body_clock_cannot_enter(self) -> None:
        """No caller-provided clock callback bypasses the original class implementation."""
        with self.assertRaisesRegex(RuntimeError, "clock fields"):
            source_color_read_remaining(body_clock(300))
        self.clock.remaining = lambda: 99999
        with self.assertRaisesRegex(RuntimeError, "clock fields"):
            source_color_read_remaining(self.clock)

    def test_original_opening_clock_remains_unchanged(self) -> None:
        """Legacy opening reads keep their separate monotonic-only contract."""
        self.assertEqual(source_color_read_remaining(OpeningExecutionClock(1100)), 100)
        self.mono[0] = 1100
        with self.assertRaisesRegex(RuntimeError, "deadline"):
            source_color_read_remaining(OpeningExecutionClock(1100))


if __name__ == "__main__":
    unittest.main()
