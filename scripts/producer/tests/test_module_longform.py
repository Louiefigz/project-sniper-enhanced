"""Retired module designs cannot execute; retained geometry stays readable."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from _common import *  # noqa: F401,F403
from graphics.template_contract import entry_errors
from graphics.visual_source_policy import ROOT

class RetiredModuleDesignTests(unittest.TestCase):
    """Both modes reject every prior module route before renderer work."""

    KINDS = ("glass-rail", "module-takeover", "module-scoreboard",
             "module-pipeline", "module-ledger-dark", "canvas-pip-list")

    def test_sources_are_absent_and_reinjected_bytes_have_no_authority(self) -> None:
        for kind in self.KINDS:
            self.assertFalse((ROOT / "templates/motion/compositions" / (kind + ".html")).exists())
            row = {"kind": kind, "outStart": 0, "outEnd": 6, "spec": {}}
            self.assertTrue(any("retired" in error for error in entry_errors(row, "<html>TEST old source</html>")))

    def test_renderer_rejects_before_launch_with_presenter_and_style_flags(self) -> None:
        for kind in self.KINDS:
            for spec in ({}, {"presenterFrame": True}, {"entrance": "rail-push", "theme": "cream"}):
                row = {"kind": kind, "outStart": 0, "outEnd": 6, "anchor": "own-screen", "spec": spec}
                with mock.patch.object(gr, "_render_to") as launch:
                    with self.assertRaisesRegex(ValueError, "retired"):
                        gr.render_entry(row, "/private/tmp/TEST-unused-retired-output")
                    launch.assert_not_called()

    def test_plan_admission_rejects_in_both_modes_and_anchors(self) -> None:
        for mode in ("short", "longform"):
            for kind in self.KINDS:
                plan = good_plan()
                plan["target"].update(mode=mode, graphicsStyle="catalog-first", excerpt=True)
                plan["graphicsTrack"] = [{"kind": kind, "outStart": 2, "outEnd": 8,
                    "anchor": "own-screen", "spec": {"presenterFrame": True}, "needsPip": True}]
                with self.subTest(mode=mode, kind=kind):
                    self.assertTrue(any("retired" in error for error in pl.lint(plan, MANIFEST).errors))

class PipHoleGeometryTests(unittest.TestCase):
    """graphics/pip_hole.py — pure geometry, fail-loud contracts."""

    # The presenter-frame cards share the takeover's EXACT hole rect/radius so
    # the reserved right band [1344..1878] fills with zero content reflow.
    _PRESENTER_KINDS = ("module-scoreboard", "module-pipeline",
                        "module-ledger-dark")

    def test_hole_rect_known_kind(self) -> None:
        self.assertEqual(phole.hole_rect("module-takeover"), (1344, 60, 534, 960))

    def test_hole_rect_presenter_frame_kinds(self) -> None:
        for kind in self._PRESENTER_KINDS:
            self.assertEqual(phole.hole_rect(kind), (1344, 60, 534, 960), kind)
            self.assertEqual(phole.HOLE_BY_KIND[kind]["radius"], 24, kind)

    def test_hole_rect_unknown_kind_raises(self) -> None:
        with self.assertRaises(ValueError):
            phole.hole_rect("statement-card")

    def test_entry_has_hole_gates_on_the_opt_in(self) -> None:
        # takeover is ALWAYS a hole, regardless of presenterFrame.
        self.assertTrue(phole.entry_has_hole({"kind": "module-takeover"}))
        self.assertTrue(phole.entry_has_hole(
            {"kind": "module-takeover", "spec": {}}))
        # presenter-frame cards: True ONLY with a truthy presenterFrame flag.
        for kind in self._PRESENTER_KINDS:
            self.assertTrue(phole.entry_has_hole(
                {"kind": kind, "spec": {"presenterFrame": True}}), kind)
            self.assertFalse(phole.entry_has_hole(
                {"kind": kind, "spec": {}}), kind)
            self.assertFalse(phole.entry_has_hole({"kind": kind}), kind)
        # A non-registered kind is never a hole, flag or not.
        self.assertFalse(phole.entry_has_hole(
            {"kind": "statement-card", "spec": {"presenterFrame": True}}))

    def test_crop_matches_hole_aspect_centred(self) -> None:
        cw, ch, cx, cy = phole.crop_for_hole(1920, 1080, "module-takeover", 0.5)
        self.assertEqual(ch, 1080)                       # full height kept
        self.assertEqual(cw % 2, 0)
        self.assertEqual(cx % 2, 0)
        # Aspect within the even-quantisation of the hole's 534/960.
        self.assertAlmostEqual(cw / ch, 534 / 960, delta=0.01)
        self.assertAlmostEqual(cx, (1920 - cw) / 2, delta=2)
        self.assertEqual(cy, 0)

    def test_crop_face_offset_clamps_inside_frame(self) -> None:
        cw, _, cx0, _ = phole.crop_for_hole(1920, 1080, "module-takeover", 0.0)
        _, _, cx1, _ = phole.crop_for_hole(1920, 1080, "module-takeover", 1.0)
        self.assertEqual(cx0, 0)
        self.assertEqual(cx1, phole._even(1920 - cw))

    def test_portrait_base_fails_loud(self) -> None:
        with self.assertRaises(ValueError):
            phole.crop_for_hole(1080, 1920, "module-takeover", 0.5)

    def test_hole_rect_scales_with_a_4k_delivery(self) -> None:
        self.assertEqual(
            phole.delivery_hole_rect("module-takeover", 3840, 2160),
            (2688, 120, 1068, 1920),
        )

    def test_bad_face_cx_fails_before_any_probe(self) -> None:
        for bad in (-0.1, 1.5, "x", True):
            with self.assertRaises(ValueError):
                phole.hole_clip_fields(
                    {"kind": "module-takeover", "faceCx": bad}, "missing.mp4")


class RenderFormatTests(unittest.TestCase):
    """graphics_render.format_for — ACTIVE hole-comps force alpha at own-screen.

    The (kind, anchor, spec) signature: module-takeover is always alpha; a
    presenter-frame card is alpha ONLY with spec.presenterFrame, else opaque."""

    def test_hole_kind_renders_alpha_even_at_own_screen(self) -> None:
        self.assertEqual(gr.format_for("module-takeover", "own-screen"),
                         ("mov", "mov"))

    def test_presenter_frame_scoreboard_forces_alpha(self) -> None:
        self.assertEqual(
            gr.format_for("module-scoreboard", "own-screen",
                          {"presenterFrame": True}),
            ("mov", "mov"))

    def test_scoreboard_without_flag_stays_opaque(self) -> None:
        # own-screen, no presenterFrame → opaque mp4 (renders as before).
        self.assertEqual(gr.format_for("module-scoreboard", "own-screen"),
                         ("mp4", "mp4"))
        self.assertEqual(
            gr.format_for("module-scoreboard", "own-screen", {}),
            ("mp4", "mp4"))

    def test_non_hole_kinds_unchanged(self) -> None:
        self.assertEqual(gr.format_for("statement-card", "own-screen"),
                         ("mp4", "mp4"))
        self.assertEqual(gr.format_for("glass-rail", "free-band"), ("mov", "mov"))

    def test_unknown_anchor_still_raises(self) -> None:
        with self.assertRaises(ValueError):
            gr.format_for("module-takeover", "floating")


class PipHoleGraphTests(unittest.TestCase):
    """graphics_stage._build_graph — the pipHole fill rides UNDER the comp."""

    def test_pip_hole_clip_fills_then_overlays(self) -> None:
        clips = [{"path": "c.mov", "outStart": 2.0, "outEnd": 8.0,
                  "anchor": "own-screen", "x": 0, "y": 0,
                  "pipHole": {"crop": (600, 1080, 660, 0),
                              "rect": (1344, 60, 534, 960)}}]
        graph, final = gs._build_graph(clips)
        self.assertIn("split[ph0a][ph0b]", graph)
        self.assertIn("[ph0b]crop=600:1080:660:0,scale=534:960:flags=lanczos[ph0s]",
                      graph)
        self.assertIn("[ph0a][ph0s]overlay=x=1344:y=60:"
                      "enable='between(t,2.0000,8.0000)'[phb0]", graph)
        # The comp overlays AFTER the fill, onto the filled base.
        self.assertIn("[phb0][ov0]overlay=enable='between(t,2.0000,8.0000)'"
                      ":format=auto[gc0]", graph)
        self.assertEqual(final, "[gc0]")

    def test_plain_clip_graph_is_byte_identical(self) -> None:
        clips = [{"path": "c.mov", "outStart": 2.0, "outEnd": 4.0,
                  "anchor": "free-band", "x": 0, "y": 0}]
        graph, final = gs._build_graph(clips)
        self.assertEqual(graph,
                         "[1:v]setpts=PTS-STARTPTS+2.0000/TB[ov0];"
                         "[0:v][ov0]overlay=enable='between(t,2.0000,4.0000)'"
                         ":format=auto[gc0]")
        self.assertEqual(final, "[gc0]")

    def test_render_all_attaches_pip_hole_fields(self) -> None:
        entry = {"kind": "module-takeover", "anchor": "own-screen",
                 "outStart": 2.0, "outEnd": 8.0, "reason": "beat", "spec": {}}
        with mock.patch.object(gs, "render_entry", return_value={
                "path": "c.mov", "cached": True, "key": "k",
                "kind": "module-takeover", "fmt": "mov"}), \
             mock.patch.object(gs, "_clip_fps", return_value=30.0), \
             mock.patch.object(gs, "_clip_dims", return_value=(1920, 1080)), \
             mock.patch.object(spl, "_clip_dims", return_value=(1920, 1080)), \
             mock.patch("graphics.pip_takeover.probe_dims",
                        return_value=(1920, 1080)):
            clips, _rows = gs._render_all(gs.GraphicsJob("base.mp4", "unused.mp4", [entry]))
        self.assertEqual(clips[0]["pipHole"]["rect"], (1344, 60, 534, 960))
        cw, ch, _, cy = clips[0]["pipHole"]["crop"]
        self.assertEqual((ch, cy), (1080, 0))
        self.assertAlmostEqual(cw / ch, 534 / 960, delta=0.01)


if __name__ == "__main__":
    unittest.main()
