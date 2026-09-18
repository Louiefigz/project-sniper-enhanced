"""Hand-drawn (hw) family template contracts — catalog port wave A."""
from __future__ import annotations

import unittest

import _common  # noqa: F401  (producer pkg root on sys.path)
from graphics import template_contract as tc
from graphics.template_hw_contract import HW_KINDS
from planner import graphics_planner_longform as longform


def _entry(kind: str, spec: dict, anchor: str = "free-band") -> dict:
    return {"kind": kind, "outStart": 4.0, "outEnd": 7.0, "anchor": anchor,
            "reason": "spoken emphasis", "spec": spec}


class MarkerHighlightContractTests(unittest.TestCase):
    """The marker IS the graphic: a silent no-marker render must be rejected."""

    def assert_error(self, spec: dict, needle: str) -> None:
        errors = tc.entry_errors(_entry("marker-highlight", spec))
        self.assertTrue(any(needle in error for error in errors), errors)

    def _good(self) -> dict:
        return {"text": "Retention is won in the first line",
                "emphasisWord": "Retention", "style": "circle", "drawAt": 1.2}

    def test_good_spec_passes(self) -> None:
        self.assertEqual(tc.entry_errors(_entry("marker-highlight",
                                                self._good())), [])

    def test_missing_text_is_rejected(self) -> None:
        self.assert_error({"emphasisWord": "hook"}, "non-empty spec.text")

    def test_blank_emphasis_word_is_rejected(self) -> None:
        spec = dict(self._good(), emphasisWord="  ")
        self.assert_error(spec, "non-empty spec.emphasisWord")

    def test_unmatched_emphasis_word_is_rejected(self) -> None:
        spec = dict(self._good(), emphasisWord="algorithm")
        self.assert_error(spec, "does not appear in")

    def test_mid_word_only_match_is_rejected(self) -> None:
        # "tent" only appears inside "Retention": a substring hit would
        # mark the wrong ink (review F3); the match must be whole-word.
        spec = dict(self._good(), emphasisWord="tent")
        self.assert_error(spec, "whole word")

    def test_overwide_emphasis_phrase_is_rejected(self) -> None:
        # The emphasized span never wraps; the glyph-width table (not a
        # char count) must catch a phrase wider than the 758px panel box.
        phrase = "a very long emphasised phrase that never wraps"
        spec = {"text": f"So {phrase} happens", "emphasisWord": phrase,
                "style": "highlight", "drawAt": 0.9}
        self.assert_error(spec, "glyph-width")

    def test_emphasis_match_is_case_insensitive(self) -> None:
        spec = dict(self._good(), emphasisWord="retention")
        self.assertEqual(tc.entry_errors(_entry("marker-highlight", spec)), [])

    def test_unknown_style_fails_the_enum_gate(self) -> None:
        spec = dict(self._good(), style="wavy")
        self.assert_error(spec, "not in")

    def test_negative_draw_at_is_rejected(self) -> None:
        spec = dict(self._good(), drawAt=-1)
        self.assert_error(spec, "spec.drawAt")


class HwCalloutCircleContractTests(unittest.TestCase):
    """A default region is a mis-annotation: the box is required, on-canvas."""

    def assert_error(self, spec: dict, needle: str) -> None:
        errors = tc.entry_errors(_entry("hw-callout-circle", spec))
        self.assertTrue(any(needle in error for error in errors), errors)

    def _good(self) -> dict:
        return {"x": 240, "y": 700, "w": 440, "h": 260,
                "label": "this one", "labelAt": "below", "drawAt": 0.4}

    def test_good_spec_passes(self) -> None:
        self.assertEqual(tc.entry_errors(_entry("hw-callout-circle",
                                                self._good())), [])

    def test_missing_region_is_rejected(self) -> None:
        self.assert_error({"label": "here"}, "explicit region")

    def test_off_canvas_region_is_rejected(self) -> None:
        spec = dict(self._good(), x=700, w=600)
        self.assert_error(spec, "inside the 1080x1920 canvas")

    def test_zero_area_region_is_rejected(self) -> None:
        spec = dict(self._good(), w=0)
        self.assert_error(spec, "must be > 0")

    def test_explicit_blank_label_is_circle_only_intent(self) -> None:
        spec = dict(self._good(), label="")
        self.assertEqual(tc.entry_errors(_entry("hw-callout-circle", spec)), [])

    def test_unknown_label_side_fails_the_enum_gate(self) -> None:
        spec = dict(self._good(), labelAt="above")
        self.assert_error(spec, "not in")

    def test_off_canvas_label_is_rejected(self) -> None:
        # The proven defect: a right-side label beside a wide region ran off
        # the canvas on a real render (clipped "this number").
        spec = {"x": 300, "y": 820, "w": 480, "h": 260,
                "label": "this number", "labelAt": "right"}
        self.assert_error(spec, "lands off the 1080x1920 canvas")

    def test_declared_defaults_pass_their_own_contract(self) -> None:
        # Review F1: the shipped defaults (labelAt "right") failed this very
        # gate and blockaded the kind via a probe renderError row.
        spec = {"x": 240, "y": 780, "w": 600, "h": 300, "label": "look here",
                "labelAt": "below", "scribble": False, "seed": 4,
                "drawAt": 0.2}
        self.assertEqual(tc.entry_errors(_entry("hw-callout-circle", spec)), [])

    def test_wide_glyph_label_is_rejected(self) -> None:
        # Ten Caveat "W" glyphs paint ~720px; the retired 36px/char average
        # said they fit (review F3b) — the measured table must not.
        spec = {"x": 152, "y": 800, "w": 400, "h": 240,
                "label": "WWWWWWWWWW", "labelAt": "right", "drawAt": 0.2}
        self.assert_error(spec, "lands off the 1080x1920 canvas")

    def test_edge_flush_region_is_rejected(self) -> None:
        # The ellipse draws ~26px + stroke + wobble outside the region: a
        # region flush with the canvas edge clips its own ink.
        spec = {"x": 0, "y": 780, "w": 600, "h": 300, "label": "",
                "drawAt": 0.2}
        self.assert_error(spec, "clearance")


class HwScribbleTransitionContractTests(unittest.TestCase):
    """A transition's defaults ARE the product — {} is a legitimate spec."""

    def assert_error(self, spec: dict, needle: str) -> None:
        errors = tc.entry_errors(_entry("hw-scribble-transition", spec))
        self.assertTrue(any(needle in error for error in errors), errors)

    def test_empty_spec_passes(self) -> None:
        self.assertEqual(tc.entry_errors(
            _entry("hw-scribble-transition", {})), [])

    def test_fractional_band_count_is_rejected(self) -> None:
        self.assert_error({"bands": 7.5}, "integer in [3,18]")

    def test_out_of_range_band_count_is_rejected(self) -> None:
        self.assert_error({"bands": 1}, "integer in [3,18]")

    def test_out_of_range_stroke_scale_is_rejected(self) -> None:
        self.assert_error({"strokeScale": 9}, "in [0.5,2.0]")


class HwFamilyRegistrationTests(unittest.TestCase):
    """The kinds are real comps and the planner's canvas filter knows them."""

    def test_catalog_carries_the_family_at_shorts_canvas(self) -> None:
        catalog = tc.template_catalog()
        for kind in HW_KINDS:
            with self.subTest(kind=kind):
                self.assertEqual(catalog[kind]["dimensions"], [1080, 1920])

    def test_planner_canvas_fallback_registers_the_family(self) -> None:
        for kind in HW_KINDS:
            with self.subTest(kind=kind):
                self.assertEqual(
                    longform.KIND_CANVAS_FALLBACK.get(kind), "9:16")

    def test_content_contract_requires_the_planned_copy(self) -> None:
        catalog = tc.template_catalog()
        marker = catalog["marker-highlight"]["contentContract"]
        self.assertIn("text", marker["requiredDefaultOverrides"])
        self.assertIn("emphasisWord", marker["requiredDefaultOverrides"])
        callout = catalog["hw-callout-circle"]["contentContract"]
        self.assertIn("label", callout["requiredDefaultOverrides"])
        scribble = catalog["hw-scribble-transition"]["contentContract"]
        self.assertEqual(scribble["requiredDefaultOverrides"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
