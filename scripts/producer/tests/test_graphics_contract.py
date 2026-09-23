"""Graphic template intent + rendered-asset proof contracts."""
from __future__ import annotations

import hashlib
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
    """A current catalog entry; tests never reinstall a retired HTML source."""
    return {"kind": "line-swap", "outStart": 5.0, "outEnd": 8.5,
            "anchor": anchor, "reason": "TEST copy contract", "spec": spec}


class CatalogContentContractTests(unittest.TestCase):
    """Current source selection still rejects defaults and invalid copy."""

    def test_retired_statement_variants_are_not_executable(self) -> None:
        for spec in ({}, {"variant": "classic", "text": "Real copy"},
                     {"variant": "module", "statements": "ONE|TWO", "statementLands": 2},
                     {"variant": "classic", "text": "Real", "headlineLines": ""}):
            entry = {**_entry(spec), "kind": "statement-card"}
            with self.subTest(spec=spec):
                self.assertTrue(any("retired" in error for error in tc.entry_errors(entry)))

    def test_catalog_requires_both_authored_lines(self) -> None:
        for field in ("lineA", "lineB"):
            spec = {"lineA": "First claim", "lineB": "Second claim", "underlineWord": ""}
            del spec[field]
            self.assertTrue(any(field in error for error in tc.entry_errors(_entry(spec))))

    def test_current_copy_and_intentional_blank_override_are_preserved(self) -> None:
        entry = _entry({"lineA": "First claim", "lineB": "Second claim", "underlineWord": ""})
        self.assertEqual(tc.entry_errors(entry), [])
        self.assertEqual(tc.planned_copy(entry), ["First claim", "Second claim"])

    def test_default_emphasis_cannot_leak_into_authored_copy(self) -> None:
        errors = tc.entry_errors(_entry({"lineA": "First claim", "lineB": "Second claim"}))
        self.assertTrue(any("underlineWord" in error and "demo copy" in error for error in errors), errors)

    def test_unknown_variable_and_nonstring_copy_fail(self) -> None:
        for extra, needle in (({"typoText": "ignored"}, "spec.typoText"), ({"lineA": None}, "lineA")):
            entry = _entry({"lineA": "First", "lineB": "Second", "underlineWord": "", **extra})
            self.assertTrue(any(needle in error for error in tc.entry_errors(entry)))

    def test_catalog_is_source_derived_and_json_safe(self) -> None:
        from graphics.visual_source_policy import integrated_kinds
        catalog = tc.template_catalog()
        self.assertEqual(set(catalog), integrated_kinds())
        self.assertNotIn("statement-card", catalog)
        contract = catalog["line-swap"]["contentContract"]
        self.assertFalse(contract["defaultsCountAsContent"])
        self.assertIn("lineA", contract["requiredDefaultOverrides"])
        json.dumps(catalog)

    def test_plan_lint_rejects_retired_default_and_explicit_copy(self) -> None:
        for spec in ({}, {"variant": "classic", "text": "Actual copy"}):
            plan = good_plan()
            plan["graphicsTrack"] = [{**_entry(spec), "kind": "statement-card"}]
            errors = pl.lint(plan, MANIFEST).errors
            self.assertTrue(any("retired" in error for error in errors), errors)

    def test_catalog_image_requires_a_real_explicit_local_asset(self) -> None:
        for spec in ({}, {"image": "assets/nonexistent.png"}, {"image": "assets/test.png?x=1"}):
            entry = {**_entry(spec), "kind": "ui-focus-zoom"}
            self.assertTrue(any("spec.image" in error for error in tc.entry_errors(entry)))


class GraphicsStyleDecisionTests(unittest.TestCase):
    """Every scope defaults to catalog selection; no house style can override it."""

    def test_catalog_is_default_for_short_long_and_graphics_off(self) -> None:
        for mode in ("short", "longform"):
            for scope in ("trim", "light", "produced", "full"):
                for lanes in ({}, {"graphics": "off"}):
                    plan = {"target": {"mode": mode, "scope": scope, "lanes": lanes}}
                    self.assertEqual(longform.resolve_style(None, plan), "catalog-first")

    def test_retired_or_unknown_saved_and_explicit_styles_fail(self) -> None:
        for style in ("overlay-rich", "cutaway-only", "face-bridge", "wallpaper", "", False, {}):
            plan = {"target": {"graphicsStyle": style, "graphicsStyleRationale": "Does not confer approval"}}
            with self.subTest(style=style), self.assertRaisesRegex(ValueError, "retired|catalog"):
                longform.resolve_style(None, plan)
            with self.assertRaises(ValueError):
                longform.resolve_style(style, {"target": {}})

    def test_plan_lint_cannot_bypass_retired_style_admission(self) -> None:
        plan = good_plan()
        plan["target"]["graphicsStyle"] = "overlay-rich"
        self.assertTrue(any("retired" in error for error in pl.lint(plan, MANIFEST).errors))


class RenderedAssetProofTests(unittest.TestCase):
    PROBE = {"streams": [{"codec_type": "video", "codec_name": "h264",
                           "profile": "High", "pix_fmt": "yuv420p",
                           "width": 1080, "height": 1920,
                           "duration": "3.500000", "nb_frames": "105",
                           "avg_frame_rate": "30/1", "r_frame_rate": "30/1"}],
             "format": {"duration": "3.500000", "size": "8"}}

    def test_opaque_own_screen_proof_carries_copy_and_occupancy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "card.mp4")
            Path(path).write_bytes(b"not-empty")
            entry = _entry({"lineA": "The *real* copy", "lineB": "Second line", "underlineWord": ""})
            measured = {"sustainedRatio": 0.125, "sampledFrames": 35}
            with mock.patch.object(ap, "_probe", return_value=self.PROBE), \
                    mock.patch.object(ap, "_full_decode",
                                      return_value={"decoded": True}), \
                    mock.patch.object(ap, "_visible_opaque",
                                      return_value=measured):
                proof = ap.prove_rendered_asset(ap.AssetProofRequest(
                    path, entry, "mp4", (1080, 1920), 3.5, "render-key"))
            self.assertEqual(proof["copy"]["expected"], ["The real copy", "Second line"])
            self.assertEqual(proof["copy"]["renderInputKey"], "render-key")
            self.assertEqual(proof["occupancy"]["mode"], "opaque-measured-content")
            self.assertEqual(proof["occupancy"]["areaRatio"], 0.125)
            self.assertTrue(os.path.isfile(proof["sidecar"]))

    def test_alpha_asset_must_retain_alpha(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "overlay.mov")
            Path(path).write_bytes(b"not-empty")
            stream = {**self.PROBE["streams"][0], "codec_name": "prores",
                      "profile": "4444"}
            with mock.patch.object(ap, "_probe", return_value={"streams": [stream]}):
                with self.assertRaisesRegex(RuntimeError, "requires pix_fmt"):
                    ap.prove_rendered_asset(ap.AssetProofRequest(
                        path, _entry({"lineA": "Copy", "lineB": "Second line", "underlineWord": ""},
                                     anchor="free-band"),
                        "mov", (1080, 1920), 3.5, "render-key"))

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg required")
    def test_fully_transparent_overlay_fails_visible_pixel_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "transparent.mov")
            subprocess.run([
                "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                "nullsrc=s=64x64:d=0.2:r=10,format=rgba,geq=r=0:g=0:b=0:a=0",
                "-c:v", "qtrle", path,
            ], check=True)
            entry = _entry({"lineA": "Invisible", "lineB": "Second line", "underlineWord": ""},
                           anchor="free-band")
            with mock.patch.object(ap, "_validate_codec"):
                with self.assertRaisesRegex(RuntimeError, "blank/transparent"):
                    ap.prove_rendered_asset(ap.AssetProofRequest(
                        path, entry, "mov", (64, 64), 0.2,
                        "transparent-key", 10.0))

    def test_wrong_dimensions_fail_before_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "card.mp4")
            Path(path).write_bytes(b"not-empty")
            probe = {"streams": [{**self.PROBE["streams"][0], "width": 1280}]}
            with mock.patch.object(ap, "_probe", return_value=probe):
                with self.assertRaisesRegex(RuntimeError, "dimensions"):
                    ap.prove_rendered_asset(ap.AssetProofRequest(
                        path, _entry({"lineA": "Copy", "lineB": "Second line", "underlineWord": ""}),
                        "mp4", (1080, 1920), 3.5, "render-key"))

    def test_render_entry_always_returns_pre_handoff_proof(self) -> None:
        entry = _entry({"lineA": "Real copy", "lineB": "Second line", "underlineWord": ""})
        with tempfile.TemporaryDirectory() as tmp:
            def fake_render(_rel: str, _fmt: str, _spec: dict, out: str) -> None:
                Path(out).write_bytes(b"render")

            def fake_prove(request: ap.AssetProofRequest) -> dict:
                sidecar = request.path + ".proof.json"
                Path(sidecar).write_text("{}")
                return {"schemaVersion": 1, "sidecar": sidecar,
                        "asset": {"sha256": hashlib.sha256(b"render").hexdigest()}}

            with mock.patch.object(gr, "_render_to", side_effect=fake_render), \
                    mock.patch.object(gr, "prove_rendered_asset",
                                      side_effect=fake_prove) as prove:
                result = gr.render_entry(entry, tmp)
            self.assertEqual(result["proof"]["schemaVersion"], 1)
            prove.assert_called_once()

if __name__ == "__main__":
    unittest.main(verbosity=2)
