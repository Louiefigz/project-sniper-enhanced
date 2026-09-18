"""Catalog data/hook/screen family template contracts — port wave B."""
from __future__ import annotations

import os
import unittest

import _common  # noqa: F401  (producer pkg root on sys.path)
from graphics import template_contract as tc
from graphics.template_catalog_contract import CATALOG_KINDS
from planner import graphics_planner_longform as longform
from producer_config import MOTION


def _entry(kind: str, spec: dict, anchor: str = "free-band") -> dict:
    return {"kind": kind, "outStart": 4.0, "outEnd": 9.0, "anchor": anchor,
            "reason": "evidence beat", "spec": spec}


class ChartStoryContractTests(unittest.TestCase):
    """The chart lands exact values: form, data, labels, emphasis explicit."""

    def assert_error(self, spec: dict, needle: str) -> None:
        errors = tc.entry_errors(_entry("chart-story", spec))
        self.assertTrue(any(needle in error for error in errors), errors)

    def _good(self) -> dict:
        return {"type": "bars", "data": "12, 28, 45, 64",
                "labels": "Q1, Q2, Q3, Q4", "emphasize": 3, "unit": "%"}

    def test_good_spec_passes(self) -> None:
        self.assertEqual(tc.entry_errors(_entry("chart-story",
                                                self._good())), [])

    def test_each_chart_form_passes(self) -> None:
        for form in ("bars", "line", "donut", "progress"):
            spec = dict(self._good(), type=form)
            self.assertEqual(tc.entry_errors(_entry("chart-story", spec)),
                             [], form)

    def test_implicit_type_is_rejected(self) -> None:
        spec = self._good()
        del spec["type"]
        self.assert_error(spec, "explicit spec.type")

    def test_missing_data_is_rejected(self) -> None:
        spec = self._good()
        del spec["data"]
        self.assert_error(spec, "non-empty spec.data")

    def test_non_numeric_data_token_is_rejected(self) -> None:
        self.assert_error(dict(self._good(), data="12, lots, 45"),
                          "is not a number")

    def test_underscore_numeral_is_rejected(self) -> None:
        # float("1_2") == 12.0 in Python but Number("1_2") is NaN in the
        # comp (review F5): the parser drift must fail at the gate, not at
        # render time.
        self.assert_error(dict(self._good(), data="1_2, 34", labels="a, b",
                               emphasize=1), "is not a number")

    def test_overlarge_magnitude_is_rejected(self) -> None:
        self.assert_error(dict(self._good(), data="12, 2000000000, 45, 64"),
                          "within 1e+09")

    def test_overlong_unit_is_rejected(self) -> None:
        self.assert_error(dict(self._good(), unit="requests/second"),
                          "at most 8")

    def test_single_datum_is_rejected(self) -> None:
        spec = dict(self._good(), data="42", labels="All", emphasize=0)
        self.assert_error(spec, "needs 2..8 values")

    def test_negative_data_is_rejected(self) -> None:
        self.assert_error(dict(self._good(), data="12, -3, 45, 64"),
                          "finite and >= 0")

    def test_all_zero_data_is_rejected(self) -> None:
        self.assert_error(dict(self._good(), data="0, 0, 0, 0"),
                          "at least one value > 0")

    def test_label_count_mismatch_is_rejected(self) -> None:
        self.assert_error(dict(self._good(), labels="Q1, Q2"),
                          "pair 1:1")

    def test_missing_emphasize_is_rejected(self) -> None:
        spec = self._good()
        del spec["emphasize"]
        self.assert_error(spec, "integer spec.emphasize")

    def test_out_of_range_emphasize_is_rejected(self) -> None:
        self.assert_error(dict(self._good(), emphasize=4),
                          "outside the data range")


class CountUpContractTests(unittest.TestCase):
    """The landed number is the content: explicit, finite, and moving."""

    def assert_error(self, spec: dict, needle: str) -> None:
        errors = tc.entry_errors(_entry("count-up", spec))
        self.assertTrue(any(needle in error for error in errors), errors)

    def _good(self) -> dict:
        return {"start": 0, "end": 250, "suffix": "%"}

    def test_good_spec_passes(self) -> None:
        self.assertEqual(tc.entry_errors(_entry("count-up", self._good())), [])

    def test_missing_end_is_rejected(self) -> None:
        self.assert_error({"start": 0, "suffix": "%"}, "explicit finite spec.end")

    def test_boolean_end_is_rejected(self) -> None:
        self.assert_error(dict(self._good(), end=True), "spec.end")

    def test_zero_motion_counter_is_rejected(self) -> None:
        self.assert_error(dict(self._good(), start=250), "must differ")

    def test_fractional_end_is_rejected(self) -> None:
        # The comp rounds every painted row: end=99.5 would land "100", a
        # value no gate ever saw (review F2).
        self.assert_error(dict(self._good(), end=99.5), "integer")

    def test_fractional_start_is_rejected(self) -> None:
        self.assert_error(dict(self._good(), start=0.4), "integer")

    def test_unreadable_magnitude_is_rejected(self) -> None:
        self.assert_error(dict(self._good(), end=5e12), "within")

    def test_suffix_default_is_a_required_override(self) -> None:
        spec = self._good()
        del spec["suffix"]
        self.assert_error(spec, "spec.suffix")


class LineSwapContractTests(unittest.TestCase):
    """Both lines required; the swap and underline must be plannable."""

    def assert_error(self, spec: dict, needle: str) -> None:
        errors = tc.entry_errors(_entry("line-swap", spec))
        self.assertTrue(any(needle in error for error in errors), errors)

    def _good(self) -> dict:
        return {"lineA": "Nobody needs more footage",
                "lineB": "You need a sharper first line",
                "underlineWord": "sharper", "swapAt": 1.2}

    def test_good_spec_passes(self) -> None:
        self.assertEqual(tc.entry_errors(_entry("line-swap", self._good())), [])

    def test_missing_line_is_rejected(self) -> None:
        spec = self._good()
        del spec["lineA"]
        self.assert_error(spec, "non-empty spec.lineA")

    def test_overlong_line_is_rejected(self) -> None:
        spec = dict(self._good(), lineB="A line so long that the nowrap fit "
                    "would overflow the card badly", underlineWord="nowrap")
        self.assert_error(spec, "overflows the card")

    def test_unmatched_underline_word_is_rejected(self) -> None:
        spec = dict(self._good(), underlineWord="algorithm")
        self.assert_error(spec, "does not appear in")

    def test_mid_word_only_underline_match_is_rejected(self) -> None:
        # "harper" only appears inside "sharper": a substring hit would
        # underline the wrong ink (review F3); the match must be whole-word.
        spec = dict(self._good(), underlineWord="harper")
        self.assert_error(spec, "whole word")

    def test_wide_glyph_line_is_rejected_by_the_width_table(self) -> None:
        # 40 x "W" is under the 48-char cap but paints ~1500px against the
        # 758px overflow-hidden mask (review F3a).
        spec = dict(self._good(), lineB="W" * 40, underlineWord="")
        self.assert_error(spec, "glyph-width")

    def test_realistic_long_line_still_passes(self) -> None:
        spec = dict(self._good(),
                    lineB="The first two seconds decide who keeps watching",
                    underlineWord="seconds")
        self.assertEqual(tc.entry_errors(_entry("line-swap", spec)), [])

    def test_explicit_blank_underline_word_passes(self) -> None:
        spec = dict(self._good(), underlineWord="")
        self.assertEqual(tc.entry_errors(_entry("line-swap", spec)), [])

    def test_negative_swap_at_is_rejected(self) -> None:
        self.assert_error(dict(self._good(), swapAt=-1), "spec.swapAt")


class UiFocusZoomContractTests(unittest.TestCase):
    """The screenshot IS the cutaway; anchor and move must be real."""

    IMAGE = "assets/sample-screen.png"

    def assert_error(self, spec: dict, needle: str) -> None:
        errors = tc.entry_errors(_entry("ui-focus-zoom", spec))
        self.assertTrue(any(needle in error for error in errors), errors)

    def _good(self) -> dict:
        return {"image": self.IMAGE, "anchorX": 64, "anchorY": 36,
                "zoom": 1.8, "zoomAt": 1.0}

    def test_good_spec_passes(self) -> None:
        self.assertEqual(tc.entry_errors(_entry("ui-focus-zoom",
                                                self._good())), [])

    def test_missing_image_is_rejected(self) -> None:
        spec = self._good()
        del spec["image"]
        self.assert_error(spec, "requires explicit spec.image")

    def test_unresolved_image_is_rejected(self) -> None:
        spec = dict(self._good(), image="assets/absent.png")
        self.assert_error(spec, "does not resolve")

    def test_traversal_image_selector_is_rejected(self) -> None:
        spec = dict(self._good(), image="assets/../icons/notion.svg")
        self.assert_error(spec, "does not resolve")

    def test_non_assets_selector_is_rejected(self) -> None:
        spec = dict(self._good(), image="icons/notion.svg")
        self.assert_error(spec, "does not resolve")

    def test_no_op_zoom_is_rejected(self) -> None:
        self.assert_error(dict(self._good(), zoom=1.0), "no-op")

    def test_off_screen_anchor_is_rejected(self) -> None:
        self.assert_error(dict(self._good(), anchorX=140), "spec.anchorX")


class ImageAssetRowTests(unittest.TestCase):
    """resolved_assets carries the screenshot so the cache hashes its bytes."""

    IMAGE = "assets/sample-screen.png"

    def test_resolved_assets_returns_the_screenshot_row(self) -> None:
        rows = tc.resolved_assets(_entry("ui-focus-zoom", {"image": self.IMAGE}))
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0]["field"], "image")
        self.assertEqual(rows[0]["selector"], self.IMAGE)
        self.assertTrue(os.path.isfile(rows[0]["path"]), rows[0])

    def test_kindless_call_still_resolves_it(self) -> None:
        # The sealed-snapshot path (container_io._asset_sources) resolves
        # assets without a kind — only the comp html and the spec.
        with open(os.path.join(tc.COMPOSITIONS_DIR, "ui-focus-zoom.html"),
                  encoding="utf-8") as handle:
            html = handle.read()
        rows = tc.resolved_assets({"spec": {"image": self.IMAGE}}, html)
        self.assertEqual([row["field"] for row in rows], ["image"])

    def test_unresolved_selector_yields_no_row(self) -> None:
        rows = tc.resolved_assets(_entry("ui-focus-zoom",
                                         {"image": "assets/absent.png"}))
        self.assertEqual(rows, [])

    def test_non_image_kinds_are_unaffected(self) -> None:
        rows = tc.resolved_assets(_entry("chart-story", {
            "type": "bars", "data": "1, 2", "labels": "a, b",
            "emphasize": 1, "unit": ""}))
        self.assertEqual(rows, [])


class CatalogFamilyRegistrationTests(unittest.TestCase):
    """The kinds are real comps wired into the planner's catalogs."""

    CANVAS = {"chart-story": ([1920, 1080], "16:9"),
              "count-up": ([1080, 1920], "9:16"),
              "line-swap": ([1080, 1920], "9:16"),
              "ui-focus-zoom": ([1920, 1080], "16:9")}

    def test_catalog_carries_the_family_at_its_lane_canvas(self) -> None:
        catalog = tc.template_catalog()
        for kind in CATALOG_KINDS:
            with self.subTest(kind=kind):
                self.assertEqual(catalog[kind]["dimensions"],
                                 self.CANVAS[kind][0])

    def test_planner_canvas_fallback_registers_the_family(self) -> None:
        for kind in CATALOG_KINDS:
            with self.subTest(kind=kind):
                self.assertEqual(longform.KIND_CANVAS_FALLBACK.get(kind),
                                 self.CANVAS[kind][1])

    def test_data_kinds_join_their_information_shape_families(self) -> None:
        form_map = MOTION["card_form_map"]
        self.assertIn("chart-story", form_map["comparison"])
        self.assertIn("chart-story", form_map["trend"])
        self.assertIn("count-up", form_map["scale"])
        self.assertIn("line-swap", form_map["thesis"])

    def test_ui_focus_zoom_is_trigger_less(self) -> None:
        # glitch-hit doctrine: no info-shape family, no transcript trigger —
        # a screenshot punch-in is brain/operator-placed only.
        for family, kinds in MOTION["card_form_map"].items():
            self.assertNotIn("ui-focus-zoom", kinds, family)

    def test_content_contract_requires_the_planned_copy(self) -> None:
        catalog = tc.template_catalog()
        chart = catalog["chart-story"]["contentContract"]
        for key in ("data", "labels", "unit"):
            self.assertIn(key, chart["requiredDefaultOverrides"])
        swap = catalog["line-swap"]["contentContract"]
        for key in ("lineA", "lineB", "underlineWord"):
            self.assertIn(key, swap["requiredDefaultOverrides"])
        focus = catalog["ui-focus-zoom"]["contentContract"]
        # image is an ASSET slot, never visible copy.
        self.assertNotIn("image", focus["contentVariables"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
