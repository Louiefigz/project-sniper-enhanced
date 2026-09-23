"""Old gauge selection cannot produce a house-template candidate."""
from __future__ import annotations

import unittest
from planner import graphics_planner_gauge as gauge
from planner.graphics_planner_longform import Ctx


class GaugeRetirementTests(unittest.TestCase):
    def test_numeric_climb_does_not_restore_gauge_in_either_mode(self) -> None:
        words = [{"word": value, "start": index, "end": index + 0.5}
                 for index, value in enumerate(("1k", "10k", "100k", "1M"))]
        for mode, aspect in (("short", "9:16"), ("longform", "16:9")):
            context = Ctx(words, mode, aspect, lambda _: ("talking-head", None), 12.0)
            with self.assertRaisesRegex(ValueError, "retired"):
                gauge.gauge_beats(context)

    def test_empty_request_still_provides_explicit_migration_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "HyperFrames catalog"):
            gauge.gauge_beats(None)

    def test_saved_gauge_cannot_be_filled_or_presented_for_selection(self) -> None:
        beat = {"kind": "widget-gauge", "marks": [{"atSec": 0}, {"atSec": 1}]}
        with self.assertRaisesRegex(ValueError, "retired"):
            gauge.fill_gauge_spec(beat, "TEST", [{"markIndex": 0, "pos": 0.1}, {"markIndex": 1, "pos": 1}])
        with self.assertRaisesRegex(ValueError, "retired"):
            gauge.table_lines([beat])


if __name__ == "__main__":
    unittest.main()
