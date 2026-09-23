"""Qualified template/static/decoded contrast cases; not real-render approval."""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from audit import audit_composite_visual as composite
from audit.audit_text_plates import text_plate_results
from audit.audit_text_placement import PlateContext
from graphics.template_text_contrast import effective_text_roles, text_plate_contract
from plan_lint_contrast import check_contrast


# Inert retained role metadata for isolated parser/pixel checks; never render input.
TEST_PLATE = {'schemaVersion': 1, 'treatment': 'plates', 'roles': [{'id': 'eyebrow', 'selector': '#marker-eyebrow', 'copyVariable': 'num', 'foreground': '#FFFFFF', 'background': '#0a1123', 'fullOpacityAt': 0.34}, {'id': 'title', 'selector': '#marker-title', 'copyVariable': 'line1', 'foregroundVariable': 'accent', 'background': '#f6eac6', 'fullOpacityAt': 0.58}, {'id': 'qualifier', 'selector': '#marker-qualifier', 'copyVariable': 'line2', 'foreground': '#FFFFFF', 'background': '#0a1123', 'fullOpacityAt': 0.66}], 'exit': {'maximumSeconds': 0.42, 'durationFraction': 0.18, 'frameReserveSeconds': 0.05}, 'declared': {'num': {'id': 'num', 'type': 'string', 'label': 'Eyebrow / section label — appears FIRST (e.g. 1 or Part 2)', 'default': 'Part 1'}, 'line1': {'id': 'line1', 'type': 'string', 'label': 'Title — serif-accent, wipes in (<= 2 words)', 'default': 'The Setup'}, 'line2': {'id': 'line2', 'type': 'string', 'label': 'Qualifier — white sans, optional (<= 2 words)', 'default': 'Basics'}, 'side': {'id': 'side', 'type': 'enum', 'label': 'Anchor side (the emptier side, opposite the subject)', 'default': 'left', 'options': [{'value': 'left', 'label': 'Top-left'}, {'value': 'right', 'label': 'Top-right'}]}, 'accent': {'id': 'accent', 'type': 'color', 'label': 'Accent color (serif title)', 'default': '#054BC9'}, 'readability': {'id': 'readability', 'type': 'enum', 'label': 'Text backing (new recipes use local plates)', 'default': 'scrim', 'options': [{'value': 'scrim', 'label': 'Legacy translucent scrim'}, {'value': 'plates', 'label': 'Opaque local text plates'}]}}, 'templateSha256': '0000000000000000000000000000000000000000000000000000000000000000'}

class Report:
    def __init__(self) -> None:
        self.errors, self.warnings = [], []

    def error(self, text: str) -> None:
        self.errors.append(text)

    def warn(self, text: str) -> None:
        self.warnings.append(text)


def entry(accent: str | None = None) -> dict:
    spec = {"num": "No.1", "line1": "Title", "line2": "Qualifier", "readability": "plates"}
    if accent is not None:
        spec["accent"] = accent
    return {"kind": "section-marker", "anchor": "free-band", "spec": spec,
            "outStart": 0, "outEnd": 2.5}


def images(background: str, accent: str = "#054BC9", missing: str = "") -> tuple:
    base = Image.new("RGB", (480, 853), background)
    final = base.copy()
    drawing = ImageDraw.Draw(final)
    for role, y, height, color, backing in (
            ("eyebrow", 40, 20, "#ffffff", "#0a1123"),
            ("title", 100, 45, accent, "#f6eac6"),
            ("qualifier", 180, 28, "#ffffff", "#0a1123")):
        drawing.rectangle((12, y, 150, y + height), fill=backing)
        if role == missing:
            continue
        for x in range(24, 140, 8):
            drawing.rectangle((x, y + 6, x + 2, y + height - 6), fill=color)
    return final, base


def checks_for(graphic: dict, samples: list) -> list:
    """Pure pixel tests use explicit synthetic placement observations, not receipts."""
    row = {"kind": "section-marker", "anchor": graphic["anchor"],
        "outStart": 0, "outEnd": 2.5, "canvas": [480, 853], "placedBBox": [12, 40, 150, 208]}
    evidence = PlateContext(rows=[row], graphics=[graphic], samples=samples, error="")
    with patch("audit.audit_text_plates.text_plate_contract", return_value=TEST_PLATE):
        return text_plate_results(0, graphic, evidence, composite._contrast)


class SectionMarkerContractTests(unittest.TestCase):
    def setUp(self) -> None:
        for name in ("plan_lint_contrast.text_plate_contract", "audit.audit_text_plates.text_plate_contract"):
            context = patch(name, return_value=TEST_PLATE)
            context.start()
            self.addCleanup(context.stop)

    def test_current_renderer_rejects_retired_marker(self) -> None:
        from graphics.template_contract import validate_entry
        with self.assertRaisesRegex(ValueError, "retired"):
            validate_entry(entry())

    def test_retained_role_defaults_remain_readable(self) -> None:
        contract = TEST_PLATE
        roles = effective_text_roles(entry(), contract)
        self.assertEqual([row["id"] for row in roles], ["eyebrow", "title", "qualifier"])
        self.assertEqual(roles[1]["foreground"], "#054BC9")
        self.assertEqual(contract["declared"]["readability"]["default"], "scrim")

    def test_changed_source_cannot_self_declare_qualified_roles(self) -> None:
        from graphics import template_text_contrast as contracts
        with tempfile.TemporaryDirectory() as directory:
            source = "<meta name=TEST content=inert-unqualified-role-metadata>"
            Path(directory, "section-marker.html").write_text(source + "\n<!-- changed -->")
            with patch.object(contracts, "COMPOSITIONS_DIR", directory):
                with self.assertRaisesRegex(ValueError, "hash is not qualified"):
                    text_plate_contract("section-marker")

    def test_bad_accent_fails_and_acceptable_authored_color_is_preserved(self) -> None:
        for color, fails in (("#f6eac6", True), ("#123456", False), (None, False)):
            graphic, report = entry(color), Report()
            before = copy.deepcopy(graphic)
            check_contrast({"graphicsTrack": [graphic]}, report)
            self.assertEqual(bool(report.errors), fails, report.errors)
            self.assertEqual(graphic, before)

    def test_legacy_omission_warns_without_recolor_or_migration(self) -> None:
        graphic, report = entry("#054BC9"), Report()
        del graphic["spec"]["readability"]
        graphic["anchor"] = "own-screen"
        before = copy.deepcopy(graphic)
        check_contrast({"graphicsTrack": [graphic]}, report)
        checks = text_plate_results(0, graphic, [], composite._contrast)
        self.assertFalse(report.errors)
        self.assertIn("unmeasured", report.warnings[0])
        self.assertEqual(checks[0].status, composite.WARN if hasattr(composite, "WARN") else "warn")
        self.assertEqual(graphic, before)

    def test_unknown_colors_and_treatments_fail_closed(self) -> None:
        for graphic in (entry("navy"), {**entry(), "spec": {**entry()["spec"], "readability": "guess"}}):
            report = Report()
            check_contrast({"graphicsTrack": [graphic]}, report)
            self.assertTrue(report.errors)


class SectionMarkerDecodedTests(unittest.TestCase):
    def setUp(self) -> None:
        context = patch("audit.audit_text_plates.text_plate_contract", return_value=TEST_PLATE)
        context.start()
        self.addCleanup(context.stop)

    def test_local_backings_not_footage_are_measured(self) -> None:
        for background in ("#000000", "#0a1123", "#ffffff"):
            checks = checks_for(entry(), [("mid", 1.25, images(background))])
            self.assertEqual(len(checks), 3)
            self.assertTrue(all(row.status == "pass" for row in checks), checks)
            self.assertTrue(all("decoded local plate" in row.measured for row in checks))

    def test_missing_title_never_becomes_presence_only_pass(self) -> None:
        checks = checks_for(entry(), [("mid", 1.25,
            images("#ffffff", missing="title"))])
        self.assertEqual(checks[0].status, "fail")
        self.assertIn("evidence unavailable", checks[0].measured)

    def test_bad_decoded_foreground_fails(self) -> None:
        checks = checks_for(entry("#ffffff"), [("mid", 1.25,
            images("#000000", accent="#ffffff"))])
        self.assertTrue(any(row.status == "fail" for row in checks))

    def test_partial_animation_is_disclosed_not_scored_as_full_opacity(self) -> None:
        pair = images("#ffffff")
        checks = checks_for(entry(), [("entrance", 0.1, pair),
            ("mid", 1.25, pair), ("fade", 2.4, pair)])
        self.assertEqual(sum(row.status == "pass" for row in checks), 3)
        self.assertEqual(checks[-1].status, "warn")
        self.assertIn("entrance, fade", checks[-1].measured)
        only_partial = checks_for(entry(), [("entrance", 0.1, pair)])
        self.assertEqual(only_partial[0].status, "fail")

    def test_unrelated_matching_source_pixels_do_not_prove_a_graphic(self) -> None:
        final, _ = images("#ffffff")
        checks = checks_for(entry(), [("mid", 1.25, (final, final))])
        self.assertEqual(checks[0].status, "fail")

    def test_elsewhere_lookalike_cannot_satisfy_absent_intended_marker(self) -> None:
        lookalike, base = images("#000000")
        final = base.copy()
        final.paste(lookalike.crop((0, 0, 180, 250)), (280, 500))
        checks = checks_for(entry(), [("mid", 1.25, (final, base))])
        self.assertEqual(checks[0].status, "fail")

    def test_missing_observation_and_foreign_canvas_fail_closed(self) -> None:
        graphic = entry()
        evidence = PlateContext(samples=[("mid", 1.25, images("#000000"))])
        missing = text_plate_results(0, graphic, evidence, composite._contrast)
        self.assertEqual(missing[0].status, "fail")
        evidence.error, evidence.graphics = "", [graphic]
        evidence.rows = [{"canvas": [960, 1706], "placedBBox": [24, 80, 300, 416]}]
        foreign = text_plate_results(0, graphic, evidence, composite._contrast)
        self.assertEqual(foreign[0].status, "fail")


if __name__ == "__main__":
    unittest.main()
