"""Declared asset defaults and explicit probe samples must seal exact local files."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from graphics.comp_rate_oci_inputs import _prepare_one
from graphics.template_contract import entry_errors, resolved_assets

ROOT = Path(__file__).resolve().parents[3]


class AssetDefaultSealingTests(unittest.TestCase):
    def test_empty_or_label_only_stroke_cannot_ship_hidden_preview_sample(self) -> None:
        for spec in ({}, {"label": "Subscribe"}, {"icon": ""}, {"icon": "", "label": ""}):
            entry = {"kind": "stroke-draw-badge", "spec": spec, "outStart": 0, "outEnd": 3}
            with self.subTest(spec=spec):
                self.assertTrue(any("asset-only" in issue for issue in entry_errors(entry)))
        good = {"kind": "stroke-draw-badge", "spec": {"icon": "youtube", "label": ""}, "outStart": 0, "outEnd": 3}
        self.assertEqual(entry_errors(good), [])

    def test_omitted_declared_icons_resolve_but_explicit_blanks_remain_blank(self) -> None:
        default = resolved_assets({"kind": "icon-badge", "spec": {"label": ""}})
        self.assertEqual([row["selector"] for row in default], ["codex", "gemini", "cursor"])
        explicit = resolved_assets({"kind": "icon-badge", "spec": {"icon1": "", "icon2": "youtube.svg", "icon3": "", "label": ""}})
        self.assertEqual([(row["field"], row["selector"]) for row in explicit], [("icon2", "youtube.svg")])

    def test_invalid_missing_traversal_or_encoded_asset_fails_before_render(self) -> None:
        for selector in ("does-not-exist.svg", "../youtube.svg", "/icons/youtube.svg", "%2e%2e/youtube.svg", None):
            with self.subTest(selector=selector), self.assertRaises(ValueError):
                resolved_assets({"kind": "stroke-draw-badge", "spec": {"icon": selector}})

    def test_explicit_diagnostic_sample_is_in_actual_sealed_archive(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw).resolve() / "probe"
            request = _prepare_one(str(ROOT), ROOT / "templates/motion/compositions/stroke-draw-badge.html", "30", directory)
            self.assertEqual([(row["field"], row["selector"], row["path"]) for row in request["assetBindings"]],
                             [("icon", "youtube", "motion/icons/youtube.svg")])
            self.assertIn("motion/icons/youtube.svg", [row["path"] for row in request["manifest"]])


if __name__ == "__main__":
    unittest.main()
