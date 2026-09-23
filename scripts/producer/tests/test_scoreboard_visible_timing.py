"""Actual template schedule parity and short-beat visible-completeness tests."""
from __future__ import annotations

import copy
import unittest
from pathlib import Path
from unittest import mock

from _common import pl  # noqa: F401
from graphics import template_visual_contract as visual
from graphics.template_contract import entry_errors

ROOT = Path(__file__).resolve().parents[3]
SCOREBOARD = ROOT / "templates/motion/compositions/module-scoreboard.html"
SPEC = {"eyebrow": "Every hour", "contextChips": "footage|viewer|guardrails",
        "heroValue": "1,000", "heroLabel": "hours of footage",
        "tiles": "survive~the tricks|lose~a viewer|guardrails~matter",
        "stripChips": "", "limitLabel": "LIMIT",
        "limitText": "Every hour of that can lose a viewer", "moduleLands": "", "exit": "hold"}


def entry(spec: dict, duration: float) -> dict:
    """One TEST-only card, not a creator plan or editorial approval."""
    return {"kind": "module-scoreboard", "outStart": 0, "outEnd": duration, "spec": spec}


# Inert historical numeric constants; no retired JavaScript is executed.
TEST_TIMING = {'LAND_DEFAULT_START_S': 0.2, 'LAND_DEFAULT_GAP_S': 0.9, 'CTX_STAGGER_S': 0.1, 'TILE_STAGGER_S': 0.1, 'CHIP_SWEEP_S': 0.085, 'TEXT_RAMP_S': 0.2, 'EYEBROW_LEAD_S': 0.25, 'EXIT_BLUR_S': 0.15}


class ScoreboardTimingTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(visual, "_scoreboard_tokens", return_value=TEST_TIMING)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_actual_failed_ui_card_rejects_missing_late_modules(self) -> None:
        issues = visual.visual_entry_errors(entry(SPEC, 1.8018))
        self.assertTrue(any("4.35s" in issue and "last reveal 2.90s" in issue for issue in issues), issues)
        self.assertTrue(entry_errors(entry(SPEC, 1.8018)))
        self.assertEqual(visual.visual_entry_errors(entry(SPEC, 4.35)), [])

    def test_simple_number_keeps_a_fast_short_beat_without_dropping_copy(self) -> None:
        spec = {"heroValue": "1,000", "heroLabel": "hours", "moduleLands": "", "limitLabel": "LIMIT"}
        self.assertEqual(visual.visual_entry_errors(entry(spec, 1.8)), [])
        self.assertTrue(visual.visual_entry_errors(entry(spec, 1.6)))

    def test_retired_source_is_absent_and_current_contract_rejects(self) -> None:
        self.assertFalse(SCOREBOARD.exists())
        for spec in (SPEC, {"heroValue": "100"}):
            self.assertTrue(any("retired" in issue for issue in entry_errors(entry(spec, 10))))

    def test_exit_has_its_own_runway_after_readable_dwell(self) -> None:
        spec = {**SPEC, "exit": "blur-recede"}
        self.assertTrue(visual.visual_entry_errors(entry(spec, 4.35)))
        self.assertEqual(visual.visual_entry_errors(entry(spec, 4.5)), [])

    def test_bad_or_incomplete_schedules_fail_closed(self) -> None:
        for lands in ([0], [0, 1, 1, 2], [0, 1, 2, float("inf")], [False, 1, 2, 3],
                      "0|1|2|bad", "0|1|2|3tail", "-1|0|1|2", "3|2|1|0", "0|1|2|3_0e-3", "0|1|2|3e-٣"):
            with self.subTest(lands=lands):
                self.assertTrue(visual.visual_entry_errors(entry({**SPEC, "moduleLands": lands}, 10)))

    def test_missing_or_changed_source_timing_is_not_assumed_safe(self) -> None:
        with mock.patch.object(visual, "_scoreboard_tokens", side_effect=ValueError("changed source")):
            self.assertTrue(visual.visual_entry_errors(entry(SPEC, 10)))
        self.assertTrue(visual.visual_entry_errors(entry({}, 10)))

    def test_retained_timing_default_and_custom_schedule_stay_distinct(self) -> None:
        baseline = visual.scoreboard_timing(SPEC)
        later = visual.scoreboard_timing({**SPEC, "moduleLands": "0|0.5|1.2|3.5"})
        self.assertGreater(later[0], baseline[0])

    def test_validation_does_not_retime_or_remove_content(self) -> None:
        before = copy.deepcopy(SPEC)
        visual.visual_entry_errors(entry(SPEC, 1.8018))
        self.assertEqual(SPEC, before)


if __name__ == "__main__":
    unittest.main()
