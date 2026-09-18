"""Regression guards for the adversarial review of the 7 catalog-ported
comps (2026-08-28).

The review's GATE-HOLE tests asserted the then-broken acceptance; every
finding is now fixed and each test asserts the REPAIRED behavior so the
holes cannot reopen. Findings: F1 hw-callout defaults failed their own
contract (probe renderError blockaded the kind), F2 count-up's numeric
start/end escaped claims_contract, F3 char-count fit gates let wide glyphs
clip + substring emphasis matched mid-word, F5 Python float() accepted
numerals JS Number() rejects, F7 the image resolver never sniffed content.
Standalone run:

    cd scripts/producer && PYTHONPATH=.:tests ../../.venv/bin/python3 \
        tests/test_comps_edgecases_review.py
"""
from __future__ import annotations

import os
import tempfile
import unittest

import _common  # noqa: F401  (producer pkg root on sys.path)
import claims_contract as cc
import plan_lint as pl
from graphics import template_catalog_contract as tcc
from graphics import template_contract as tc
from graphics.comp_catalog_probe import _PROBE_OVERRIDES, probe_spec
from graphics.graphics_render import COMPOSITIONS_DIR
from graphics.template_contract import declared_variables


def _entry(kind: str, spec: dict, anchor: str = "free-band") -> dict:
    return {"kind": kind, "outStart": 4.0, "outEnd": 9.0, "anchor": anchor,
            "reason": "review probe", "spec": spec}


def _words(text: str, start: float = 0.0, step: float = 0.5) -> list[dict]:
    out, t = [], start
    for tok in text.split():
        out.append({"word": tok, "start": round(t, 3), "end": round(t + 0.4, 3)})
        t += step
    return out


# --------------------------------------------------------------------------- #
# FINDING 1 — hw-callout-circle's DECLARED DEFAULTS failed their own
# label-geometry contract (labelAt "right" beside the default-width region
# ran the label off the 1080 canvas), so the capability probe recorded
# renderError and plan_lint_comps hard-FAILed every plan carrying the kind.
# FIX: defaults are self-consistent (labelAt "below"). The stale
# comp_capabilities.json row refreshes on the next probe run (team lead's).
# --------------------------------------------------------------------------- #
class HwCalloutDefaultsTests(unittest.TestCase):

    def _declared(self) -> dict:
        path = os.path.join(COMPOSITIONS_DIR, "hw-callout-circle.html")
        with open(path, encoding="utf-8") as handle:
            return declared_variables(handle.read())

    def test_declared_defaults_pass_their_own_contract(self) -> None:
        declared = self._declared()
        defaults = {key: row["default"] for key, row in declared.items()
                    if "default" in row}
        self.assertEqual(
            tc.entry_errors(_entry("hw-callout-circle", defaults)), [])

    def test_probe_spec_passes_so_the_probe_can_render(self) -> None:
        # comp_catalog_probe renders probe_spec(defaults + overrides); a
        # contract-green probe spec is what keeps renderError off the row.
        spec = probe_spec("hw-callout-circle", self._declared())
        self.assertEqual(tc.entry_errors(_entry("hw-callout-circle", spec)), [])

    def test_no_probe_override_is_needed(self) -> None:
        # The fix is self-consistent DEFAULTS, not an override patch.
        self.assertNotIn("hw-callout-circle", _PROBE_OVERRIDES)

    def test_valid_spec_still_passes_the_contract(self) -> None:
        spec = {"x": 240, "y": 700, "w": 440, "h": 260,
                "label": "this one", "labelAt": "below", "drawAt": 0.4}
        self.assertEqual(tc.entry_errors(_entry("hw-callout-circle", spec)), [])

    def test_edge_flush_region_is_rejected(self) -> None:
        # Hardening: the wobbled ellipse draws ~26px+stroke outside the
        # region — flush against the canvas edge it clips its own ink.
        spec = {"x": 0, "y": 780, "w": 600, "h": 300, "label": "",
                "drawAt": 0.2}
        errors = tc.entry_errors(_entry("hw-callout-circle", spec))
        self.assertTrue(any("clearance" in e for e in errors), errors)


# --------------------------------------------------------------------------- #
# FINDING 2 — count-up's hero number NEVER reached claims_contract
# (spec.end/start are JSON numbers; _spec_strings walked string leaves
# only). FIX: numeric leaves of an affix-declaring dict are gated as their
# PAINTED forms ("250%"); zero stays exempt as the null counting origin.
# The template contract also requires integer start/end now — the comp
# rounds every painted row.
# --------------------------------------------------------------------------- #
class CountUpTruthGateTests(unittest.TestCase):

    def _plan(self, spec: dict) -> dict:
        return {"graphicsTrack": [
            {"outStart": 0.0, "outEnd": 4.0, "kind": "count-up",
             "anchor": "free-band", "spec": spec}]}

    def test_unspoken_end_value_fails_claims_contract(self) -> None:
        rep = pl.Report()
        cc.check_claims_contract(
            self._plan({"start": 0, "end": 250, "suffix": "%"}),
            _words("we grew the channel a lot last quarter honestly"), rep)
        self.assertTrue(any("250%" in e for e in rep.errors), rep.errors)

    def test_spoken_end_value_passes(self) -> None:
        # start=0 owes nothing (the null origin); the landed 250% is spoken.
        rep = pl.Report()
        cc.check_claims_contract(
            self._plan({"start": 0, "end": 250, "suffix": "%"}),
            _words("we grew the channel two hundred fifty percent honestly"),
            rep)
        self.assertEqual(rep.errors, [])
        self.assertEqual(rep.warnings, [])

    def test_fractional_end_fails_the_template_contract(self) -> None:
        # formatValue() Math.round()s every row: end=99.5 would LAND "100",
        # a value no gate saw, and 0.4 lands a zero-motion "0".
        for end in (99.5, 0.4):
            spec = {"start": 0, "end": end, "suffix": "%"}
            errors = tc.entry_errors(_entry("count-up", spec))
            self.assertTrue(any("integer" in e for e in errors), (end, errors))

    def test_boundary_magnitude_passes(self) -> None:
        # 1e9 stays accepted (the bound is inclusive by design).
        spec = {"start": 0, "end": 1_000_000_000, "suffix": "%"}
        self.assertEqual(tc.entry_errors(_entry("count-up", spec)), [])


# --------------------------------------------------------------------------- #
# FINDING 5 (parser drift) — Python float() accepts underscore separators
# ("1_2" == 12.0) that JS Number() rejects, so a gate-green plan crashed the
# comp at render time. FIX: only the ASCII numeric charset reaches float().
# --------------------------------------------------------------------------- #
class ChartStoryParserDriftTests(unittest.TestCase):

    def _good(self) -> dict:
        return {"type": "bars", "data": "12, 28, 45, 64",
                "labels": "Q1, Q2, Q3, Q4", "emphasize": 3, "unit": "%"}

    def test_python_underscore_numerals_are_rejected(self) -> None:
        spec = dict(self._good(), data="1_2, 3_4", labels="a, b", emphasize=1)
        errors = tc.entry_errors(_entry("chart-story", spec))
        self.assertTrue(any("is not a number" in e for e in errors), errors)

    def test_hex_and_infinity_tokens_are_rejected(self) -> None:
        for data in ("0x10, 12", "inf, 12", "nan, 12"):
            errors = tc.entry_errors(_entry(
                "chart-story", dict(self._good(), data=data, labels="a, b",
                                    emphasize=0)))
            self.assertTrue(errors, data)

    def test_trailing_comma_is_rejected(self) -> None:
        spec = dict(self._good(), data="12, 28, 45, 64,")
        errors = tc.entry_errors(_entry("chart-story", spec))
        self.assertTrue(any("is not a number" in e for e in errors), errors)

    def test_scientific_notation_stays_consistent(self) -> None:
        # "1e5" parses identically in both runtimes — still legal.
        spec = dict(self._good(), data="1e5, 12", labels="a, b", emphasize=0)
        self.assertEqual(tc.entry_errors(_entry("chart-story", spec)), [])

    def test_integral_float_emphasize_passes(self) -> None:
        spec = dict(self._good(), emphasize=3.0)
        self.assertEqual(tc.entry_errors(_entry("chart-story", spec)), [])


# --------------------------------------------------------------------------- #
# FINDING 3 — the char-COUNT fit gates assumed average glyph width; a
# wide-glyph line passed every gate and clipped in the overflow-hidden mask,
# and substring emphasis matching hit MID-WORD ("art" inside "Start").
# FIX: measured glyph-width tables (graphics/glyph_metrics) + word-boundary
# matching in gate AND comp.
# --------------------------------------------------------------------------- #
class WidthGateGlyphTableTests(unittest.TestCase):

    def test_line_swap_wide_glyph_line_is_rejected(self) -> None:
        # 40 x "W" is <= 48 chars but paints ~1500px against the 758px mask.
        spec = {"lineA": "Short setup line",
                "lineB": "W" * 40, "underlineWord": "", "swapAt": 1.2}
        errors = tc.entry_errors(_entry("line-swap", spec))
        self.assertTrue(any("glyph-width" in e for e in errors), errors)

    def test_line_swap_49_chars_is_rejected(self) -> None:
        spec = {"lineA": "x" * 49, "lineB": "ok line",
                "underlineWord": "", "swapAt": 1.2}
        errors = tc.entry_errors(_entry("line-swap", spec))
        self.assertTrue(any("overflows the card" in e for e in errors), errors)

    def test_line_swap_realistic_long_line_still_passes(self) -> None:
        # 47 chars of realistic marketing copy must fit at the 30px floor.
        spec = {"lineA": "Nobody needs more footage",
                "lineB": "The first two seconds decide who keeps watching",
                "underlineWord": "seconds", "swapAt": 1.2}
        self.assertEqual(tc.entry_errors(_entry("line-swap", spec)), [])

    def test_marker_long_nowrap_phrase_is_rejected(self) -> None:
        # The emphasized phrase cannot wrap (.mh-em is white-space:nowrap)
        # and overflows the 758px panel content box at the 38px fit floor.
        phrase = "a very long emphasised phrase that never wraps"
        spec = {"text": f"So {phrase} happens", "emphasisWord": phrase,
                "style": "highlight", "drawAt": 0.9}
        errors = tc.entry_errors(_entry("marker-highlight", spec))
        self.assertTrue(any("glyph-width" in e for e in errors), errors)

    def test_marker_whole_word_match_passes(self) -> None:
        # "art" exists as a whole word; comp + gate both bind THAT
        # occurrence now (boundaryIndexOf / word_boundary_match).
        spec = {"text": "Start with the art of the hook",
                "emphasisWord": "art", "style": "circle", "drawAt": 0.9}
        self.assertEqual(tc.entry_errors(_entry("marker-highlight", spec)), [])

    def test_marker_mid_word_only_match_is_rejected(self) -> None:
        # "tar" appears ONLY inside "Start" — no whole-word occurrence.
        spec = {"text": "Start with the art of the hook",
                "emphasisWord": "tar", "style": "circle", "drawAt": 0.9}
        errors = tc.entry_errors(_entry("marker-highlight", spec))
        self.assertTrue(any("whole word" in e for e in errors), errors)

    def test_underline_mid_word_only_match_is_rejected(self) -> None:
        spec = {"lineA": "Setup line", "lineB": "Start with the hook",
                "underlineWord": "tar", "swapAt": 1.2}
        errors = tc.entry_errors(_entry("line-swap", spec))
        self.assertTrue(any("whole word" in e for e in errors), errors)


# --------------------------------------------------------------------------- #
# FINDING 7 — the resolver rejected traversal/symlinks correctly but never
# sniffed content: any FILE with an image extension passed, and the comp
# silently degraded to the skeleton. FIX: magic bytes must match the
# extension (PNG/JPEG/WebP signatures).
# --------------------------------------------------------------------------- #
class UiFocusZoomResolverTests(unittest.TestCase):

    PNG_MAGIC = b"\x89PNG\r\n\x1a\n" + b"payload"
    WEBP_MAGIC = b"RIFF\x24\x00\x00\x00WEBPVP8 "

    def setUp(self) -> None:
        self._saved = tcc.MOTION_DIR
        self._tmp = tempfile.mkdtemp(prefix="review-ufz-")
        os.makedirs(os.path.join(self._tmp, "assets"), exist_ok=True)
        tcc.MOTION_DIR = self._tmp

    def tearDown(self) -> None:
        tcc.MOTION_DIR = self._saved

    def _write(self, rel: str, data: bytes = b"not a png") -> str:
        path = os.path.join(self._tmp, rel)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def test_text_bytes_with_png_extension_are_rejected(self) -> None:
        self._write("assets/fake.png")
        self.assertIsNone(tcc._image_path("assets/fake.png"))

    def test_wrong_signature_for_extension_is_rejected(self) -> None:
        # Real PNG bytes under a .jpg name: the sniff matches per-extension.
        self._write("assets/mislabeled.jpg", self.PNG_MAGIC)
        self.assertIsNone(tcc._image_path("assets/mislabeled.jpg"))

    def test_matching_signatures_pass(self) -> None:
        self._write("assets/real.png", self.PNG_MAGIC)
        self._write("assets/real.webp", self.WEBP_MAGIC)
        self._write("assets/real.jpg", b"\xff\xd8\xff\xe0rest")
        for selector in ("assets/real.png", "assets/real.webp",
                         "assets/real.jpg"):
            self.assertIsNotNone(tcc._image_path(selector), selector)

    def test_content_mismatch_gets_its_own_error_message(self) -> None:
        self._write("assets/fake.png")
        errors = tcc._focus_zoom_errors({"image": "assets/fake.png"})
        self.assertTrue(any("magic-byte" in e for e in errors), errors)

    def test_symlink_escaping_assets_is_rejected(self) -> None:
        link = os.path.join(self._tmp, "assets", "esc.png")
        os.symlink("/etc/hosts", link)
        self.assertIsNone(tcc._image_path("assets/esc.png"))

    def test_lexical_traversal_forms_are_rejected(self) -> None:
        self._write("assets/x.png", self.PNG_MAGIC)
        for selector in ("assets/../assets/x.png", "assets/./x.png",
                         "assets//x.png", "/assets/x.png", " assets/x.png",
                         "assets\\x.png", "Assets/x.png", "assets/x.png%00"):
            self.assertIsNone(tcc._image_path(selector), selector)

    def test_probe_override_resolves_against_the_real_repo(self) -> None:
        tcc.MOTION_DIR = self._saved  # the real templates/motion
        selector = _PROBE_OVERRIDES["ui-focus-zoom"]["image"]
        self.assertIsNotNone(tcc._image_path(selector))


# --------------------------------------------------------------------------- #
# FINDING 4 — ui-focus-zoom's camera rode tween-level onUpdate, which fires
# only on event-firing seeks; Studio and the editor preview seek suppressed,
# freezing the camera there. FIX: setter-driven camera proxy. Source-level
# guard here; landing-transform parity is proven in the review harness.
# --------------------------------------------------------------------------- #
class UiFocusZoomDriverTests(unittest.TestCase):

    def test_no_onupdate_left_in_the_comp(self) -> None:
        path = os.path.join(COMPOSITIONS_DIR, "ui-focus-zoom.html")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        # The executable tween-config form (comments may explain the trap).
        self.assertNotIn("onUpdate:", source)
        self.assertIn("defineProperty", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
