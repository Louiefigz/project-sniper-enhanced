"""Catalog-first hook routing never requires or revives a retired title card."""
from __future__ import annotations

import copy
import unittest
from plan_lint import Report
from plan_lint_overlays import check_title_cards
from graphics.visual_source_policy import require_plan_sources


class ShortHookIntentTests(unittest.TestCase):
    """Hook quality is reviewed in its native project; legacy cards always refuse."""

    def errors(self, plan: dict) -> list[str]:
        """Read-only call to the actual compatibility gate."""
        before, report = copy.deepcopy(plan), Report()
        check_title_cards(plan, {}, 20.0, report)
        self.assertEqual(plan, before)
        return report.errors

    def test_no_scope_requires_a_removed_house_card(self) -> None:
        for scope in ("trim", "light", "produced", "full"):
            for mode in ("short", "longform"):
                plan = {"target": {"mode": mode, "scope": scope}, "titleCards": []}
                self.assertEqual(self.errors(plan), [])

    def test_valid_looking_legacy_card_cannot_reenter_by_scope_or_lane(self) -> None:
        for scope in ("trim", "light", "produced", "full"):
            for lane in ("auto", "off", "operator"):
                plan = {"target": {"mode": "short", "scope": scope, "lanes": {"graphics": lane}},
                        "titleCards": [{"outStart": 0, "outEnd": 2.5, "text": "TEST hook", "style": "hook"}]}
                self.assertIn("retired", " ".join(self.errors(plan)))
                with self.assertRaisesRegex(ValueError, "retired"):
                    require_plan_sources(plan)

    def test_old_style_cannot_invent_a_title_card_exception(self) -> None:
        for style in ("restrained", "punch"):
            with self.assertRaisesRegex(ValueError, "retired"):
                require_plan_sources({"target": {"style": style}, "titleCards": []})


if __name__ == "__main__":
    unittest.main()
