"""Original sampled body watermark faults; virtual clocks and inert TEMP metadata only."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import guided_source_color_read_entry as entry
import test_source_color_body_read_clock as existing
from guided_body_execution import BodyExecutionClock
from guided_source_color_read_clock import source_color_read_remaining


class BodyReadClockLifetimeFaultTests(unittest.TestCase):
    """A later stat must not erase the already sampled body wall watermark."""

    def setUp(self) -> None:
        """Reuse only the explicit virtual-clock/native-stub metadata fixture."""
        self.fixture = existing.BodyReadClockTests("test_original_clock_cannot_be_substituted_or_extended")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.sampled = []

    def _rollback(self) -> None:
        """Change memory only, after actual remaining has sampled the later wall."""
        self.sampled.append(self.fixture.clock.previous_wall_ms)
        self.fixture.wall[0] -= 500
        self.fixture.clock.previous_wall_ms -= 500

    def test_entry_guard_retains_wall_sample_before_original_filesystem_sweep(self) -> None:
        """Previously accepted2000500 after actually observing2001000 in remaining."""
        f = self.fixture
        f.wall[0] += 1000
        real = entry._directory_states
        armed = [True]

        def states(paths: tuple) -> tuple:
            """Finish the real metadata read before the sole TEST memory fault."""
            value = real(paths)
            if armed[0]:
                armed[0] = False
                self._rollback()
            return value

        with patch.object(entry, "_directory_states", side_effect=states):
            with self.assertRaisesRegex(RuntimeError, "watermark"):
                entry.assert_source_color_read_entry(f.f.entry, f.clock)
        self.assertEqual(self.sampled, [2_001_000])

    def test_capture_retains_each_original_wall_sample_before_path_stat(self) -> None:
        """Initial capture cannot adopt the reduced watermark as its first baseline."""
        f = self.fixture
        f.wall[0] += 1000
        real = Path.lstat
        armed = [True]

        def stat(path: Path, *args: object, **kwargs: object) -> object:
            """Only the original inert input's first completed stat changes memory."""
            value = real(path, *args, **kwargs)
            if armed[0] and path == f.f.inputs.path:
                armed[0] = False
                self._rollback()
            return value

        with patch.object(Path, "lstat", stat):
            with self.assertRaisesRegex(RuntimeError, "watermark"):
                entry.capture_source_color_read_entry((f.f.inputs.path, f.f.output),
                    f.f.authority, f.f.transport, f.clock)
        self.assertEqual(self.sampled, [2_001_000])

    def test_exact_clock_type_rejects_subclass_without_calling_its_override(self) -> None:
        """A matching-looking clock is not the supplied exact body clock class."""
        class OtherClock(BodyExecutionClock):
            """TEST override must never become the timing implementation."""

            def remaining(self) -> float:
                """Fail if a custom timing callback is actually dispatched."""
                raise AssertionError("TEST subclass callback ran")

        with self.assertRaisesRegex(RuntimeError, "exact original clock"):
            source_color_read_remaining(OtherClock(self.fixture.clock.end))

    def test_replacement_event_list_cannot_reconstruct_original_clock(self) -> None:
        """Even equal events must retain the original event-list object."""
        f = self.fixture
        f.clock.events = list(f.clock.events)
        with self.assertRaisesRegex(RuntimeError, "entry clock"):
            entry.assert_source_color_read_entry(f.f.entry, f.clock)


if __name__ == "__main__":
    unittest.main()
