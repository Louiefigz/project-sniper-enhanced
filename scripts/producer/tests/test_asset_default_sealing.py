"""Declared asset defaults and explicit probe samples must seal exact local files."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from graphics.comp_rate_oci_inputs import _prepare_one
from graphics.template_contract import entry_errors, resolved_assets
from graphics.template_assets import effective_asset_spec, resolved_selectors

ROOT = Path(__file__).resolve().parents[3]


class AssetDefaultSealingTests(unittest.TestCase):
    def test_retired_icon_template_cannot_ship_even_with_explicit_assets(self) -> None:
        for spec in ({}, {"label": "Subscribe"}, {"icon": ""}, {"icon": "", "label": ""}):
            entry = {"kind": "stroke-draw-badge", "spec": spec, "outStart": 0, "outEnd": 3}
            with self.subTest(spec=spec):
                self.assertTrue(any("retired" in issue for issue in entry_errors(entry)))
        good = {"kind": "stroke-draw-badge", "spec": {"icon": "youtube", "label": ""}, "outStart": 0, "outEnd": 3}
        self.assertTrue(any("retired" in issue for issue in entry_errors(good)))

    def test_omitted_declared_icons_resolve_but_explicit_blanks_remain_blank(self) -> None:
        declared = {f"icon{index}": {"type": "string", "default": value}
                    for index, value in enumerate(("codex", "gemini", "cursor"), 1)}
        default = resolved_selectors(effective_asset_spec({}, declared), declared)
        self.assertEqual([row["selector"] for row in default], ["codex", "gemini", "cursor"])
        explicit = resolved_selectors(effective_asset_spec(
            {"icon1": "", "icon2": "youtube.svg", "icon3": ""}, declared), declared)
        self.assertEqual([(row["field"], row["selector"]) for row in explicit], [("icon2", "youtube.svg")])

    def test_invalid_missing_traversal_or_encoded_asset_fails_before_render(self) -> None:
        for selector in ("does-not-exist.svg", "../youtube.svg", "/icons/youtube.svg", "%2e%2e/youtube.svg", None):
            with self.subTest(selector=selector), self.assertRaises(ValueError):
                resolved_selectors({"icon": selector}, {"icon": {"type": "string"}})

    def test_explicit_diagnostic_sample_is_in_actual_sealed_archive(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw).resolve() / "probe"
            request = _prepare_one(str(ROOT), ROOT / "templates/motion/compositions/ui-focus-zoom.html", "30", directory)
            self.assertEqual([(row["field"], row["selector"], row["path"]) for row in request["assetBindings"]],
                             [("image", "assets/sample-screen.png", "motion/assets/sample-screen.png")])
            self.assertIn("motion/assets/sample-screen.png", [row["path"] for row in request["manifest"]])

    def test_current_image_asset_requires_explicit_safe_selector(self) -> None:
        for value in ("", "assets/missing.png", "../sample-screen.png", "assets/sample-screen.png?x=1", None):
            entry = {"kind": "ui-focus-zoom", "spec": {"image": value}, "outStart": 0, "outEnd": 3}
            with self.subTest(value=value):
                self.assertTrue(any("image" in issue for issue in entry_errors(entry)))
        assets = resolved_assets({"kind": "ui-focus-zoom", "spec": {"image": "assets/sample-screen.png"}})
        self.assertEqual([row["selector"] for row in assets], ["assets/sample-screen.png"])


if __name__ == "__main__":
    unittest.main()
