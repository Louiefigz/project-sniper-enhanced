"""Retained cold file evidence across later phases, with TEST-only metadata faults.

No native worker, active reservation, source hash or current tool is invoked.
Only exact canonical fixture-owned raw records may be rewritten.
"""
from __future__ import annotations

from copy import copy, deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from _source_color_observation_read_fixture import ColdObservationFixture
from guided_source_color_observation_read import HeldColdSourceColorObservations, hold_source_color_observations


class ColdObservationHoldTests(unittest.TestCase):
    """Original same-read files and cutoff stay live without a second frame replay."""

    def setUp(self) -> None:
        """Original grade cutoff1120 is expired; the same caller read cutoff1300 is live."""
        self.now = [1200.0]
        timer = patch("time.monotonic", side_effect=lambda: self.now[0])
        timer.start()
        self.addCleanup(timer.stop)
        self.f = ColdObservationFixture()
        self.addCleanup(self.f.cleanup)

    def test_retained_check_does_not_replay_or_read_any_raw_bytes(self) -> None:
        """Later phases reuse finite metadata checks and the actual original read record."""
        held = hold_source_color_observations(self.f.section, self.f.read_context)
        self.assertEqual(held.record, self.f.section)
        self.assertIsNot(held.record, self.f.section)
        with patch("guided_source_color_observation_replay._lines", side_effect=AssertionError("second replay")), \
                patch("guided_source_color_observation_files.read_bytes", side_effect=AssertionError("second read")):
            held.check()
            held.check()
        self.assertFalse(held.record["gradeApplied"])

    def test_later_phase_same_byte_raw_frames_replacement_rejects(self) -> None:
        """A later base/A-V callback cannot change an earlier retained original record."""
        held = hold_source_color_observations(self.f.section, self.f.read_context)
        self.f.replace(Path(self.f.sections[0]["artifacts"]["frames"]["path"]))
        with self.assertRaisesRegex(RuntimeError, "metadata file"):
            held.check()

    def test_retained_guard_still_checks_same_read_cutoff_not_old_phase(self) -> None:
        """Expired historical work is allowed as history; expired actual read time is not."""
        held = hold_source_color_observations(self.f.section, self.f.read_context)
        self.now[0] = 1299.0
        held.check()
        self.now[0] = 1300.0
        with self.assertRaises(RuntimeError):
            held.check()

    def test_copied_holder_and_changed_returned_data_cannot_pass(self) -> None:
        """Only the actual read object retains its files; no copy becomes a capability."""
        held = hold_source_color_observations(self.f.section, self.f.read_context)
        with self.assertRaisesRegex(RuntimeError, "actual original read"):
            HeldColdSourceColorObservations.check(copy(held))
        held.record["sources"][0]["records"]["width"] = 32.0
        with self.assertRaisesRegex(RuntimeError, "parsed metadata"):
            held.check()

    def test_last_guard_cannot_replace_detached_record_with_equal_copy(self) -> None:
        """Check original returned identity after the final arbitrary caller callback."""
        held = hold_source_color_observations(self.f.section, self.f.read_context)
        self.f.guard.side_effect = lambda: object.__setattr__(held, "record", deepcopy(held.record))
        with self.assertRaisesRegex(RuntimeError, "original returned record"):
            held.check()

    def test_callback_free_tail_checks_original_files_and_holder_identity(self) -> None:
        """Final outer sweeps cannot call the old owner or accept forged/mutated holders."""
        held = hold_source_color_observations(self.f.section, self.f.read_context)
        self.f.guard.reset_mock()
        self.f.guard.side_effect = AssertionError("callback-free tail called external guard")
        held.assert_metadata()
        self.f.guard.assert_not_called()
        with self.assertRaisesRegex(RuntimeError, "actual original read"):
            HeldColdSourceColorObservations.assert_metadata(copy(held))
        self.f.replace(Path(self.f.sections[1]["artifacts"]["frames"]["path"]))
        with self.assertRaisesRegex(RuntimeError, "metadata file"):
            held.assert_metadata()


if __name__ == "__main__":
    unittest.main()
