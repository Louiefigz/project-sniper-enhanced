"""House-style selection is retired across planner and advice boundaries."""
from __future__ import annotations

import unittest

from graphics.form_allocation import assess_profile_form_reuse, build_form_allocation
from graphics.style_profiles import FACE_BRIDGE_PROFILE, form_contract, forms_for_shape, profile
from graphics.visual_source_policy import require_plan_sources
from graphics_style_advisor import recommend_style
from planner import graphics_planner_face_bridge as face_bridge
from planner import graphics_planner_style as styles
from planner.graphics_planner_longform import resolve_style


class RetiredFaceBridgeTests(unittest.TestCase):
    """An old profile, empty preset, or dense footage cannot restore a house style."""

    def test_saved_style_is_rejected_with_or_without_its_old_profile(self) -> None:
        for mode in ("short", "longform"):
            for extra in ({}, {"visualProfile": FACE_BRIDGE_PROFILE}, {"visualProfile": ""}):
                plan = {"target": {"mode": mode, "graphicsStyle": "face-bridge", **extra}}
                with self.subTest(plan=plan), self.assertRaisesRegex(ValueError, "retired"):
                    resolve_style(None, plan)

    def test_profile_readers_never_return_executable_house_contracts(self) -> None:
        self.assertIsNone(profile(FACE_BRIDGE_PROFILE))
        for shape in ("tool-list", "credibility", "evidence", "process", "comparison", "list", "scale"):
            self.assertEqual(forms_for_shape(FACE_BRIDGE_PROFILE, shape), [])
        for form in ("status-queue", "comparison-bars", "step-sequence", "hero-scoreboard"):
            self.assertIsNone(form_contract(FACE_BRIDGE_PROFILE, form))

    def test_direct_old_retarget_apis_fail_before_selecting_any_template(self) -> None:
        for api in (face_bridge.retarget, styles.retarget):
            with self.subTest(api=api), self.assertRaisesRegex(ValueError, "retired"):
                api([{"kind": "module-rail"}], object())

    def test_direct_profile_allocation_and_reuse_apis_fail(self) -> None:
        for name in (FACE_BRIDGE_PROFILE, "", "unknown"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "retired"):
                build_form_allocation([], selected_profile=name)
            with self.assertRaisesRegex(ValueError, "retired"):
                assess_profile_form_reuse([], [], name)

    def test_advice_cannot_infer_a_reference_style_from_face_or_density(self) -> None:
        for face in (None, [0.45, 0.2, 0.15, 0.3]):
            for count in (0, 2, 24):
                plan = {"target": {"graphicsStyle": "face-bridge", "visualProfile": FACE_BRIDGE_PROFILE,
                                   "style": "retired-creator"}, "faceBBoxNorm": face}
                advice = recommend_style(plan, [{"shape": "comparison"}] * count)
                target = {key: value for key, value in plan["target"].items()
                          if key not in advice["removeTargetFields"]}
                target.update(advice["recommendedTargetFields"])
                self.assertEqual(target["graphicsStyle"], "catalog-first")
                self.assertNotIn("visualProfile", target)
                self.assertNotIn("style", target)
                require_plan_sources({"target": target})


if __name__ == "__main__":
    unittest.main()
