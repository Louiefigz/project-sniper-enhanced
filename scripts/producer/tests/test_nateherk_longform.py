#!/usr/bin/env python3
"""NATEHERK longform lane tests (NATEHERK_STUDY.md §5 items 8-9).

Item 8 — glass-rail 'rail-push' entrance (field width-grows 0->33%W in 0.33s
power-out beside the live face; headline at 65% growth; rows +0.25/+0.40s
container-first) + the cream/ink light skin. Item 9 — nateherk-takeover
(near-black canvas + grid, transparent face hole the renderer fills, dual
semantic accents, in-card payoffs) + the pip_hole renderer wire. OPERATOR
ADJUDICATION 2026-07-10: both moves are LEGAL FOR LONGFORM, BANNED FOR
SHORTS — the lint matrix below pins that. Contract surface only — renders +
frame timing verification run out-of-suite (same doctrine as the jaden /
nateherk-pack tests). Every default keeps pre-item behavior (additive law).
"""
import unittest
from pathlib import Path
from unittest import mock

from _common import *  # noqa: F401,F403

_REPO = Path(__file__).resolve().parents[3]           # PROJECT_SNIPER
_MOTION = _REPO / "templates" / "motion"
_COMPS = _MOTION / "compositions"


class NateherkLaneTokensTests(unittest.TestCase):
    """Item 8/9 tokens: semantic dual accent + cream skin + dark canvas."""

    def test_tokens_css_carries_the_lane(self) -> None:
        css = (_MOTION / "tokens.css").read_text(encoding="utf-8")
        for tok in ("--accent-result: #c6f542",     # lime = hero/results
                    "--accent-process: #35b6d9",    # cyan = process/status
                    "--accent-compare: #9aa0a6",    # gray = comparison
                    "--rail-cream: #f0f0e6",        # T-B light field
                    "--rail-cream-ink: #1a1a1a",
                    "--nateherk-canvas: #0c1014"):  # dark takeover canvas
            self.assertIn(tok, css)
        self.assertIn("--pop-in-dur", css)          # jaden twin untouched


class RailPushCompTests(unittest.TestCase):
    """Item 8 — glass-rail entrance/theme contract; classic path intact."""

    def setUp(self) -> None:
        self.html = (_COMPS / "glass-rail.html").read_text(encoding="utf-8")

    def test_new_variables_default_to_the_old_build(self) -> None:
        self.assertIn('"id":"entrance","type":"enum","label":"Entrance",'
                      '"default":"slide"', self.html)
        self.assertIn('"id":"theme","type":"enum","label":"Skin",'
                      '"default":"glass"', self.html)

    def test_rail_push_carries_the_measured_timings(self) -> None:
        # T-B: grow 0->33%W (634px of 1920) in 0.33s power-out; headline at
        # 65% of the grow; rows +0.25s container / +0.40s text after it.
        for token in ("const RAIL_PUSH_S = 0.33",
                      "const HEADLINE_AT_GROWTH = 0.65",
                      "const ROW_CONTAINER_DELAY_S = 0.25",
                      "const ROW_TEXT_DELAY_S = 0.4",
                      'ease: "power2.out" }, 0)',
                      "width: 634"):
            self.assertIn(token, self.html)
        self.assertIn("#rail-field", self.html)

    def test_light_skin_uses_the_cream_tokens(self) -> None:
        self.assertIn("var(--rail-cream, #f0f0e6)", self.html)
        self.assertIn("var(--rail-cream-ink, #1a1a1a)", self.html)
        self.assertIn("var(--accent-process, #35b6d9)", self.html)

    def test_classic_build_survives_verbatim(self) -> None:
        self.assertIn("back.out(1.6)", self.html)      # stamp build
        self.assertIn("back.out(2.6)", self.html)      # chip pop
        self.assertIn("skeletonFirst", self.html)      # rank-2 opt-in
        self.assertIn("blurRecede", self.html)         # T-D exit opt-in


class NateherkTakeoverCompTests(unittest.TestCase):
    """Item 9 — the dark takeover comp: canvas, hole, accents, payoffs."""

    def setUp(self) -> None:
        self.html = (_COMPS / "nateherk-takeover.html").read_text(encoding="utf-8")

    def test_canvas_and_grid(self) -> None:
        self.assertIn("var(--nateherk-canvas, #0c1014)", self.html)
        self.assertIn("repeating-linear-gradient", self.html)

    def test_hole_geometry_matches_the_pip_hole_registry(self) -> None:
        # The comp masks the canvas out of this rect + draws the ring at it;
        # the renderer fills the SAME rect (graphics/pip_hole.py). A drift
        # here means the footage and the hole disagree — pin both sides.
        hole = phole.HOLE_BY_KIND["nateherk-takeover"]
        x, y, w, h = hole["rect"]
        self.assertEqual((x, y, w, h), (1344, 60, 534, 960))
        for css in (f"left: {x}px", f"top: {y}px",
                    f"width: {w}px", f"height: {h}px",
                    f"border-radius: {hole['radius']}px"):
            self.assertIn(css, self.html)
        # ~28%W x 89%H per the study (±1% band after even-quantisation).
        self.assertAlmostEqual(w / 1920, 0.28, delta=0.01)
        self.assertAlmostEqual(h / 1080, 0.89, delta=0.01)
        # The evenodd mask actually cuts the hole out of the canvas.
        self.assertIn("fill-rule='evenodd'", self.html)
        self.assertIn("mask-image", self.html)

    def test_dual_semantic_accents(self) -> None:
        self.assertIn("var(--accent-result, #c6f542)", self.html)
        self.assertIn("var(--accent-process, #35b6d9)", self.html)
        self.assertIn("var(--accent-compare, #9aa0a6)", self.html)

    def test_in_card_payoff_constants(self) -> None:
        # Rank 7-8: hero 0.4s power2.out / comparison 0.8s power1.out /
        # chips 85ms sweep / delta only after both bars.
        for token in ("const HERO_FILL_S = 0.4",
                      "const COMPARE_FILL_S = 0.8",
                      "const CHIP_SWEEP_S = 0.085",
                      "const DELTA_BEAT_S = 0.1",
                      "power1.out"):
            self.assertIn(token, self.html)
        self.assertIn("fillAt + COMPARE_FILL_S + DELTA_BEAT_S", self.html)

    def test_skeleton_eyebrow_and_module_lands_vars(self) -> None:
        for var in ('"id":"eyebrow"', '"id":"headlineLines"', '"id":"heroPct"',
                    '"id":"comparePct"', '"id":"deltaChip"', '"id":"chips"',
                    '"id":"evidenceSource"', '"id":"moduleLands"'):
            self.assertIn(var, self.html)
        self.assertIn('"id":"exit","type":"enum","label":"Exit","default":"hold"',
                      self.html)
        # Skeleton-first grammar: the bars shell ramps as one unit and the
        # fills start +SKELETON_GAP_S later (the payoff is a width fill, so
        # the comp uses textRamp + the gap token rather than skeletonFirst()).
        for helper in ("textRamp", "blurRecede",
                       "EYEBROW_LEAD_S", "M.SKELETON_GAP_S"):
            self.assertIn(helper, self.html)
        self.assertIn("const fillAt = tB + M.SKELETON_GAP_S", self.html)
        self.assertIn('window.__timelines["nateherk-takeover"]', self.html)


class PresenterFrameCompTests(unittest.TestCase):
    """The opt-in framed presenter-container on the 3 dark cards.

    Backward-compat law: the flag is declared (template_contract accepts it) and
    defaults false; the mask + ring are scoped to .has-presenter and copy the
    takeover's geometry VERBATIM, matching the pip_hole registry rect exactly."""

    # kind -> (id prefix, root id)
    _COMPS = {
        "nateherk-scoreboard": "nsb",
        "nateherk-pipeline": "npl",
        "nateherk-ledger-dark": "nld",
    }

    def _html(self, kind: str) -> str:
        return (_COMPS / f"{kind}.html").read_text(encoding="utf-8")

    def test_presenter_frame_var_declared_and_defaults_false(self) -> None:
        for kind in self._COMPS:
            html = self._html(kind)
            self.assertIn('"id":"presenterFrame","type":"boolean"', html, kind)
            self.assertIn('"default":false', html, kind)
            # It reads the flag onto the root class, mirroring exit/moduleLands.
            self.assertIn("has-presenter", html, kind)

    def test_ring_geometry_matches_the_registry_rect(self) -> None:
        for kind, pre in self._COMPS.items():
            html = self._html(kind)
            hole = phole.HOLE_BY_KIND[kind]
            x, y, w, h = hole["rect"]
            self.assertEqual((x, y, w, h), (1344, 60, 534, 960), kind)
            # The ring element + its geometry, scoped to .has-presenter.
            self.assertIn(f"#{pre}-face-slot", html, kind)
            for css in (f"left: {x}px", f"top: {y}px",
                        f"width: {w}px", f"height: {h}px",
                        f"border-radius: {hole['radius']}px"):
                self.assertIn(css, html, f"{kind}: {css}")

    def test_mask_cuts_the_hole_out_of_the_canvas(self) -> None:
        for kind, pre in self._COMPS.items():
            html = self._html(kind)
            # The evenodd mask + the SAME rounded-rect path as the takeover.
            self.assertIn("fill-rule='evenodd'", html, kind)
            self.assertIn("mask-image", html, kind)
            self.assertIn(
                "M1368 60h486a24 24 0 0 1 24 24v912a24 24 0 0 1 -24 "
                "24h-486a24 24 0 0 1 -24 -24V84a24 24 0 0 1 24 -24z", html, kind)
            # Both the mask and the ring are gated behind the opt-in class.
            self.assertIn(f"#{pre}-root.has-presenter #{pre}-canvas", html, kind)
            self.assertIn(f"#{pre}-root.has-presenter #{pre}-face-slot", html, kind)


class PipHoleGeometryTests(unittest.TestCase):
    """graphics/pip_hole.py — pure geometry, fail-loud contracts."""

    # The presenter-frame cards share the takeover's EXACT hole rect/radius so
    # the reserved right band [1344..1878] fills with zero content reflow.
    _PRESENTER_KINDS = ("nateherk-scoreboard", "nateherk-pipeline",
                        "nateherk-ledger-dark")

    def test_hole_rect_known_kind(self) -> None:
        self.assertEqual(phole.hole_rect("nateherk-takeover"), (1344, 60, 534, 960))

    def test_hole_rect_presenter_frame_kinds(self) -> None:
        for kind in self._PRESENTER_KINDS:
            self.assertEqual(phole.hole_rect(kind), (1344, 60, 534, 960), kind)
            self.assertEqual(phole.HOLE_BY_KIND[kind]["radius"], 24, kind)

    def test_hole_rect_unknown_kind_raises(self) -> None:
        with self.assertRaises(ValueError):
            phole.hole_rect("statement-card")

    def test_entry_has_hole_gates_on_the_opt_in(self) -> None:
        # takeover is ALWAYS a hole, regardless of presenterFrame.
        self.assertTrue(phole.entry_has_hole({"kind": "nateherk-takeover"}))
        self.assertTrue(phole.entry_has_hole(
            {"kind": "nateherk-takeover", "spec": {}}))
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
        cw, ch, cx, cy = phole.crop_for_hole(1920, 1080, "nateherk-takeover", 0.5)
        self.assertEqual(ch, 1080)                       # full height kept
        self.assertEqual(cw % 2, 0)
        self.assertEqual(cx % 2, 0)
        # Aspect within the even-quantisation of the hole's 534/960.
        self.assertAlmostEqual(cw / ch, 534 / 960, delta=0.01)
        self.assertAlmostEqual(cx, (1920 - cw) / 2, delta=2)
        self.assertEqual(cy, 0)

    def test_crop_face_offset_clamps_inside_frame(self) -> None:
        cw, _, cx0, _ = phole.crop_for_hole(1920, 1080, "nateherk-takeover", 0.0)
        _, _, cx1, _ = phole.crop_for_hole(1920, 1080, "nateherk-takeover", 1.0)
        self.assertEqual(cx0, 0)
        self.assertEqual(cx1, phole._even(1920 - cw))

    def test_portrait_base_fails_loud(self) -> None:
        with self.assertRaises(ValueError):
            phole.crop_for_hole(1080, 1920, "nateherk-takeover", 0.5)

    def test_hole_rect_scales_with_a_4k_delivery(self) -> None:
        self.assertEqual(
            phole.delivery_hole_rect("nateherk-takeover", 3840, 2160),
            (2688, 120, 1068, 1920),
        )

    def test_bad_face_cx_fails_before_any_probe(self) -> None:
        for bad in (-0.1, 1.5, "x", True):
            with self.assertRaises(ValueError):
                phole.hole_clip_fields(
                    {"kind": "nateherk-takeover", "faceCx": bad}, "missing.mp4")


class RenderFormatTests(unittest.TestCase):
    """graphics_render.format_for — ACTIVE hole-comps force alpha at own-screen.

    The (kind, anchor, spec) signature: nateherk-takeover is always alpha; a
    presenter-frame card is alpha ONLY with spec.presenterFrame, else opaque."""

    def test_hole_kind_renders_alpha_even_at_own_screen(self) -> None:
        self.assertEqual(gr.format_for("nateherk-takeover", "own-screen"),
                         ("mov", "mov"))

    def test_presenter_frame_scoreboard_forces_alpha(self) -> None:
        self.assertEqual(
            gr.format_for("nateherk-scoreboard", "own-screen",
                          {"presenterFrame": True}),
            ("mov", "mov"))

    def test_scoreboard_without_flag_stays_opaque(self) -> None:
        # own-screen, no presenterFrame → opaque mp4 (renders as before).
        self.assertEqual(gr.format_for("nateherk-scoreboard", "own-screen"),
                         ("mp4", "mp4"))
        self.assertEqual(
            gr.format_for("nateherk-scoreboard", "own-screen", {}),
            ("mp4", "mp4"))

    def test_non_hole_kinds_unchanged(self) -> None:
        self.assertEqual(gr.format_for("statement-card", "own-screen"),
                         ("mp4", "mp4"))
        self.assertEqual(gr.format_for("glass-rail", "free-band"), ("mov", "mov"))

    def test_unknown_anchor_still_raises(self) -> None:
        with self.assertRaises(ValueError):
            gr.format_for("nateherk-takeover", "floating")


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
        entry = {"kind": "nateherk-takeover", "anchor": "own-screen",
                 "outStart": 2.0, "outEnd": 8.0, "reason": "beat", "spec": {}}
        with mock.patch.object(gs, "render_entry", return_value={
                "path": "c.mov", "cached": True, "key": "k",
                "kind": "nateherk-takeover", "fmt": "mov"}), \
             mock.patch.object(gs, "_clip_dims", return_value=(1920, 1080)), \
             mock.patch.object(spl, "_clip_dims", return_value=(1920, 1080)), \
             mock.patch("graphics.pip_takeover.probe_dims",
                        return_value=(1920, 1080)):
            clips, _rows = gs._render_all([entry], None, "base.mp4")
        self.assertEqual(clips[0]["pipHole"]["rect"], (1344, 60, 534, 960))
        cw, ch, _, cy = clips[0]["pipHole"]["crop"]
        self.assertEqual((ch, cy), (1080, 0))
        self.assertAlmostEqual(cw / ch, 534 / 960, delta=0.01)


def _longform_plan(graphics: list) -> dict:
    return {
        "planVersion": 1,
        "target": {"mode": "longform", "durationTargetS": 60, "excerpt": True},
        "cutTrack": [{"sourceId": "raw-1", "start": i * 3.0,
                      "end": (i + 1) * 3.0, "speed": 1.0} for i in range(20)],
        "reframe": {"strategy": "face"},
        "captions": {"burn": False, "style": "line"},
        "graphicsTrack": graphics,
    }


def _rail_entry(entrance: str | None, hold: float = 4.5) -> dict:
    spec = {"eyebrow": "The pipeline", "title1": "Intake", "sub1": "raw in"}
    if entrance is not None:
        spec["entrance"] = entrance
    return {"outStart": 4.0, "outEnd": 4.0 + hold, "kind": "glass-rail",
            "anchor": "free-band", "reason": "system map", "spec": spec}


def _takeover_entry(hold: float = 9.0, anchor: str = "own-screen") -> dict:
    return {"outStart": 4.0, "outEnd": 4.0 + hold, "kind": "nateherk-takeover",
            "anchor": anchor, "reason": "benchmark beat",
            "spec": {"eyebrow": "ULTRA", "headlineLines": "ONE RUN.|FOUR AGENTS.",
                     "heroPct": 92, "comparePct": 86}}


class NateherkLintMatrixTests(unittest.TestCase):
    """The adjudication as lint: LONGFORM legal, shorts = ERROR (both moves)."""

    def _short_plan(self, graphics: list) -> dict:
        plan = good_plan()
        plan["graphicsTrack"] = graphics
        return plan

    # -- item 8: rail-push entrance --------------------------------------
    def test_rail_push_is_clean_on_longform(self) -> None:
        rep = pl.lint(_longform_plan([_rail_entry("rail-push")]), MANIFEST)
        self.assertFalse([e for e in rep.errors if "rail-push" in e], rep.errors)

    def test_rail_push_is_an_error_on_shorts(self) -> None:
        rep = pl.lint(self._short_plan([_rail_entry("rail-push", hold=4.0)]),
                      MANIFEST)
        self.assertTrue(any("rail-push" in e and "LONGFORM-ONLY" in e
                            for e in rep.errors), rep.errors)

    def test_default_slide_entrance_is_clean_on_shorts(self) -> None:
        rep = pl.lint(self._short_plan([_rail_entry("slide", hold=4.0)]), MANIFEST)
        self.assertFalse([e for e in rep.errors if "entrance" in e], rep.errors)

    def test_unknown_entrance_fails_loud(self) -> None:
        rep = pl.lint(_longform_plan([_rail_entry("teleport")]), MANIFEST)
        self.assertTrue(any("spec.entrance 'teleport'" in e for e in rep.errors),
                        rep.errors)

    def test_entrance_on_a_non_rail_kind_fails_loud(self) -> None:
        entry = _takeover_entry()
        entry["spec"]["entrance"] = "rail-push"
        rep = pl.lint(_longform_plan([entry]), MANIFEST)
        self.assertTrue(any("glass-rail variable" in e for e in rep.errors),
                        rep.errors)

    # -- item 9: nateherk-takeover hole-comp -----------------------------
    def test_takeover_is_clean_on_longform(self) -> None:
        rep = pl.lint(_longform_plan([_takeover_entry()]), MANIFEST)
        self.assertFalse(
            [e for e in rep.errors if "nateherk-takeover" in e], rep.errors)

    def test_takeover_is_an_error_on_shorts(self) -> None:
        rep = pl.lint(self._short_plan([_takeover_entry(hold=2.0)]), MANIFEST)
        self.assertTrue(any("nateherk-takeover" in e and "LONGFORM-ONLY" in e
                            for e in rep.errors), rep.errors)

    def test_takeover_requires_own_screen(self) -> None:
        rep = pl.lint(_longform_plan([_takeover_entry(anchor="free-band")]),
                      MANIFEST)
        self.assertTrue(any("own-screen" in e and "nateherk-takeover" in e
                            for e in rep.errors), rep.errors)

    def test_takeover_rides_hold_max_not_the_takeover_ceiling(self) -> None:
        # 11.0s hold: > takeover_max_s (10.5 longform) but <= hold_max_s
        # (11.0) — the face stays visible, so no takeover-ceiling error.
        rep = pl.lint(_longform_plan([_takeover_entry(hold=11.0)]), MANIFEST)
        self.assertFalse([e for e in rep.errors if "exceeds" in e], rep.errors)

    def test_needs_pip_on_a_hole_kind_is_not_the_unwired_error(self) -> None:
        entry = _takeover_entry()
        entry["needsPip"] = True
        rep = pl.lint(_longform_plan([entry]), MANIFEST)
        self.assertFalse([e for e in rep.errors if "unwired" in e], rep.errors)

    # -- the old guardrail stays up for everything else -------------------
    def test_canvas_pip_list_still_blocked_unwired(self) -> None:
        entry = {"outStart": 4.0, "outEnd": 10.0, "kind": "canvas-pip-list",
                 "anchor": "own-screen", "reason": "doors",
                 "spec": {"item1": "Door one"}}
        rep = pl.lint(_longform_plan([entry]), MANIFEST)
        self.assertTrue(any("unwired" in e for e in rep.errors), rep.errors)

    def test_needs_pip_on_other_kinds_still_blocked(self) -> None:
        entry = {"outStart": 4.0, "outEnd": 10.0, "kind": "statement-card",
                 "anchor": "own-screen", "reason": "beat",
                 "spec": {"text": "x"}, "needsPip": True}
        rep = pl.lint(_longform_plan([entry]), MANIFEST)
        self.assertTrue(any("unwired" in e for e in rep.errors), rep.errors)


class PresenterFrameLintGateTests(unittest.TestCase):
    """plan_lint_nateherk._check_hole_kind routes on entry_has_hole, so the
    longform+own-screen gate fires ONLY for an active presenter frame — a plain
    opt-out scoreboard is untouched (backward compat)."""

    def _entry(self, presenter: bool, anchor: str = "own-screen") -> dict:
        spec = {"heroValue": "97%"}
        if presenter:
            spec["presenterFrame"] = True
        return {"outStart": 4.0, "outEnd": 12.0, "kind": "nateherk-scoreboard",
                "anchor": anchor, "reason": "scoreboard beat", "spec": spec}

    def test_plain_scoreboard_has_no_hole_gate(self) -> None:
        rep = pl.Report()
        pln.check_nateherk_entry("g0", self._entry(False), "shorts", rep)
        self.assertEqual(rep.errors, [])

    def test_presenter_frame_scoreboard_is_longform_only(self) -> None:
        rep = pl.Report()
        pln.check_nateherk_entry("g0", self._entry(True), "shorts", rep)
        self.assertTrue(any("LONGFORM-ONLY" in e for e in rep.errors), rep.errors)

    def test_presenter_frame_scoreboard_requires_own_screen(self) -> None:
        rep = pl.Report()
        pln.check_nateherk_entry(
            "g0", self._entry(True, anchor="free-band"), "longform", rep)
        self.assertTrue(any("own-screen" in e for e in rep.errors), rep.errors)

    def test_presenter_frame_scoreboard_clean_on_longform_own_screen(self) -> None:
        rep = pl.Report()
        pln.check_nateherk_entry("g0", self._entry(True), "longform", rep)
        self.assertEqual(rep.errors, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
