"""Pure hook-intent matrix; no source, renderer, provider, or approval evidence."""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plan_lint_overlays import check_title_cards
from plan_lint import Report


def plan(scope: str, **target_fields: object) -> dict:
    """Create only target/card fields consumed by the pure overlay lint."""
    return {"target": {"mode": "short", "scope": scope, **target_fields},
            "titleCards": []}


def card(**fields: object) -> dict:
    """Return a valid legacy frame-one hook for validation-only tests."""
    return {"outStart": 0.0, "outEnd": 2.5, "style": "hook",
            "text": "A clear thesis", **fields}


class ShortHookIntentTests(unittest.TestCase):
    """Only missing-hook ownership changes; authored card checks stay strict."""

    def errors(self, value: dict) -> list[str]:
        """Run the actual gate and require input immutability."""
        before = copy.deepcopy(value)
        report = Report()
        check_title_cards(value, {}, 20.0, report)
        self.assertEqual(value, before)
        return report.errors

    def test_generic_light_and_trim_do_not_require_hook(self) -> None:
        """Graphics-inactive scopes do not invent an extra requested title."""
        for scope in ("light", "trim"):
            with self.subTest(scope=scope):
                self.assertEqual(self.errors(plan(scope)), [])

    def test_graphics_auto_override_cannot_enable_inactive_scope(self) -> None:
        """The existing resolved-lane semantics, not the spelling auto, win."""
        for scope in ("light", "trim"):
            with self.subTest(scope=scope):
                self.assertEqual(self.errors(plan(scope, lanes={"graphics": "auto"})), [])

    def test_produced_and_full_auto_still_require_hook(self) -> None:
        """Both default and explicit active auto keep the full obligation."""
        for scope in ("produced", "full"):
            for lanes in ({}, {"graphics": "auto"}):
                self.assertIn("style='hook'", " ".join(self.errors(plan(scope, lanes=lanes))))

    def test_explicit_nonowned_graphics_skip_only_missing_hook(self) -> None:
        """Off, operator, and supplied assets do not require system artwork."""
        for scope in ("light", "produced", "full"):
            for value in ("off", "operator", ["operator-supplied"]):
                self.assertEqual(self.errors(plan(scope, lanes={"graphics": value})), [])

    def test_legacy_scope_default_keeps_produced_obligation(self) -> None:
        """Omitted scope retains the existing produced fallback."""
        value = plan("produced")
        del value["target"]["scope"]
        self.assertIn("style='hook'", " ".join(self.errors(value)))

    def test_valid_hook_satisfies_system_owned_graphics(self) -> None:
        """A real supplied legacy card still satisfies this metadata gate."""
        value = plan("produced")
        value["titleCards"] = [card()]
        self.assertEqual(self.errors(value), [])

    def test_generic_catalog_graphic_is_not_hook_equivalence(self) -> None:
        """Neither a row at zero nor a caller role label replaces a hook card."""
        value = plan("produced")
        value["graphicsTrack"] = [{"id": "TEST-only", "kind": "statement-card",
                                  "outStart": 0, "outEnd": 2.5, "role": "hook"}]
        self.assertIn("style='hook'", " ".join(self.errors(value)))

    def test_caleb_style_retains_named_light_thesis_hook(self) -> None:
        """The explicit style, not graphics scope default, names the base kit."""
        value = plan("light", style="caleb", pace="caleb", lanes={"motion": "off"})
        self.assertIn("style='hook'", " ".join(self.errors(value)))
        value["titleCards"] = [card()]
        self.assertEqual(self.errors(value), [])

    def test_pace_alone_does_not_infer_named_style(self) -> None:
        """A cadence selection is not a request for the complete Caleb style."""
        self.assertEqual(self.errors(plan("light", pace="caleb")), [])

    def test_caleb_explicit_graphics_off_is_conflict_even_with_card(self) -> None:
        """Do not silently waive style or add a title against explicit off."""
        value = plan("light", style="caleb", lanes={"graphics": "off"})
        self.assertIn("operator intent conflict", " ".join(self.errors(value)))
        value["titleCards"] = [card()]
        self.assertIn("operator intent conflict", " ".join(self.errors(value)))

    def test_caleb_trim_is_explicit_scope_conflict(self) -> None:
        """A selected style cannot force engagement artwork into trim scope."""
        self.assertIn("operator intent conflict",
                      " ".join(self.errors(plan("trim", style="caleb"))))

    def test_caleb_operator_hook_must_actually_be_supplied(self) -> None:
        """Operator-owned is not off, but cannot assert a nonexistent hook."""
        value = plan("light", style="caleb", lanes={"graphics": "operator"})
        self.assertIn("style='hook'", " ".join(self.errors(value)))
        value["titleCards"] = [card()]
        self.assertEqual(self.errors(value), [])

    def test_caleb_unknown_lane_or_scope_cannot_bypass_validation(self) -> None:
        """Malformed ownership retains the shared resolver's hard rejection."""
        for value in (plan("unknown", style="caleb"),
                      plan("light", style="caleb", lanes={"graphics": "typo"})):
            with self.assertRaises(ValueError):
                self.errors(value)

    def test_other_named_style_does_not_infer_caleb_exception(self) -> None:
        """This narrow compatibility exception does not open other style rules."""
        self.assertEqual(self.errors(plan("light", style="jadenly")), [])

    def test_longform_never_gains_short_hook_requirement(self) -> None:
        """Mode-specific missing-hook behavior is unchanged."""
        self.assertEqual(self.errors(plan("produced", mode="longform", style="caleb")), [])

    def test_supplied_cards_keep_text_hold_and_window_checks_when_off(self) -> None:
        """Waived missing-card ownership does not weaken authored card safety."""
        cases = [
            ({"text": "a b c d e f g h i"}, "words (max"),
            ({"text": "a\nb\nc"}, "lines (max"),
            ({"text": "x" * 60}, "chars (max"),
            ({"outEnd": 0.1}, "hold"),
            ({"outEnd": 8.0}, "hold"),
            ({"outStart": -1.0}, "outside output duration"),
        ]
        for fields, expected in cases:
            value = plan("light", lanes={"graphics": "off"})
            value["titleCards"] = [card(**fields)]
            self.assertIn(expected, " ".join(self.errors(value)))

    def test_supplied_overlapping_cards_still_fail_when_off(self) -> None:
        """Card/card collisions remain checked for every supplied track."""
        value = plan("light", lanes={"graphics": "off"})
        value["titleCards"] = [card(), card(outStart=1.0, outEnd=3.5)]
        self.assertIn("overlaps another title card", " ".join(self.errors(value)))

    def test_wrong_or_late_hook_does_not_satisfy_owned_obligation(self) -> None:
        """Existing style/start requirements remain literal, not inferred."""
        for fields in ({"style": "lower"}, {"outStart": 0.02}):
            value = plan("full")
            value["titleCards"] = [card(**fields)]
            self.assertIn("style='hook'", " ".join(self.errors(value)))


if __name__ == "__main__":
    unittest.main()
