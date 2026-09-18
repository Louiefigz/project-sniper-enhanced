"""Visible-completeness regression tests for long-form templates."""
from __future__ import annotations

import unittest

from _common import pl  # noqa: F401
from graphics import template_contract as tc


def _entry(kind: str, spec: dict, duration: float = 6.0) -> dict:
    return {"kind": kind, "outStart": 0.0, "outEnd": duration,
            "anchor": "own-screen", "spec": spec}


class TemplateVisualContractTests(unittest.TestCase):
    def test_named_brands_require_distinct_color_assets(self) -> None:
        entry = _entry("icon-badge-wide", {
            "icon1": "openai.svg", "icon2": "claude.svg",
            "icon3": "gemini.svg", "at1": 0.2, "at2": 0.8, "at3": 1.4,
        })
        errors = tc.entry_errors(entry)
        self.assertEqual(sum("approved asset" in error for error in errors), 3)
        entry["spec"].update({
            "icon1": "openai-color.svg", "icon2": "claude-color.svg",
            "icon3": "gemini-color.svg",
        })
        self.assertEqual(tc.entry_errors(entry), [])

    def test_avatar_card_cannot_render_an_empty_portrait(self) -> None:
        entry = _entry("avatar-bio-card", {
            "avatarSrc": "", "initials": "", "line1": "Ten years",
            "line2": "I build the system", "at2": 3.0,
        })
        errors = tc.entry_errors(entry)
        self.assertTrue(any("empty portrait circle" in error for error in errors),
                        errors)
        entry["spec"]["initials"] = "PS"
        self.assertEqual(tc.entry_errors(entry), [])

    def test_avatar_copy_must_fit_the_arc_safe_region(self) -> None:
        entry = _entry("avatar-bio-card", {
            "initials": "PS", "line1": "A decade building software",
            "line2": "This credential statement is deliberately much too long "
                     "for the safe two-line region beside the curve",
            "at2": 3.0, "at3": 3.4,
        })
        errors = tc.entry_errors(entry)
        self.assertTrue(any("two-line safe region" in error
                            for error in errors), errors)

    def test_last_icon_reveal_needs_dwell_and_exit_runway(self) -> None:
        entry = _entry("icon-badge-wide", {
            "icon1": "openai-color.svg", "icon2": "claude-color.svg",
            "icon3": "gemini-color.svg", "at1": 1.29, "at2": 1.89,
            "at3": 2.43,
        }, 2.97)
        errors = tc.entry_errors(entry)
        self.assertTrue(any("completion floor" in error for error in errors),
                        errors)
        entry["outEnd"] = 4.26
        self.assertEqual(tc.entry_errors(entry), [])

    def test_statement_card_has_a_readable_floor(self) -> None:
        entry = _entry("statement-card", {
            "variant": "classic", "text": "A real thesis",
        }, 1.7)
        errors = tc.entry_errors(entry)
        self.assertTrue(any("completion floor" in error for error in errors),
                        errors)


if __name__ == "__main__":
    unittest.main()
