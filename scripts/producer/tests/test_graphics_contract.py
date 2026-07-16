"""Graphic template intent + rendered-asset proof contracts."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _common import MANIFEST, good_plan, gr, pl  # noqa: F401
from graphics import asset_proof as ap
from graphics import template_contract as tc
from planner import graphics_planner_longform as longform


def _entry(spec: dict, anchor: str = "own-screen") -> dict:
    return {"kind": "statement-card", "outStart": 5.0, "outEnd": 8.5,
            "anchor": anchor, "reason": "earned thesis", "spec": spec}


class StatementCardContractTests(unittest.TestCase):
    """The production defect cannot fall through to the template demo copy."""

    def assert_error(self, spec: dict, needle: str) -> None:
        errors = tc.entry_errors(_entry(spec))
        self.assertTrue(any(needle in error for error in errors), errors)

    def test_current_defect_requires_nateherk_variant(self) -> None:
        self.assert_error({
            "statements": "A DECADE AS A *SOFTWARE ENGINEER*|OBSESSED WITH *AI*",
            "statementLands": 2.1, "bg": "dark", "accent": "#D7FF3F",
        }, "variant must be explicitly")

    def test_classic_requires_explicit_text(self) -> None:
        self.assert_error({"variant": "classic", "bg": "dark"},
                          "explicit non-empty spec.text")

    def test_classic_rejects_unused_nateherk_fields(self) -> None:
        self.assert_error({"variant": "classic", "text": "Real copy",
                           "statements": "Ignored copy"},
                          "classic does not read spec.statements")

    def test_nateherk_statement_sequence_passes(self) -> None:
        entry = _entry({"variant": "nateherk",
                        "statements": "FIRST CLAIM|SECOND CLAIM",
                        "statementLands": 2.0, "bg": "dark"})
        self.assertEqual(tc.entry_errors(entry), [])
        self.assertEqual(tc.planned_copy(entry), ["FIRST CLAIM", "SECOND CLAIM"])

    def test_nateherk_requires_one_content_source(self) -> None:
        self.assert_error({"variant": "nateherk", "text": "Used?",
                           "statements": "Actually used"}, "exactly one")

    def test_multi_statement_needs_explicit_lands(self) -> None:
        self.assert_error({"variant": "nateherk",
                           "statements": "FIRST|SECOND"},
                          "statementLands needs 1 explicit")

    def test_unknown_template_variable_fails(self) -> None:
        self.assert_error({"variant": "classic", "text": "Real copy",
                           "typoText": "silently ignored"},
                          "template does not read spec.typoText")

    def test_plan_lint_blocks_default_copy_defect(self) -> None:
        plan = good_plan()
        plan["graphicsTrack"] = [_entry({
            "statements": "ENGINEER|AI SYSTEMS", "statementLands": 2.0})]
        errors = pl.lint(plan, MANIFEST).errors
        self.assertTrue(any("variant must be explicitly" in error
                            for error in errors), errors)

    def test_catalog_is_source_derived_and_json_safe(self) -> None:
        catalog = tc.template_catalog()
        statement = catalog["statement-card"]
        self.assertIn("variant", statement["variables"])
        self.assertFalse(statement["contentContract"]["defaultsCountAsContent"])
        json.dumps(catalog)


class GenericTemplateContentTests(unittest.TestCase):
    """Every non-statement template also fails closed on demo copy."""

    @staticmethod
    def _graphic(kind: str, spec: dict) -> dict:
        return {"kind": kind, "outStart": 0.0, "outEnd": 3.0,
                "anchor": "own-screen", "spec": spec}

    def test_omitted_agenda_defaults_are_rejected(self) -> None:
        errors = tc.entry_errors(self._graphic("agenda-slide", {}))
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("template demo copy would leak", errors[0])
        self.assertIn("spec.title1", errors[0])
        self.assertIn("spec.sub3", errors[0])

    def test_explicit_blanks_are_intent_and_do_not_leak(self) -> None:
        required = tc.template_catalog()["agenda-slide"]["contentContract"] \
            ["requiredDefaultOverrides"]
        spec = {key: "" for key in required}
        self.assertEqual(tc.entry_errors(self._graphic("agenda-slide", spec)), [])

    def test_asset_only_template_requires_explicit_resolved_identity(self) -> None:
        errors = tc.entry_errors(self._graphic("logo-card", {}))
        self.assertTrue(any("explicitly override spec.iconFile" in error
                            for error in errors), errors)
        self.assertEqual(tc.entry_errors(
            self._graphic("logo-card", {"iconFile": "notion.svg"})), [])
        contract = tc.template_catalog()["logo-card"]["contentContract"]
        self.assertNotIn("iconFile", contract["contentVariables"])
        self.assertEqual(contract["requiredDefaultOverrides"], [])
        asset = tc.template_catalog()["logo-card"]["assetContract"]
        self.assertTrue(asset["assetOnly"])
        self.assertEqual(asset["requiredExplicitSelectors"], ["iconFile"])

    def test_blank_asset_only_overlay_is_rejected_before_render(self) -> None:
        entry = self._graphic("icon-badge-wide", {
            "icon1": "", "icon2": "", "icon3": ""})
        errors = tc.entry_errors(entry)
        self.assertTrue(any("at least one non-empty resolved selector" in error
                            for error in errors), errors)

    def test_explicit_content_override_must_be_a_string(self) -> None:
        entry = self._graphic("widget-gauge", {"label": None})
        errors = tc.entry_errors(entry)
        self.assertTrue(any("spec.label must be a string" in error
                            for error in errors), errors)

    def test_planned_copy_is_source_derived_beyond_statement_card(self) -> None:
        entry = self._graphic("blur-tease", {
            "image": "/tmp/reference.png", "label": "The *real* reveal"})
        self.assertEqual(tc.entry_errors(entry), [])
        self.assertEqual(tc.planned_copy(entry), ["The real reveal"])

    def test_catalog_exposes_default_override_obligation(self) -> None:
        contract = tc.template_catalog()["versus-split"]["contentContract"]
        self.assertFalse(contract["defaultsCountAsContent"])
        self.assertIn("leftTitle", contract["contentVariables"])
        self.assertIn("leftTitle", contract["requiredDefaultOverrides"])


class GraphicsStyleDecisionTests(unittest.TestCase):
    """Produced longform cannot silently inherit cutaway-only grammar."""

    @staticmethod
    def _plan(**target: object) -> dict:
        return {"target": target}

    def test_produced_longform_requires_explicit_style(self) -> None:
        plan = self._plan(mode="longform", scope="produced",
                          graphicsStyleRationale="Reference uses overlays")
        with self.assertRaisesRegex(ValueError, "requires explicit"):
            longform.resolve_style(None, plan)

    def test_produced_longform_requires_rationale(self) -> None:
        plan = self._plan(mode="longform", scope="produced",
                          graphicsStyle="overlay-rich")
        with self.assertRaisesRegex(ValueError, "graphicsStyleRationale"):
            longform.resolve_style(None, plan)

    def test_target_style_and_rationale_pass(self) -> None:
        plan = self._plan(mode="longform", scope="full",
                          graphicsStyle="overlay-rich",
                          graphicsStyleRationale="Dense first-minute visual grammar")
        self.assertEqual(longform.resolve_style(None, plan), "overlay-rich")

    def test_api_style_still_requires_persisted_rationale(self) -> None:
        plan = self._plan(mode="longform", scope="produced",
                          graphicsStyleRationale="Operator chose restrained cutaways")
        self.assertEqual(longform.resolve_style("cutaway-only", plan),
                         "cutaway-only")

    def test_short_and_light_retain_legacy_default(self) -> None:
        self.assertEqual(longform.resolve_style(
            None, self._plan(mode="short", scope="produced")), "cutaway-only")
        self.assertEqual(longform.resolve_style(
            None, self._plan(mode="longform", scope="light")), "cutaway-only")

    def test_unknown_explicit_style_still_fails(self) -> None:
        plan = self._plan(mode="longform", scope="produced",
                          graphicsStyle="wallpaper",
                          graphicsStyleRationale="Bad value")
        with self.assertRaisesRegex(ValueError, "unknown graphics style"):
            longform.resolve_style(None, plan)

    def test_plan_lint_blocks_author_bypassing_the_planner(self) -> None:
        plan = good_plan()
        plan["target"].update({"mode": "longform", "scope": "produced",
                               "excerpt": True})
        errors = pl.lint(plan, MANIFEST).errors
        self.assertTrue(any("graphics style decision" in error
                            and "requires explicit" in error
                            for error in errors), errors)

    def test_graphics_off_discharge_needs_no_style_decision(self) -> None:
        plan = self._plan(mode="longform", scope="produced",
                          lanes={"graphics": "off"})
        self.assertEqual(longform.resolve_style(None, plan), "cutaway-only")


class RenderedAssetProofTests(unittest.TestCase):
    PROBE = {"streams": [{"codec_name": "h264", "pix_fmt": "yuv420p",
                           "width": 1920, "height": 1080,
                           "duration": "3.500000", "nb_frames": "105",
                           "avg_frame_rate": "30/1"}],
             "format": {"duration": "3.500000", "size": "8"}}

    def test_opaque_own_screen_proof_carries_copy_and_occupancy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "card.mp4")
            Path(path).write_bytes(b"not-empty")
            entry = _entry({"variant": "classic", "text": "The *real* copy"})
            measured = {"sustainedRatio": 0.125, "sampledFrames": 35}
            with mock.patch.object(ap, "_probe", return_value=self.PROBE), \
                    mock.patch.object(ap, "_visible_opaque",
                                      return_value=measured):
                proof = ap.prove_rendered_asset(
                    path, entry, "mp4", (1920, 1080), 3.5, "render-key")
            self.assertEqual(proof["copy"]["expected"], ["The real copy"])
            self.assertEqual(proof["copy"]["renderInputKey"], "render-key")
            self.assertEqual(proof["occupancy"]["mode"], "opaque-measured-content")
            self.assertEqual(proof["occupancy"]["areaRatio"], 0.125)
            self.assertTrue(os.path.isfile(proof["sidecar"]))

    def test_alpha_asset_must_retain_alpha(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "overlay.mov")
            Path(path).write_bytes(b"not-empty")
            with mock.patch.object(ap, "_probe", return_value=self.PROBE):
                with self.assertRaisesRegex(RuntimeError, "lost alpha"):
                    ap.prove_rendered_asset(
                        path, _entry({"variant": "classic", "text": "Copy"},
                                     anchor="free-band"),
                        "mov", (1920, 1080), 3.5, "render-key")

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg required")
    def test_fully_transparent_overlay_fails_visible_pixel_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "transparent.mov")
            subprocess.run([
                "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                "nullsrc=s=64x64:d=0.2:r=10,format=rgba,geq=r=0:g=0:b=0:a=0",
                "-c:v", "qtrle", path,
            ], check=True)
            entry = _entry({"variant": "classic", "text": "Invisible"},
                           anchor="free-band")
            with self.assertRaisesRegex(RuntimeError, "blank/transparent"):
                ap.prove_rendered_asset(
                    path, entry, "mov", (64, 64), 0.2, "transparent-key")

    def test_wrong_dimensions_fail_before_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "card.mp4")
            Path(path).write_bytes(b"not-empty")
            probe = {"streams": [{**self.PROBE["streams"][0], "width": 1280}]}
            with mock.patch.object(ap, "_probe", return_value=probe):
                with self.assertRaisesRegex(RuntimeError, "dimensions"):
                    ap.prove_rendered_asset(
                        path, _entry({"variant": "classic", "text": "Copy"}),
                        "mp4", (1920, 1080), 3.5, "render-key")

    def test_render_entry_always_returns_pre_handoff_proof(self) -> None:
        entry = _entry({"variant": "classic", "text": "Real copy"})
        with tempfile.TemporaryDirectory() as tmp:
            def fake_render(_rel: str, _fmt: str, _spec: dict, out: str) -> None:
                Path(out).write_bytes(b"render")

            with mock.patch.object(gr, "_render_to", side_effect=fake_render), \
                    mock.patch.object(gr, "prove_rendered_asset",
                                      return_value={"schemaVersion": 1}) as prove:
                result = gr.render_entry(entry, tmp)
            self.assertEqual(result["proof"], {"schemaVersion": 1})
            prove.assert_called_once()

    def test_hyperframes_runtime_is_version_pinned(self) -> None:
        with mock.patch.object(gr.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0, stderr="", stdout="")
            with mock.patch.object(gr.os.path, "exists", return_value=True):
                gr._render_to("compositions/card.html", "mp4", {}, "/tmp/card.mp4")
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ["npx", "--yes", "hyperframes@0.7.33"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
