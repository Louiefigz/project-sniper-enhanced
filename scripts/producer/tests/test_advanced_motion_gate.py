"""Continuous tracking and animated PIP remain explicitly unreleased."""
from __future__ import annotations

import unittest

from _common import MANIFEST, good_plan
import plan_lint
from planner.advanced_motion_gate import advanced_motion_release_status

_FIXTURES = (
    "no-face", "multiple-face", "face-exit", "occluded-face",
    "screen-share", "shot-boundary", "fast-motion", "safe-zone",
    "canvas-9x16-30000x1001", "canvas-16x9-24", "manual-override",
)


class AdvancedMotionGateTests(unittest.TestCase):
    def test_complete_passing_matrix_is_the_only_release_shape(self) -> None:
        evidence = [{
            "fixtureId": name, "trackingPassed": True,
            "animatedPipPassed": True,
        } for name in _FIXTURES]
        self.assertTrue(advanced_motion_release_status(evidence)["released"])
        evidence[-1]["trackingPassed"] = False
        verdict = advanced_motion_release_status(evidence)
        self.assertFalse(verdict["released"])
        self.assertEqual(verdict["failedFixtures"], ["manual-override"])

    def test_missing_face_and_canvas_cases_stay_blocked(self) -> None:
        verdict = advanced_motion_release_status([])
        self.assertFalse(verdict["released"])
        self.assertEqual(verdict["requiredFixtureCount"], len(_FIXTURES))
        self.assertIn("no-face", verdict["missingFixtures"])
        self.assertIn("canvas-9x16-30000x1001", verdict["missingFixtures"])

    def test_plan_rejects_continuous_tracking(self) -> None:
        plan = good_plan()
        plan.setdefault("reframe", {})["continuousTracking"] = True
        errors = plan_lint.lint(plan, MANIFEST).errors
        self.assertTrue(any("continuousTracking is unsupported"
                            in error for error in errors), errors)

    def test_plan_rejects_reserved_presenter_root_even_when_false(self) -> None:
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                plan = good_plan()
                plan["presenter"] = {"animatedPip": enabled}
                errors = plan_lint.lint(plan, MANIFEST).errors
                self.assertEqual(errors, [
                    "plan contains unreleased renderer fields: ['presenter']"])

    def test_explicit_false_preserves_static_manual_reframe(self) -> None:
        plan = good_plan()
        plan["reframe"]["continuousTracking"] = False
        self.assertEqual(plan_lint.lint(plan, MANIFEST).errors, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
