"""plan_lint tests (split from selftest.py)."""
import copy
import unittest

from _common import *  # noqa: F401,F403


class PlanLintTests(unittest.TestCase):
    """Every editorial gate must fire; a known-good plan must pass clean."""

    def _errors(self, plan: dict) -> list[str]:
        return pl.lint(plan, MANIFEST).errors

    def assert_fires(self, plan: dict, needle: str) -> None:
        errors = self._errors(plan)
        self.assertTrue(any(needle in e for e in errors),
                        f"expected {needle!r} in errors: {errors}")

    def test_good_plan_passes_clean(self) -> None:
        self.assertEqual(self._errors(good_plan()), [])

    def test_trim_short_does_not_require_a_title_card(self) -> None:
        plan = good_plan()
        plan["target"]["scope"] = "trim"
        plan["titleCards"] = []
        plan["brollTrack"] = []
        plan["captions"]["burn"] = False
        plan["music"] = {"enabled": False}
        self.assertEqual(self._errors(plan), [])

    def test_longform_youtube_destination_matches_starter_vocabulary(self) -> None:
        plan = good_plan()
        plan["target"].update({
            "mode": "longform",
            "scope": "trim",
            "platforms": ["youtube"],
            "durationTargetS": 600,
        })
        plan["cutTrack"] = [{
            "sourceId": "raw-1", "start": 0.0, "end": 600.0, "speed": 1.0,
        }]
        plan["reframe"] = {"strategy": "none"}
        plan["titleCards"] = []
        plan["brollTrack"] = []
        plan["captions"] = {"burn": False, "style": "line"}
        plan["music"] = {"enabled": False}
        manifest = copy.deepcopy(MANIFEST)
        manifest["sources"][0]["duration"] = 600
        self.assertEqual(pl.lint(plan, manifest).errors, [])

    def test_hook_too_many_words(self) -> None:
        plan = good_plan()
        plan["titleCards"][0]["text"] = "a b c d e f g h i"    # 9 words
        self.assert_fires(plan, "words (max")

    def test_hook_too_many_lines(self) -> None:
        plan = good_plan()
        plan["titleCards"][0]["text"] = "a\nb\nc"               # 3 lines
        self.assert_fires(plan, "lines (max")

    def test_hook_line_too_long(self) -> None:
        plan = good_plan()
        plan["titleCards"][0]["text"] = "abcdefghijklmnopqrstuvwxyz1234"   # 30 chars
        self.assert_fires(plan, "chars")

    def test_title_card_overlap(self) -> None:
        plan = good_plan()
        plan["titleCards"].append({"outStart": 2.0, "outEnd": 4.0,
                                   "text": "Second card ok", "style": "lower"})
        self.assert_fires(plan, "overlaps another title card")

    def test_broll_missing_reason(self) -> None:
        plan = good_plan()
        plan["brollTrack"][0]["reason"] = ""
        self.assert_fires(plan, "missing reason")

    def test_broll_under_title_card(self) -> None:
        plan = good_plan()
        plan["brollTrack"][0].update({"outStart": 1.0, "outEnd": 2.0})   # under hook [0,2.5]
        self.assert_fires(plan, "under a title card")

    def test_music_bad_variants(self) -> None:
        plan = good_plan()
        plan["music"]["variants"] = ["loud"]
        self.assert_fires(plan, "music.variants")

    def test_unknown_source_id(self) -> None:
        plan = good_plan()
        plan["cutTrack"][0]["sourceId"] = "raw-9"
        self.assert_fires(plan, "not in manifest")

    def test_speed_over_cap(self) -> None:
        plan = good_plan()
        plan["cutTrack"][0]["speed"] = 1.5      # short cap is 1.25
        self.assert_fires(plan, "exceeds mode cap")

    def test_duration_under_floor(self) -> None:
        plan = good_plan()
        plan["cutTrack"] = [{"sourceId": "raw-1", "start": 0.0, "end": 5.0, "speed": 1.0}]
        self.assert_fires(plan, "below mode floor")

    def test_excerpt_downgrades_floor_to_warning(self) -> None:
        # A deliberate excerpt (first-N-minutes review render) renders despite
        # being under the full-video floor: the floor is a warning, not an error.
        plan = good_plan()
        plan["cutTrack"] = [{"sourceId": "raw-1", "start": 0.0, "end": 5.0, "speed": 1.0}]
        plan.setdefault("target", {})["excerpt"] = True
        rep = pl.lint(plan, MANIFEST)
        self.assertFalse(any("below mode floor" in e for e in rep.errors), rep.errors)
        self.assertTrue(any("below mode floor" in w for w in rep.warnings), rep.warnings)

    def test_same_source_overlap_rejected(self) -> None:
        # Edge X14: replayed range would render caption-less on the repeat.
        plan = good_plan()
        plan["cutTrack"] = [
            {"sourceId": "raw-1", "start": 0.0, "end": 20.0, "speed": 1.0},
            {"sourceId": "raw-1", "start": 15.0, "end": 35.0, "speed": 1.0},
        ]
        self.assert_fires(plan, "overlaps cutTrack[0]")

    def test_short_mode_rejects_strategy_none(self) -> None:
        # Edge X15: 16:9 short would mis-scale the 1080x1920-authored captions.
        plan = good_plan()
        plan["reframe"] = {"strategy": "none"}
        self.assert_fires(plan, "requires a 9:16 reframe strategy")

    def test_caption_band_offset_bounded(self) -> None:
        # Edge C12: band shift is up-only and bounded.
        plan = good_plan()
        plan["captions"]["bandYOffsetPx"] = 900
        self.assert_fires(plan, "bandYOffsetPx")
        plan["captions"]["bandYOffsetPx"] = 200
        self.assertEqual(self._errors(plan), [])


class ReframeLintTests(unittest.TestCase):
    """The reframe LAYOUT CONTRACT (fill/split, 2026-07-09) accept/reject matrix."""

    def _errors(self, plan: dict) -> list[str]:
        return pl.lint(plan, MANIFEST).errors

    def assert_fires(self, plan: dict, needle: str) -> None:
        errors = self._errors(plan)
        self.assertTrue(any(needle in e for e in errors),
                        f"expected {needle!r} in errors: {errors}")

    def _split_plan(self) -> dict:
        plan = good_plan()
        plan["reframe"] = {"layout": "split", "split": {
            "top": {"crop": [0.05, 0.55, 0.18, 0.32], "frac": 0.5},
            "bottom": {"crop": [0.30, 0.05, 0.65, 0.85]}}}
        return plan

    # ---- accepts -----------------------------------------------------------
    def test_split_plan_passes_clean(self) -> None:
        self.assertEqual(self._errors(self._split_plan()), [])

    def test_split_default_frac_passes(self) -> None:
        plan = self._split_plan()
        del plan["reframe"]["split"]["top"]["frac"]
        self.assertEqual(self._errors(plan), [])

    def test_track_false_accepted(self) -> None:
        plan = self._split_plan()
        plan["reframe"]["track"] = False
        self.assertEqual(self._errors(plan), [])

    def test_fill_manual_crop_passes(self) -> None:
        plan = good_plan()
        plan["reframe"] = {"layout": "fill", "crop": [0.30, 0.05, 0.65, 0.85]}
        self.assertEqual(self._errors(plan), [])

    def test_fill_crop_without_layout_key_passes(self) -> None:
        # layout absent = fill; the crop override still applies.
        plan = good_plan()
        plan["reframe"] = {"strategy": "face", "crop": [0.1, 0.1, 0.5, 0.5]}
        self.assertEqual(self._errors(plan), [])

    # ---- layout / track ----------------------------------------------------
    def test_unknown_layout_rejected(self) -> None:
        plan = good_plan()
        plan["reframe"] = {"layout": "stacked"}
        self.assert_fires(plan, "reframe.layout 'stacked'")

    def test_track_true_rejected(self) -> None:
        plan = self._split_plan()
        plan["reframe"]["track"] = True
        self.assert_fires(plan, "tracker not yet wired")

    # ---- split shape -------------------------------------------------------
    def test_split_requires_short_mode(self) -> None:
        plan = self._split_plan()
        plan["target"]["mode"] = "longform"
        self.assert_fires(plan, "9:16 shorts only")

    def test_split_missing_bottom_rejected(self) -> None:
        plan = self._split_plan()
        del plan["reframe"]["split"]["bottom"]
        self.assert_fires(plan, "BOTH 'top' and 'bottom'")

    def test_split_missing_dict_rejected(self) -> None:
        plan = good_plan()
        plan["reframe"] = {"layout": "split"}
        self.assert_fires(plan, "BOTH 'top' and 'bottom'")

    def test_split_unknown_cell_rejected(self) -> None:
        plan = self._split_plan()
        plan["reframe"]["split"]["middle"] = {"crop": [0.1, 0.1, 0.5, 0.5]}
        self.assert_fires(plan, "unknown cells")

    def test_split_cell_without_crop_rejected(self) -> None:
        plan = self._split_plan()
        plan["reframe"]["split"]["bottom"] = {}
        self.assert_fires(plan, "reframe.split.bottom")

    def test_split_with_strategy_rejected(self) -> None:
        plan = self._split_plan()
        plan["reframe"]["strategy"] = "face"
        self.assert_fires(plan, "does not apply to layout 'split'")

    def test_split_with_fill_crop_rejected(self) -> None:
        plan = self._split_plan()
        plan["reframe"]["crop"] = [0.1, 0.1, 0.5, 0.5]
        self.assert_fires(plan, "fill-layout override")

    def test_split_dict_under_fill_layout_rejected(self) -> None:
        plan = self._split_plan()
        plan["reframe"]["layout"] = "fill"
        self.assert_fires(plan, "requires reframe.layout 'split'")

    # ---- crop rects --------------------------------------------------------
    def test_crop_wrong_arity_rejected(self) -> None:
        plan = self._split_plan()
        plan["reframe"]["split"]["top"]["crop"] = [0.1, 0.1, 0.5]
        self.assert_fires(plan, "4 numbers")

    def test_crop_non_numeric_rejected(self) -> None:
        plan = self._split_plan()
        plan["reframe"]["split"]["top"]["crop"] = [0.1, "0.1", 0.5, 0.5]
        self.assert_fires(plan, "4 numbers")

    def test_crop_negative_origin_rejected(self) -> None:
        plan = self._split_plan()
        plan["reframe"]["split"]["bottom"]["crop"] = [-0.1, 0.1, 0.5, 0.5]
        self.assert_fires(plan, "x/y must be in [0,1]")

    def test_crop_too_thin_rejected(self) -> None:
        plan = self._split_plan()
        plan["reframe"]["split"]["top"]["crop"] = [0.1, 0.1, 0.02, 0.5]
        self.assert_fires(plan, "w/h must be >= 0.05")

    def test_crop_leaving_frame_rejected(self) -> None:
        plan = self._split_plan()
        plan["reframe"]["split"]["bottom"]["crop"] = [0.5, 0.1, 0.6, 0.5]
        self.assert_fires(plan, "leaves the source frame")

    def test_fill_crop_bad_rect_rejected(self) -> None:
        plan = good_plan()
        plan["reframe"] = {"crop": [0.5, 0.5, 0.6, 0.6]}
        self.assert_fires(plan, "reframe.crop: rect leaves the source frame")

    def test_fill_crop_longform_rejected(self) -> None:
        plan = good_plan()
        plan["target"]["mode"] = "longform"
        plan["reframe"] = {"crop": [0.1, 0.1, 0.5, 0.5]}
        self.assert_fires(plan, "not applicable to longform")

    # ---- frac --------------------------------------------------------------
    def test_frac_below_range_rejected(self) -> None:
        plan = self._split_plan()
        plan["reframe"]["split"]["top"]["frac"] = 0.25
        self.assert_fires(plan, "frac must be a number in [0.3,0.7]")

    def test_frac_above_range_rejected(self) -> None:
        plan = self._split_plan()
        plan["reframe"]["split"]["top"]["frac"] = 0.8
        self.assert_fires(plan, "frac must be a number in [0.3,0.7]")

    def test_frac_on_bottom_rejected(self) -> None:
        plan = self._split_plan()
        plan["reframe"]["split"]["bottom"]["frac"] = 0.5
        self.assert_fires(plan, "bottom.frac is not a field")

    # ---- reframe shape (non-dict) -------------------------------------------
    def test_reframe_non_dict_rejected(self) -> None:
        # {"reframe": "face"} must be a lint ERROR, not an AttributeError.
        plan = good_plan()
        plan["reframe"] = "face"
        self.assert_fires(plan, "reframe must be an object")

    # ---- manual crop x baselineLook (coordinate-space conflict) -------------
    # render.py runs baseline_stage BEFORE reframe_stage: a rect drawn on the
    # raw source frame lands on the wrong pixels once baselineLook recrops.
    # V1 = fail loud, no transform.
    _BASELINE = {"zoom": 1.28, "centerX": 0.5, "centerY": 0.44, "grade": "warm"}

    def test_fill_crop_with_baseline_look_rejected(self) -> None:
        plan = good_plan()
        plan["reframe"] = {"layout": "fill", "crop": [0.30, 0.05, 0.65, 0.85]}
        plan["baselineLook"] = dict(self._BASELINE)
        self.assert_fires(plan, "coordinate transform not yet supported")

    def test_split_with_baseline_look_rejected(self) -> None:
        plan = self._split_plan()
        plan["baselineLook"] = dict(self._BASELINE)
        self.assert_fires(plan, "coordinate transform not yet supported")

    def test_baseline_look_alone_passes(self) -> None:
        # baselineLook with the AUTOMATIC face reframe is fine — only manual
        # geometry (crop/split) conflicts.
        plan = good_plan()
        plan["baselineLook"] = dict(self._BASELINE)
        self.assertEqual(self._errors(plan), [])

    def test_manual_crop_alone_passes(self) -> None:
        plan = good_plan()
        plan["reframe"] = {"layout": "fill", "crop": [0.30, 0.05, 0.65, 0.85]}
        self.assertEqual(self._errors(plan), [])


class MotionLintTests(unittest.TestCase):
    """MG-track lint: treatment map, graphics doctrine, gain, corrections."""

    def _errors(self, plan: dict) -> list[str]:
        return pl.lint(plan, MANIFEST).errors

    def assert_fires(self, plan: dict, needle: str) -> None:
        errors = self._errors(plan)
        self.assertTrue(any(needle in e for e in errors),
                        f"expected {needle!r} in errors: {errors}")

    def _mg_plan(self) -> dict:
        plan = good_plan()
        plan["treatmentMap"] = [
            {"outStart": 0, "outEnd": 10, "treatment": "kinetic",
             "budget": "high", "visualState": "talking-head"},
            {"outStart": 10, "outEnd": 30, "treatment": "templated",
             "budget": "low", "visualState": "screen-share"},
        ]
        plan["graphicsTrack"] = [
            {"outStart": 4.0, "outEnd": 6.0, "kind": "stat-card",
             "spec": {"value": "10+ years", "label": ""},
             "anchor": "free-band",
             "reason": "restates 'ten years' — number trigger"},
        ]
        return plan

    def test_valid_mg_plan_passes(self) -> None:
        self.assertEqual(self._errors(self._mg_plan()), [])

    def test_zone_overlap_rejected(self) -> None:
        plan = self._mg_plan()
        plan["treatmentMap"][1]["outStart"] = 5
        self.assert_fires(plan, "overlaps the previous zone")

    def test_overlay_forbidden_in_screenshare_zone(self) -> None:
        # Operator doctrine 2026-07-05: the screen is the star.
        plan = self._mg_plan()
        plan["graphicsTrack"][0].update({"outStart": 12.0, "outEnd": 14.0})
        self.assert_fires(plan, "forbidden in a screen-share zone")

    def test_own_screen_takeover_too_long(self) -> None:
        plan = self._mg_plan()
        plan["graphicsTrack"][0].update(
            {"anchor": "own-screen", "outStart": 4.0, "outEnd": 8.0})
        self.assert_fires(plan, "exceeds")

    def test_graphic_missing_reason(self) -> None:
        plan = self._mg_plan()
        plan["graphicsTrack"][0]["reason"] = ""
        self.assert_fires(plan, "missing reason")

    def test_zone_budget_exceeded(self) -> None:
        plan = self._mg_plan()
        plan["graphicsTrack"] = [
            {"outStart": float(s), "outEnd": float(s) + 1.2, "kind": "stat-card",
             "spec": {}, "anchor": "free-band", "reason": "r"}
            for s in (10.5, 12.0, 14.0, 16.0, 18.0, 20.0)]   # 6 in a 'low' zone
        self.assert_fires(plan, "budget")

    def test_audio_gain_bounds(self) -> None:
        # owner moved to plan_lint_audio (parse_windows) — same ±12 dB band.
        plan = self._mg_plan()
        plan["audioGain"] = [{"outStart": 2.0, "outEnd": 4.0, "dB": 30}]
        self.assert_fires(plan, "audioGain")

    def test_missing_icon_file_rejected(self) -> None:
        plan = self._mg_plan()
        plan["graphicsTrack"][0]["kind"] = "chip-row"
        plan["graphicsTrack"][0]["spec"] = {"chip1": "Codex", "icon1": "nope.svg"}
        self.assert_fires(plan, "icon file")

    def test_icon_badge_icon_files_validated(self) -> None:
        # icon-badge (R12) carries its marks in icon1..N spec keys — the same
        # generic startswith("icon") existence check chip-row relies on must
        # cover the new comp. A missing mark fails the plan; real marks pass.
        plan = self._mg_plan()
        plan["graphicsTrack"][0]["kind"] = "icon-badge"
        plan["graphicsTrack"][0]["spec"] = {"icon1": "codex.svg", "icon2": "nope.svg"}
        self.assert_fires(plan, "icon file")
        plan["graphicsTrack"][0]["spec"] = {"icon1": "codex.svg", "icon2": "gemini.svg"}
        self.assertEqual(self._errors(plan), [])

    def test_resolver_bare_names_pass_icon_check(self) -> None:
        # icon_library.resolve_name returns bare names ("github",
        # "lucide/check"); every icon comp's iconSrc appends ".svg" when the
        # value has no dot. The lint gate validates through that SAME rule —
        # it must accept the resolver's own vocabulary (seam fix 2026-07-11)
        # while a bare name with no file behind it still fails the plan.
        plan = self._mg_plan()
        plan["graphicsTrack"][0]["kind"] = "chip-row"
        plan["graphicsTrack"][0]["spec"] = {
            "chip1": "X", "chip2": "", "chip3": "", "icon1": "github",
            "icon2": "lucide/check"}
        self.assertEqual(self._errors(plan), [])
        plan["graphicsTrack"][0]["spec"] = {
            "chip1": "X", "chip2": "", "chip3": "",
            "icon1": "lucide/nope"}
        self.assert_fires(plan, "icon file")

    def test_corrections_type_checked(self) -> None:
        plan = self._mg_plan()
        plan["captions"]["corrections"] = {"Snyperbot": ""}
        self.assert_fires(plan, "non-empty strings")

    def test_valid_punch_ins_pass(self) -> None:
        # Punch-ins are a top-level cut-treatment section (not graphicsTrack).
        plan = self._mg_plan()
        plan["punchIns"] = [
            {"outStart": 2.0, "outEnd": 4.0, "zoom": 1.08},
            {"outStart": 20.0, "outEnd": 22.0, "zoom": 1.15,
             "centerX": 0.5, "centerY": 0.4},
        ]
        self.assertEqual(self._errors(plan), [])

    def test_punch_in_zoom_out_of_bounds(self) -> None:
        plan = self._mg_plan()
        plan["punchIns"] = [{"outStart": 2.0, "outEnd": 4.0, "zoom": 1.5}]
        self.assert_fires(plan, "zoom must be")

    def test_focus_shift_legal_in_screenshare_zone(self) -> None:
        # R5: focus-shift blurs the base back, so it's the sanctioned overlay in
        # a screen-share zone where free-band graphics are forbidden.
        plan = self._mg_plan()
        plan["graphicsTrack"][0].update(
            {"anchor": "focus-shift", "outStart": 12.0, "outEnd": 14.5})
        self.assertEqual(self._errors(plan), [])

    def test_face_anchor_requires_bbox(self) -> None:
        # R3/R4: a face-relative anchor with no faceBBoxNorm anywhere must fire.
        plan = self._mg_plan()
        plan["graphicsTrack"][0]["anchor"] = "beside-face"   # talking-head zone, no bbox
        self.assert_fires(plan, "requires faceBBoxNorm")

    def test_headroom_anchor_with_bbox_passes(self) -> None:
        # A face-relative anchor with a valid entry-level bbox lints clean.
        plan = self._mg_plan()
        plan["graphicsTrack"][0].update(
            {"anchor": "headroom", "faceBBoxNorm": [0.36, 0.24, 0.28, 0.30]})
        self.assertEqual(self._errors(plan), [])


class RecomposeCadenceTests(unittest.TestCase):
    """PRO_INTRO_ENVELOPE: cut-landing recomposes ride free of the cadence."""

    def _longform_plan(self, punches: list[dict]) -> dict:
        # 10 x 6s segments -> interior seams at 6, 12, ..., 54s output time.
        return {
            "planVersion": 1,
            "target": {"mode": "longform", "durationTargetS": 60, "excerpt": True},
            "cutTrack": [{"sourceId": "raw-1", "start": i * 6.0,
                          "end": (i + 1) * 6.0, "speed": 1.0} for i in range(10)],
            "reframe": {"strategy": "face"},
            "captions": {"burn": False, "style": "line"},
            "punchIns": punches,
        }

    def _sem(self, t: float) -> dict:
        return {"outStart": t, "outEnd": t + 1.2, "zoom": 1.1}

    def _rec(self, t: float) -> dict:
        return {"role": "recompose", "outStart": t, "outEnd": t + 1.2, "zoom": 1.06}

    def test_on_seam_recomposes_are_cadence_exempt(self) -> None:
        # 5 semantic (within the 6/min hook budget) + 7 on-seam recomposes:
        # without the exemption 12 windows would blow the budget.
        punches = [self._sem(t) for t in (1.0, 14.0, 26.0, 38.0, 50.0)]
        punches += [self._rec(t) for t in (6.0, 12.0, 18.0, 24.0, 36.0, 42.0, 54.0)]
        rep = pl.lint(self._longform_plan(punches), MANIFEST)
        self.assertFalse([e for e in rep.errors if "zoom events" in e], rep.errors)

    def test_floating_recompose_counts_and_warns(self) -> None:
        # A recompose NOT on a seam is a real mid-shot zoom: it stays in the
        # count (blowing the 6-allowed hook budget here) and warns.
        punches = [self._sem(t) for t in (1.0, 8.0, 14.0, 26.0, 38.0, 50.0)]
        punches.append(self._rec(33.0))    # nearest seams 30/36 — floating
        rep = pl.lint(self._longform_plan(punches), MANIFEST)
        self.assertTrue(any("not on a cut seam" in w for w in rep.warnings),
                        rep.warnings)
        self.assertTrue(any("zoom events" in e for e in rep.errors), rep.errors)


class IntroEnvelopeShareTests(unittest.TestCase):
    """PRO_INTRO_ENVELOPE: produced first-minute share fails closed."""

    def _plan(self, graphics: list[dict]) -> dict:
        return {
            "planVersion": 1,
            "target": {"mode": "longform", "durationTargetS": 60, "excerpt": True},
            "cutTrack": [{"sourceId": "raw-1", "start": i * 3.0,
                          "end": (i + 1) * 3.0, "speed": 1.0} for i in range(20)],
            "reframe": {"strategy": "face"},
            "captions": {"burn": False, "style": "line"},
            "graphicsTrack": graphics,
        }

    def test_bare_produced_intro_errors_on_first_minute_floor(self) -> None:
        rep = pl.lint(self._plan([]), MANIFEST)
        self.assertTrue(any("first 60s" in e and "envelope floor" in e
                            for e in rep.errors), rep.errors)

    def test_dressed_intro_clears_share_floor(self) -> None:
        # ~27s of graphics over 60s = 45% — above both floors (28% / 40%).
        gfx = [{"outStart": s, "outEnd": s + 9.0, "kind": "statement-card",
                "spec": {"text": "x"}, "anchor": "own-screen", "reason": "beat"}
               for s in (4.0, 24.0, 44.0)]
        rep = pl.lint(self._plan(gfx), MANIFEST)
        self.assertFalse([w for w in rep.warnings if "envelope floor" in w],
                         rep.warnings)
        self.assertFalse([e for e in rep.errors if "envelope floor" in e],
                         rep.errors)


if __name__ == "__main__":
    unittest.main(verbosity=2)
