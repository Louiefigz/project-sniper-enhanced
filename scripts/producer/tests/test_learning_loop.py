"""LEARNING LOOP tests — every showpiece-QC / operator finding, encoded.

One test class per FAILURE_LEDGER.md row (LL-001..LL-011), plus the ledger
machinery itself (``ledger_lessons.parse_lessons`` / ``parse_rows``) and the
prompt wiring that makes the Brain lessons a hard authoring contract.
"""
import json
import tempfile
import unittest
from pathlib import Path

from _common import *  # noqa: F401,F403
import claims_contract as cc
import ledger_lessons as ll
import plan_lint_broll as plb
import plan_lint_smooth as pls
import plan_lint_visual as plv
from edit import cover_select as cs
from graphics import exit_on_cut as eoc
from producer_config import MOTION

_REPO = Path(__file__).resolve().parents[3]
_COMPS = _REPO / "templates" / "motion" / "compositions"


# ---------------------------------------------------------------- fixtures --
def _words(text: str, start: float = 10.0, step: float = 0.5) -> list[dict]:
    out, t = [], start
    for tok in text.split():
        out.append({"word": tok, "start": round(t, 3), "end": round(t + 0.4, 3)})
        t += step
    return out


def _claims_errors(spec: dict, words: list[dict],
                   s: float = 10.0, e: float = 14.0) -> list[str]:
    plan = {"graphicsTrack": [{"outStart": s, "outEnd": e,
                               "kind": "glass-lower-third",
                               "anchor": "free-band", "reason": "cta",
                               "spec": spec}]}
    rep = pl.Report()
    cc.check_claims_contract(plan, words, rep)
    return rep.errors


def _visual_report(entry: dict) -> "pl.Report":
    rep = pl.Report()
    plv.check_visual({"graphicsTrack": [entry]}, rep)
    return rep


def _longform_plan(cuts: list[dict], graphics: list[dict]) -> dict:
    return {
        "planVersion": 1,
        "target": {"mode": "longform", "durationTargetS": 60, "excerpt": True},
        "cutTrack": cuts,
        "reframe": {"strategy": "face"},
        "captions": {"burn": False, "style": "line"},
        "graphicsTrack": graphics,
    }


# ------------------------------------------------------- ledger machinery --
class LedgerLessonsTests(unittest.TestCase):
    """parse_lessons/parse_rows — the loop's machine interface (task 1)."""

    def test_real_ledger_lessons_parse(self) -> None:
        lessons = ll.parse_lessons()
        self.assertGreaterEqual(len(lessons), 6)
        ids = [x["id"] for x in lessons]
        self.assertEqual(ids, sorted(ids), ids)          # stable numbering
        self.assertIn("LESSON-001", ids)
        for x in lessons:
            self.assertTrue(x["text"], x)

    def test_real_ledger_rows_parse(self) -> None:
        rows = ll.parse_rows()
        self.assertGreaterEqual(len(rows), 6)
        for want in ("LL-001", "LL-002", "LL-003", "LL-004", "LL-005", "LL-006"):
            self.assertIn(want, [r["id"] for r in rows])
        for r in rows:
            for key in ("id", "date", "defect", "root cause", "caught-by",
                        "encoded-as", "status"):
                self.assertTrue(r.get(key), (r.get("id"), key))

    def test_synthetic_ledger_round_trip(self) -> None:
        text = ("# x\n\n## Ledger\n\n| id | date | defect | root cause | "
                "caught-by | encoded-as | status |\n|---|---|---|---|---|---|---|\n"
                "| LL-009 | 2026-07-10 | d | rc | qc | rule | ENCODED |\n\n"
                "## Brain lessons\n\n- LESSON-009: Do the thing.\n")
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(text)
        self.assertEqual(ll.parse_lessons(f.name),
                         [{"id": "LESSON-009", "text": "Do the thing."}])
        self.assertEqual(ll.parse_rows(f.name)[0]["id"], "LL-009")

    def test_malformed_lesson_line_fails_loudly(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write("## Brain lessons\n\nremember stuff please\n")
        with self.assertRaises(ValueError):
            ll.parse_lessons(f.name)

    def test_missing_section_fails_loudly(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write("# no sections here\n")
        with self.assertRaises(ValueError):
            ll.parse_lessons(f.name)

    def test_checklist_carries_derived_failure_modes(self) -> None:
        text = (Path(ll.CHECKLIST_PATH)).read_text(encoding="utf-8")
        for want in ("LL-001", "LL-006", "LEDGER-DERIVED:BEGIN"):
            self.assertIn(want, text)


# ------------------------------------------------------------------ LL-001 --
class ExitRunwayTests(unittest.TestCase):
    """Blur-recede needs runway before a seam (the c0679 25.04 smear-cut)."""

    def _entry(self, start: float, end: float, on_cut: bool = False) -> dict:
        return {"outStart": start, "outEnd": end, "kind": "statement-card",
                "anchor": "own-screen", "reason": "beat", "exitOnCut": on_cut,
                "spec": {"text": "x", "exit": "blur-recede"}}

    def test_out_end_on_a_seam_has_no_runway(self) -> None:
        # The exact c0679 shape: outEnd 25.04 exactly ON the 25.04 seam.
        errs, _ = eoc.exit_grammar_issues(self._entry(19.6, 25.04), "g[0]",
                                          [25.04], 1.5)
        self.assertTrue(any("no runway" in e for e in errs), errs)

    def test_out_end_just_short_of_a_seam_still_smears(self) -> None:
        errs, _ = eoc.exit_grammar_issues(self._entry(19.6, 24.9), "g[0]",
                                          [25.04], 1.5)
        self.assertTrue(any("no runway" in e for e in errs), errs)

    def test_ending_before_the_seam_gives_runway(self) -> None:
        errs, _ = eoc.exit_grammar_issues(self._entry(19.6, 24.7), "g[0]",
                                          [25.04], 1.5)
        self.assertEqual(errs, [])

    def test_exit_on_cut_is_a_hard_clear_not_a_smear(self) -> None:
        errs, _ = eoc.exit_grammar_issues(
            self._entry(19.6, 25.04, on_cut=True), "g[0]", [25.04], 1.5)
        self.assertFalse(any("no runway" in e for e in errs), errs)

    def test_fires_through_plan_lint(self) -> None:
        cuts = [{"sourceId": "raw-1", "start": 0.0, "end": 25.04, "speed": 1.0},
                {"sourceId": "raw-1", "start": 26.0, "end": 58.0, "speed": 1.0}]
        gfx = [self._entry(19.6, 25.04)]
        rep = pl.lint(_longform_plan(cuts, gfx), MANIFEST)
        self.assertTrue(any("no runway" in e for e in rep.errors), rep.errors)


# ------------------------------------------------------------------ LL-002 --
class FirstLandTests(unittest.TestCase):
    """Empty-chrome staging: first declared land vs the entrance ceilings."""

    def _entry(self, anchor: str, spec: dict, kind: str = "whiteboard-list",
               hold: float = 5.0) -> dict:
        return {"outStart": 4.0, "outEnd": 4.0 + hold, "kind": kind,
                "anchor": anchor, "reason": "list", "spec": spec}

    def test_own_screen_late_first_land_is_an_error(self) -> None:
        # The c0679 whiteboard: item 1 landed 2.29s after the cut.
        rep = _visual_report(self._entry(
            "own-screen", {"title": "Five tips", "item1": "x", "at1": 2.29}))
        self.assertTrue(any("first content land" in e for e in rep.errors),
                        rep.errors)

    def test_own_screen_early_module_land_is_clean(self) -> None:
        rep = _visual_report(self._entry(
            "own-screen", {"moduleLands": [0.2, 1.1, 2.0]},
            kind="nateherk-takeover"))
        self.assertEqual(rep.errors, [])
        self.assertEqual(rep.warnings, [])

    def test_panel_late_land_is_a_warning_not_an_error(self) -> None:
        rep = _visual_report(self._entry(
            "free-band", {"value": "92", "at1": 1.2}, kind="stat-card"))
        self.assertEqual(rep.errors, [])
        self.assertTrue(any("first content land" in w for w in rep.warnings),
                        rep.warnings)

    def test_panel_band_is_wider_than_own_screen(self) -> None:
        rep = _visual_report(self._entry(
            "free-band", {"value": "92", "at1": 0.8}, kind="stat-card"))
        self.assertEqual((rep.errors, rep.warnings), ([], []))

    def test_no_declared_lands_is_skipped(self) -> None:
        rep = _visual_report(self._entry("own-screen", {"item1": "x"}))
        self.assertEqual(rep.errors, [])

    def test_fires_through_plan_lint(self) -> None:
        cuts = [{"sourceId": "raw-1", "start": i * 3.0, "end": (i + 1) * 3.0,
                 "speed": 1.0} for i in range(20)]
        gfx = [self._entry("own-screen",
                           {"title": "Five tips", "item1": "x", "at1": 2.29})]
        rep = pl.lint(_longform_plan(cuts, gfx), MANIFEST)
        self.assertTrue(any("first content land" in e for e in rep.errors),
                        rep.errors)


# ------------------------------------------------------------------ LL-003 --
class PhraseGroundingTests(unittest.TestCase):
    """Unspoken rendered phrases (>2 words) fail the claims gate."""

    # The exact c0679 offender: the lower-third renders a CTA the speaker
    # never says in the cut (the spoken line sits ~127s outside the excerpt).
    OFFENDER = {"eyebrow": "FREE — LINK IN DESCRIPTION",
                "titleBase": "Angle Generator", "titleHighlight": "Workbook"}
    SPOKEN = "what you're actually gonna get if you download the angle generator workbook"

    def test_the_exact_c0679_cta_fails(self) -> None:
        errs = _claims_errors(self.OFFENDER, _words(self.SPOKEN))
        self.assertEqual(len(errs), 1, errs)
        self.assertIn("FREE — LINK IN DESCRIPTION", errs[0])
        self.assertIn("LESSON-001", errs[0])

    def test_the_same_card_passes_when_the_cta_is_spoken(self) -> None:
        spoken = self.SPOKEN + " it's free first link in the description"
        self.assertEqual(
            _claims_errors(self.OFFENDER, _words(spoken, step=0.3)), [])

    def test_structural_labels_are_whitelisted_chrome(self) -> None:
        spec = {"eyebrow": "WHO THIS IS FOR"}
        self.assertEqual(
            _claims_errors(spec, _words("small business owners and creators")),
            [])

    def test_two_word_phrases_are_exempt(self) -> None:
        # Exempt from PHRASE grounding (LL-003) — unrelated copy still owes
        # the LL-009 beat-coverage floor, so the only error is coverage.
        spec = {"titleBase": "Angle Generator"}
        errs = _claims_errors(spec, _words("nothing related here"))
        self.assertEqual(len(errs), 1, errs)
        self.assertIn("LL-009", errs[0])
        self.assertNotIn("LESSON-001", errs[0])
        self.assertEqual(
            _claims_errors(spec, _words("the angle generator workbook")), [])

    def test_pipe_separated_units_are_judged_separately(self) -> None:
        # "ONE RUN.|FOUR AGENTS." = two 2-word units, both phrase-exempt;
        # spoken-in-window tokens satisfy the LL-009 coverage floor too.
        spec = {"headlineLines": "ONE RUN.|FOUR AGENTS."}
        errs = _claims_errors(spec, _words("unrelated words only"))
        self.assertEqual(len(errs), 1, errs)          # coverage, not phrases
        self.assertNotIn("LESSON-001", errs[0])
        self.assertEqual(
            _claims_errors(spec, _words("we run four agents at once")), [])

    def test_faithful_paraphrase_stays_legal(self) -> None:
        # >= half the tokens spoken: "can probably even be better" grounds it.
        spec = {"statements": "Even the prompts could be better"}
        words = _words("your prompts can probably even be better")
        self.assertEqual(_claims_errors(spec, words), [])


# ------------------------------------------------------------------ LL-004 --
class ContrastTests(unittest.TestCase):
    """Accent-on-bg WCAG contrast for cataloged comp kinds."""

    def _entry(self, kind: str, spec: dict) -> dict:
        return {"outStart": 4.0, "outEnd": 9.0, "kind": kind,
                "anchor": "own-screen", "reason": "beat", "spec": spec}

    def test_ratio_math_is_wcag(self) -> None:
        self.assertAlmostEqual(plv.contrast_ratio("#ffffff", "#000000"), 21.0)
        self.assertAlmostEqual(plv.contrast_ratio("#000000", "#ffffff"), 21.0)
        self.assertIsNone(plv.contrast_ratio("navy", "#000000"))

    def test_the_c0679_accent_blue_on_dark_card_fails(self) -> None:
        rep = _visual_report(self._entry(
            "statement-card", {"text": "x", "accent": "#054BC9"}))
        self.assertEqual(len(rep.errors), 1, rep.errors)
        self.assertIn("large-text floor", rep.errors[0])

    def test_same_accent_on_the_cream_variant_passes(self) -> None:
        rep = _visual_report(self._entry(
            "statement-card", {"text": "x", "bg": "cream", "accent": "#054BC9"}))
        self.assertEqual(rep.errors, [])

    def test_lime_on_the_takeover_canvas_passes(self) -> None:
        rep = _visual_report(self._entry(
            "nateherk-takeover", {"eyebrow": "ULTRA", "accent": "#c6f542"}))
        self.assertEqual(rep.errors, [])

    def test_unknown_kind_or_variant_is_skipped_never_guessed(self) -> None:
        rep = _visual_report(self._entry("stat-card", {"accent": "#054BC9"}))
        self.assertEqual(rep.errors, [])
        rep2 = _visual_report(self._entry(
            "statement-card", {"bg": "warm", "accent": "#054BC9"}))
        self.assertEqual(rep2.errors, [])


# ------------------------------------------------------------------ LL-005 --
class LeftBalanceTests(unittest.TestCase):
    """Long full-frame holds of left-column layouts draw a WARN."""

    def _entry(self, hold: float, anchor: str = "own-screen") -> dict:
        return {"outStart": 64.73, "outEnd": 64.73 + hold,
                "kind": "whiteboard-list", "anchor": anchor, "reason": "list",
                "spec": {"item1": "x"}}

    def test_the_c0679_ten_second_hold_warns(self) -> None:
        rep = _visual_report(self._entry(10.5))
        self.assertTrue(any("left-column" in w for w in rep.warnings),
                        rep.warnings)
        self.assertEqual(rep.errors, [])            # taste, not a wall

    def test_short_hold_is_clean(self) -> None:
        self.assertEqual(_visual_report(self._entry(4.0)).warnings, [])

    def test_non_own_screen_is_not_flagged(self) -> None:
        rep = _visual_report(self._entry(10.5, anchor="free-band"))
        self.assertEqual(rep.warnings, [])


# ------------------------------------------------------------------ LL-006 --
class ReceiptLineTests(unittest.TestCase):
    """Receipt-line comp tweak: separator glyph + brighter gray token."""

    def test_tokens_sheet_declares_receipt_gray(self) -> None:
        css = (_REPO / "templates" / "motion" / "tokens.css").read_text(
            encoding="utf-8")
        self.assertIn("--receipt-gray: rgba(255, 255, 255, 0.72)", css)

    def test_both_ribbon_comps_use_token_and_separator(self) -> None:
        for name in ("nateherk-takeover.html", "statement-card.html"):
            html = (_COMPS / name).read_text(encoding="utf-8")
            self.assertIn("var(--receipt-gray", html, name)
            self.assertIn('join(" \\u00b7 ")', html, name)


# ------------------------------------------------------------------ LL-007 --
class GapFillerZoomTests(unittest.TestCase):
    """Zooms are not gap-fillers (the v2 14-17s in→out pair, operator-caught).

    The pair existed only to fill the 12.47→19.60 graphics gap: no graphic
    overlapped it and it marked no emphasis beat. The lint WARNs on exactly
    that shape; annotated / graphic-serving zooms stay clean.
    """

    # The v2 showpiece shape: a graphic exits at 12.47, the next enters 19.60.
    V2_GRAPHICS = [
        {"outStart": 8.0, "outEnd": 12.47, "kind": "glass-rail",
         "anchor": "free-band", "reason": "x", "spec": {},
         "recompose": False},
        {"outStart": 19.6, "outEnd": 24.0, "kind": "statement-card",
         "anchor": "own-screen", "reason": "x", "spec": {"text": "x"}},
    ]
    # The offending pair: eased in and back out entirely inside the gap.
    V2_PAIR = {"outStart": 14.0, "outEnd": 17.0, "zoom": 1.12,
               "attackS": 0.5, "releaseS": 0.5}

    def _ll007_warnings(self, punch_ins: list[dict],
                        graphics: list[dict] | None = None) -> list[str]:
        plan = {"target": {"mode": "longform"},
                "cutTrack": [{"sourceId": "raw-1", "start": 0.0, "end": 60.0,
                              "speed": 1.0}],
                "graphicsTrack": self.V2_GRAPHICS if graphics is None
                else graphics,
                "punchIns": punch_ins}
        rep = pl.Report()
        pls.check_smooth(plan, 60.0, "longform", rep)
        return [w for w in rep.warnings if "LL-007" in w]

    def test_the_v2_pair_trips_the_warn(self) -> None:
        warns = self._ll007_warnings([dict(self.V2_PAIR)])
        self.assertEqual(len(warns), 1, warns)
        self.assertIn("zoom pair fills a gap", warns[0])
        self.assertIn("graphic/panel extension", warns[0])

    def test_emphasis_annotated_punch_is_clean(self) -> None:
        marked = dict(self.V2_PAIR, trigger="thesis",
                      evidence="the whole pipeline runs itself")
        self.assertEqual(self._ll007_warnings([marked]), [])

    def test_evidence_alone_is_annotation(self) -> None:
        marked = dict(self.V2_PAIR, evidence="four agents in one run")
        self.assertEqual(self._ll007_warnings([marked]), [])

    def test_a_bare_reason_is_not_annotation(self) -> None:
        # Pacing-fill rows carry a reason — exactly the gap-fillers to catch.
        filler = dict(self.V2_PAIR, reason="pacing fill (hook): break the gap")
        self.assertEqual(len(self._ll007_warnings([filler])), 1)

    def test_pair_overlapping_a_graphic_is_clean(self) -> None:
        gfx = [{"outStart": 13.0, "outEnd": 18.0, "kind": "statement-card",
                "anchor": "own-screen", "reason": "x", "spec": {"text": "x"}}]
        self.assertEqual(self._ll007_warnings([dict(self.V2_PAIR)], gfx), [])

    def test_long_resolving_hold_is_not_a_pair(self) -> None:
        held = dict(self.V2_PAIR, outEnd=19.0)          # 5s > gap_pair_max_s
        self.assertEqual(self._ll007_warnings([held]), [])

    def test_punch_plus_contiguous_ramp_out_warns_as_one_pair(self) -> None:
        pair = [{"outStart": 14.0, "outEnd": 15.5, "zoom": 1.12,
                 "attackS": 0.5},
                {"outStart": 15.5, "outEnd": 16.8,
                 "ramp": {"direction": "out", "ratePctPerS": 0.8},
                 "ease": "smooth"}]
        warns = self._ll007_warnings(pair)
        self.assertEqual(len(warns), 1, warns)

    def test_aliveness_and_recompose_windows_are_exempt(self) -> None:
        wins = [{"outStart": 14.0, "outEnd": 16.0, "role": "aliveness",
                 "ramp": {"direction": "in", "ratePctPerS": 0.8}},
                {"outStart": 16.2, "outEnd": 18.0, "role": "recompose",
                 "zoom": 1.2, "attackS": 0.4, "releaseS": 0.4}]
        self.assertEqual(self._ll007_warnings(wins), [])

    def test_fires_through_plan_lint(self) -> None:
        cuts = [{"sourceId": "raw-1", "start": 0.0, "end": 60.0, "speed": 1.0}]
        plan = _longform_plan(cuts, [g.copy() for g in self.V2_GRAPHICS])
        plan["punchIns"] = [dict(self.V2_PAIR)]
        rep = pl.lint(plan, MANIFEST)
        self.assertTrue(any("LL-007" in w for w in rep.warnings),
                        rep.warnings)

    def test_longform_fills_propose_graphics_never_punches(self) -> None:
        # LL-007(a): suggest_fills no longer authors punch fills on longform.
        plan = {"cutTrack": [{"sourceId": "raw-1", "start": 0.0,
                              "end": 70.0, "speed": 1.0}]}
        fills = pac.suggest_fills(plan, 70.0, "longform")
        self.assertTrue(fills)
        for f in fills:
            self.assertEqual(f["kind"], "graphic", f)
            self.assertIn("extend the adjacent panel's hold", f["reason"])
            self.assertIn("LL-007", f["reason"])

    def test_short_fills_keep_the_punch_grammar(self) -> None:
        plan = {"cutTrack": [{"sourceId": "raw-1", "start": 0.0,
                              "end": 30.0, "speed": 1.0}]}
        fills = pac.suggest_fills(plan, 30.0, "short")
        self.assertTrue(fills)
        self.assertTrue(all(f["kind"] == "punch" for f in fills), fills)


# ------------------------------------------------------------------ LL-008 --
def _synth_profile(regions: list[tuple], t1: float = 60.0,
                   step: float = 0.25) -> "cs.MotionProfile":
    """Synthetic MotionProfile: (start, end, full, lower) regions override the
    quiet default (full 0.5, lower 0.2 — a live but still talking head)."""
    times, full, lower = [], [], []
    t = 0.0
    while t < t1:
        f, lo = 0.5, 0.2
        for rs, re, rf, rl in regions:
            if rs <= t < re:
                f, lo = rf, rl
        times.append(round(t, 3))
        full.append(f)
        lower.append(lo)
        t += step
    return cs.MotionProfile(times, full, lower)


def _speech(spans: list[tuple]) -> list[dict]:
    """~0.9s-per-second word rows covering each (start, end) span."""
    words = []
    for s, e in spans:
        t = s
        while t < e:
            words.append({"word": "w", "start": round(t, 2),
                          "end": round(min(t + 0.9, e), 2)})
            t += 1.0
    return words


class CoverSelectTests(unittest.TestCase):
    """Slip-covers must read intentional (the v2 45.3-47.8s dead stare)."""

    # SILENT gesturing 10-14s (a legal cover is silent + visibly working —
    # any visible speech is the LL-010 lip-flap exclude); retake re-delivery
    # around 21-25s with motion through 31s; the v2 dead stare (silent +
    # motionless) at 45-48s. Speech everywhere EXCEPT the motion windows.
    PROFILE_REGIONS = [(10.0, 14.0, 6.0, 5.0), (21.0, 31.0, 6.0, 5.0),
                       (45.0, 48.0, 0.2, 0.05)]
    WORDS_SPANS = [(0.0, 9.0), (15.0, 20.0), (32.0, 44.0), (49.0, 60.0)]
    RETAKES = [(21.0, 25.0)]

    def _score(self, windows: list[tuple], words: list[dict] | None = None,
               retakes: list[tuple] | None = None) -> list[dict]:
        return cs.score_windows(
            _synth_profile(self.PROFILE_REGIONS),
            _speech(self.WORDS_SPANS) if words is None else words,
            self.RETAKES if retakes is None else retakes, windows)

    def test_active_window_outscores_the_static_one(self) -> None:
        active, static = self._score([(10.5, 13.5), (45.3, 47.8)])
        self.assertGreater(active["score"], static["score"])
        self.assertIsNone(active["excluded"])

    def test_the_v2_dead_stare_is_excluded_silent_static(self) -> None:
        row = self._score([(45.3, 47.8)])[0]
        self.assertEqual(row["excluded"], "silent-static")
        self.assertLess(row["speechShare"], 0.3)

    def test_silent_but_visibly_working_survives(self) -> None:
        # Same gesturing window with NO speech at all: motion clears the
        # silent floor, so it is legal b-roll of the subject doing something.
        row = self._score([(10.5, 13.5)], words=[])[0]
        self.assertIsNone(row["excluded"])

    def test_retake_overlap_is_a_hard_exclude_even_when_active(self) -> None:
        near, clear = self._score([(24.5, 27.5), (27.5, 30.5)])
        self.assertEqual(near["excluded"], "retake-overlap")   # 25 + 2s pad
        self.assertIsNone(clear["excluded"])

    def test_visible_speech_is_excluded_lip_flap(self) -> None:
        # LL-010: the c0679 v3 cover carried 0.49s of visible speech (the
        # abandoned line's tail + the restart's onset) and the operator read
        # it as "the sound did not sync for a moment" — the same speaker
        # mouths words that are NOT the underlying audio. Any window with
        # more than lip_flap_max_s of spoken overlap is hard-excluded even
        # when fully active.
        row = self._score([(21.5, 24.0)],
                          words=_speech([(23.0, 24.0)]), retakes=[])[0]
        self.assertEqual(row["excluded"], "lip-flap")
        self.assertGreaterEqual(row["score"],
                                cs.COVER_SELECT["score_floor"])

    def test_lower_half_gesture_lifts_the_score(self) -> None:
        profile = _synth_profile([(30.0, 34.0, 2.4, 4.5),
                                  (35.0, 39.0, 2.4, 0.0)])
        hands, still = cs.score_windows(profile, _speech([(0.0, 60.0)]), [],
                                        [(30.5, 33.5), (35.5, 38.5)])
        self.assertGreater(hands["score"], still["score"])
        self.assertGreaterEqual(hands["score"],
                                cs.COVER_SELECT["score_floor"])

    def test_best_cover_picks_the_top_legal_window(self) -> None:
        result = cs.best_cover(self._score([(10.5, 13.5), (45.3, 47.8),
                                            (24.5, 27.5)]))
        self.assertEqual(result["best"]["start"], 10.5)
        self.assertIsNone(result["note"])

    def test_no_survivor_says_graphic_takeover(self) -> None:
        result = cs.best_cover(self._score([(45.3, 47.8), (44.8, 47.3)]))
        self.assertIsNone(result["best"])
        self.assertIn("graphic takeover", result["note"])
        self.assertIn("LESSON-008", result["note"])

    def test_candidate_windows_respect_span_and_source_bounds(self) -> None:
        wins = cs.candidate_windows((45.3, 47.8), 60.0)
        self.assertTrue(wins)
        for s, e in wins:
            self.assertAlmostEqual(e - s, 2.5, places=3)
            self.assertGreaterEqual(s, 45.3 - cs.COVER_SELECT["search_s"])
            self.assertLessEqual(e, 60.0)

    def test_degenerate_span_fails_loudly(self) -> None:
        with self.assertRaises(ValueError):
            cs.candidate_windows((47.8, 45.3), 60.0)

    def test_speech_share_math(self) -> None:
        words = [{"word": "w", "start": 10.0, "end": 11.0}]
        self.assertAlmostEqual(cs.speech_share(words, 10.0, 12.0), 0.5)
        self.assertAlmostEqual(cs.speech_share([], 10.0, 12.0), 0.0)

    def test_resolve_source_fails_loudly(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json",
                                         delete=False) as f:
            f.write('{"sources": [{"id": "raw-1", "duration": 60.0, '
                    '"path": "/nonexistent.mp4"}]}')
        with self.assertRaises(ValueError):        # unknown source id
            cs._resolve_source(f.name, "raw-9")
        with self.assertRaises(ValueError):        # unreadable path
            cs._resolve_source(f.name, None)


# ------------------------------------------------------------------ LL-009 --
class BeatCoverageTests(unittest.TestCase):
    """A graphic must EARN its beat (LL-009): unrelated copy fails outright."""

    SPOKEN = "your AI content system is probably at this stage"

    def test_decorative_unrelated_card_fails(self) -> None:
        # The defect SHAPE: a card whose copy shares nothing with the words
        # spoken under its window — decorative chrome is worse than clean
        # face (operator, c0679 v3 12.63-19.6s finding).
        spec = {"eyebrow": "RIGHT NOW", "title1": "Mindset hacks",
                "title2": "Morning routine"}
        errs = _claims_errors(spec, _words(self.SPOKEN))
        self.assertEqual(len(errs), 1, errs)
        self.assertIn("LL-009", errs[0])
        self.assertIn("LESSON-009", errs[0])

    def test_the_located_right_now_rail_passes_the_floor(self) -> None:
        # The ACTUAL c0679 12.63-19.6s rail: titles spoken verbatim in-window
        # PASS the deterministic floor — verbatim-REDUNDANT restatement is a
        # semantic defect only the brain's LESSON-009 step-4 read catches
        # (the floor's documented honest limit; FAILURE_LEDGER LL-009).
        spec = {"eyebrow": "RIGHT NOW", "title1": "Your AI content system",
                "title2": "Probably at this stage"}
        self.assertEqual(_claims_errors(spec, _words(self.SPOKEN)), [])

    def test_numeric_claim_counts_toward_coverage(self) -> None:
        words = _words("ninety two percent pass rate overall")
        self.assertEqual(_claims_errors({"label": "92% pass"}, words), [])

    def test_structural_chrome_owes_no_coverage(self) -> None:
        spec = {"eyebrow": "WHO THIS IS FOR"}
        self.assertEqual(
            _claims_errors(spec, _words("totally unrelated narration")), [])

    def test_single_token_card_needs_that_token(self) -> None:
        errs = _claims_errors({"title": "Workbook"}, _words("unrelated words"))
        self.assertEqual(len(errs), 1, errs)
        self.assertIn("LL-009", errs[0])
        self.assertEqual(
            _claims_errors({"title": "Workbook"},
                           _words("download the workbook now")), [])


# ------------------------------------------------------------------ LL-010 --
# The REAL c0679 utterance shapes around the abandoned line (raw-1
# transcript): the anchor trails off unterminated at 119.61, a fragment
# follows, and the restart re-delivers the line rephrased at 124.34. The
# operator's slip-cover (assetStart 122.0, 2.5s) sits in the inter-take gap.
_C0679_UTTS = [
    (116.01, 119.61, "what happens when you actually feed the same prompt,"),
    (119.93, 122.33, "but you have all of these massive?"),
    (124.34, 130.59, "So here's what happens when you actually feed that "
                     "engine that I'm giving you with, like, real data "
                     "instead."),
    (130.59, 131.22, "Okay?"),
]


def _utt_transcript(utts: list[tuple]) -> dict:
    """A transcribe.py-shaped transcript from (start, end, text) triples."""
    segs = []
    for s, e, text in utts:
        toks = text.split()
        dur = (e - s) / len(toks)
        segs.append({"start": s, "end": e, "text": text, "words": [
            {"word": tk, "start": round(s + i * dur, 3),
             "end": round(s + (i + 1) * dur, 3), "confidence": 1.0}
            for i, tk in enumerate(toks)]})
    return {"status": "done", "transcript": segs,
            "duration": utts[-1][1], "language": "en"}


@unittest.skipUnless(_HAVE_RETAKE, "rapidfuzz not installed")
class AbandonedRetakeTests(unittest.TestCase):
    """retake_scan catches the abandoned-anchor retake (LL-010 root cause a).

    The c0679 pair scored 81.4 — 0.6 UNDER the strict RETAKE_RATIO (82) —
    because the restart rephrases the tail the anchor never finished, so the
    outtake gap survived into a slip-cover. Unterminated anchors now get the
    eased ABANDONED_RETAKE_RATIO bar; terminated anchors keep the strict one.
    """

    def _spans(self, utts: list[tuple]) -> list[tuple]:
        with tempfile.NamedTemporaryFile("w", suffix=".json",
                                         delete=False) as f:
            json.dump(_utt_transcript(utts), f)
        report = rs.analyze(f.name)
        return [(r["cutStartS"], r["cutEndS"]) for r in report["retakes"]]

    def test_the_c0679_abandoned_line_is_detected(self) -> None:
        spans = self._spans(_C0679_UTTS)
        self.assertTrue(any(s <= 116.02 and e >= 124.3 for s, e in spans),
                        spans)

    def test_terminated_anchor_keeps_the_strict_bar(self) -> None:
        # Same tokens, terminal "." — the 81.4 similarity stays under the
        # strict 82 bar, so no retake is proposed (the ease is driven by the
        # ASR's own sentence state, not by content matching).
        utts = list(_C0679_UTTS)
        utts[0] = (116.01, 119.61,
                   "what happens when you actually feed the same prompt.")
        self.assertFalse([e for _, e in self._spans(utts) if e >= 124.3])


@unittest.skipUnless(_HAVE_RETAKE, "rapidfuzz not installed")
class SlipcoverLintTests(unittest.TestCase):
    """plan_lint_broll.check_slipcover — LL-010's gate on the PLAN itself.

    cover_select excludes outtake windows at PROPOSAL time; this gate re-checks
    the plan's actual brollTrack windows so a hand-authored or drifted window
    (the shipped c0679 one) cannot reach the renderer.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        (base / "raw.mp4").write_bytes(b"")
        (base / "t.json").write_text(json.dumps(_utt_transcript(_C0679_UTTS)))
        self.manifest = {
            "_path": str(base / "manifest.json"),
            "sources": [{"id": "raw-1", "path": str(base / "raw.mp4"),
                         "duration": 335.0, "transcriptPath": "t.json"}],
            "broll": [{"id": "wide-1", "path": str(base / "raw.mp4")},
                      {"id": "lib-1", "path": str(base / "other.mp4")}],
        }

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _report(self, broll: list[dict]) -> "pl.Report":
        rep = pl.Report()
        plb.check_slipcover({"brollTrack": broll}, self.manifest, rep)
        return rep

    def _cover(self, asset_start: float, asset_id: str = "wide-1") -> dict:
        return {"assetId": asset_id, "outStart": 45.29, "outEnd": 47.79,
                "assetStart": asset_start}

    def test_the_shipped_c0679_window_errors_retake_overlap(self) -> None:
        # The EXACT defect: assetStart 122.0 for a 2.5s window — raw
        # 122.0-124.5 sits inside the abandoned-line retake span 116.01-124.34.
        rep = self._report([self._cover(122.0)])
        self.assertTrue(any("outtake" in e and "LL-010" in e
                            for e in rep.errors), rep.errors)

    def test_visible_speech_window_errors_lip_flap(self) -> None:
        # raw 127.5-130.0 sits INSIDE the restart delivery: ~2.5s of visible
        # same-speaker speech over unrelated timeline audio (the AV-sync read).
        rep = self._report([self._cover(127.5)])
        self.assertTrue(any("visible speech" in e and "LL-010" in e
                            for e in rep.errors), rep.errors)

    def test_clean_silent_window_passes(self) -> None:
        rep = self._report([self._cover(132.0)])
        self.assertEqual(rep.errors, [])
        self.assertEqual(rep.warnings, [])

    def test_library_broll_is_not_a_slipcover(self) -> None:
        rep = self._report([self._cover(122.0, asset_id="lib-1")])
        self.assertEqual(rep.errors, [])

    def test_unresolvable_transcript_warns_loudly(self) -> None:
        self.manifest["sources"][0].pop("transcriptPath")
        rep = self._report([self._cover(122.0)])
        self.assertEqual(rep.errors, [])
        self.assertTrue(any("did NOT run" in w for w in rep.warnings),
                        rep.warnings)


# ------------------------------------------------------------------ LL-011 --
class RowLandsTests(unittest.TestCase):
    """Progressive point reveal — list comps land word-locked, never at once."""

    # The shipped c0679 "THE OUTPUT" rail geometry (64.73-75.2s, 3 titles).
    TITLES = {"eyebrow": "THE OUTPUT",
              "title1": "Five tips to stay consistent",
              "title2": "Use AI to create faster",
              "title3": "Top tools for creators"}

    def _rail(self, spec: dict, kind: str = "glass-rail") -> dict:
        return {"outStart": 64.73, "outEnd": 75.2, "kind": kind,
                "anchor": "free-band", "spec": spec}

    def _errs(self, entry: dict, mode: str = "longform") -> list[str]:
        rep = pl.Report()
        plv.check_row_lands({"graphicsTrack": [entry]}, mode, rep)
        return rep.errors

    def test_the_shipped_output_rail_fails_without_lands(self) -> None:
        errs = self._errs(self._rail(dict(self.TITLES)))
        self.assertEqual(len(errs), 1, errs)
        self.assertIn("LL-011", errs[0])
        self.assertIn("rowLands", errs[0])

    def test_word_locked_lands_pass(self) -> None:
        # The real word-locks: 'five' 67.02 / 'AI' 70.94 / 'top' 74.05.
        spec = dict(self.TITLES, rowLands=[2.29, 6.21, 9.32])
        self.assertEqual(self._errs(self._rail(spec)), [])

    def test_count_mismatch_fails(self) -> None:
        spec = dict(self.TITLES, rowLands=[2.29, 6.21])
        errs = self._errs(self._rail(spec))
        self.assertEqual(len(errs), 1, errs)
        self.assertIn("2 land(s) for 3 items", errs[0])

    def test_stacked_lands_read_as_all_at_once(self) -> None:
        spec = dict(self.TITLES, rowLands=[2.29, 2.4, 9.32])
        errs = self._errs(self._rail(spec))
        self.assertTrue(any("all-at-once" in e for e in errs), errs)

    def test_land_outside_the_hold_fails(self) -> None:
        spec = dict(self.TITLES, rowLands=[2.29, 6.21, 11.5])   # hold 10.47
        errs = self._errs(self._rail(spec))
        self.assertTrue(any("outside" in e for e in errs), errs)

    def test_shorts_are_not_gated(self) -> None:
        self.assertEqual(self._errs(self._rail(dict(self.TITLES)),
                                    mode="short"), [])

    def test_single_row_is_not_a_list_build(self) -> None:
        spec = {"eyebrow": "THE OUTPUT", "title1": "Five tips"}
        self.assertEqual(self._errs(self._rail(spec)), [])

    def test_whiteboard_list_uses_per_item_atn(self) -> None:
        ok = self._rail({"item1": "Point one", "at1": 1.0,
                         "item2": "Point two", "at2": 3.0},
                        kind="whiteboard-list")
        self.assertEqual(self._errs(ok), [])
        missing = self._rail({"item1": "Point one", "at1": 1.0,
                              "item2": "Point two"}, kind="whiteboard-list")
        errs = self._errs(missing)
        self.assertEqual(len(errs), 1, errs)
        self.assertIn("at2", errs[0])

    def test_fill_row_lands_word_locks_the_rows(self) -> None:
        words = [{"word": "five", "start": 67.02, "end": 67.3},
                 {"word": "AI", "start": 70.94, "end": 71.1},
                 {"word": "top", "start": 74.05, "end": 74.3}]
        entry = self._rail(dict(self.TITLES))
        filled = gcopy.fill_row_lands(entry, [0, 1, 2], words)
        self.assertEqual(filled["spec"]["rowLands"], [2.29, 6.21, 9.32])
        self.assertEqual(self._errs(filled), [])
        # Invalid picks return None — re-pick upstream, no fallback.
        self.assertIsNone(gcopy.fill_row_lands(entry, [0, 9], words))

    def test_the_comp_consumes_row_lands(self) -> None:
        html = (_COMPS / "glass-rail.html").read_text(encoding="utf-8")
        self.assertIn('"id":"rowLands"', html)          # declared variable
        self.assertEqual(html.count("rowLands ? rowLands[i]"), 2,
                         "both builds (rail-push + classic) must word-lock")
        self.assertIn("rowLands needs", html)           # count-mismatch throw


# -------------------------------------------- LL-015 form-selection contract --
class CardFormMapTests(unittest.TestCase):
    """MOTION['card_form_map'] data integrity — info-shape → form family."""

    MAP = MOTION["card_form_map"]

    def test_every_family_is_a_nonempty_tuple_of_built_comps(self) -> None:
        self.assertGreaterEqual(len(self.MAP), 7)
        for family, kinds in self.MAP.items():
            self.assertIsInstance(kinds, tuple, family)
            self.assertTrue(kinds, f"{family} family is empty")
            for kind in kinds:
                self.assertTrue((_COMPS / f"{kind}.html").exists(),
                                f"{family}: comp {kind!r} has no HTML")

    def test_the_nate_mapping_rows_are_covered(self) -> None:
        # NATEHERK_CARDS §1.4 — one spot check per table row we encode.
        self.assertIn("nateherk-bullet-bars", self.MAP["comparison"])   # #9/#12
        self.assertIn("versus-split", self.MAP["comparison"])
        self.assertIn("nateherk-pipeline", self.MAP["process"])         # #18
        self.assertIn("nateherk-ledger-dark", self.MAP["evidence"])     # #3/#5
        self.assertIn("nateherk-bullet-bars", self.MAP["limit"])        # #12
        self.assertIn("nateherk-scoreboard", self.MAP["scale"])         # #11
        self.assertIn("whiteboard-list", self.MAP["list"])              # #8/#10
        self.assertIn("statement-card", self.MAP["thesis"])             # #19

    def test_thesis_forms_never_double_as_comparison_forms(self) -> None:
        # The LESSON-029 defect shape: numbers belong on comparison forms.
        overlap = set(self.MAP["thesis"]) & set(self.MAP["comparison"])
        self.assertEqual(overlap, set())

    def test_form_shape_knobs_are_sane(self) -> None:
        cfg = MOTION["form_shape"]
        self.assertGreaterEqual(int(cfg["numeric_min"]), 2)
        self.assertIn("versus", cfg["comparative_words"])
        self.assertIn("than", cfg["comparative_words"])


class FormShapeTests(unittest.TestCase):
    """LL-015 — comparison-shaped info must ride a comparison form."""

    # "91.9 versus 85.6" spoken across the card's 10-14s window.
    WORDS = _words("the score moved to 91.9 versus 85.6 on the bench")
    SPEC = {"headline": "The numbers moved.", "value1": "91.9",
            "value2": "85.6"}

    def _report(self, kind: str, spec: dict, words=None,
                target: dict | None = None) -> pl.Report:
        plan = {"target": target or {}, "graphicsTrack": [{
            "outStart": 10.0, "outEnd": 14.0, "kind": kind,
            "anchor": "own-screen", "spec": spec}]}
        rep = pl.Report()
        plv.check_form_shape(plan, self.WORDS if words is None else words, rep)
        return rep

    def _warns(self, kind: str, spec: dict, words=None) -> list[str]:
        return self._report(kind, spec, words).warnings

    def test_numbers_on_a_statement_card_warn(self) -> None:
        warns = self._warns("statement-card", dict(self.SPEC))
        self.assertEqual(len(warns), 1, warns)
        self.assertIn("LESSON-029", warns[0])
        self.assertIn("card_form_map", warns[0])

    def test_numbers_on_statement_card_error_in_produced_longform(self) -> None:
        rep = self._report("statement-card", dict(self.SPEC), target={
            "mode": "longform", "scope": "produced"})
        self.assertEqual(rep.warnings, [])
        self.assertEqual(len(rep.errors), 1, rep.errors)
        self.assertIn("LESSON-029", rep.errors[0])

    def test_numbers_on_statement_card_remain_advisory_in_light_scope(self) -> None:
        rep = self._report("statement-card", dict(self.SPEC), target={
            "mode": "longform", "scope": "light"})
        self.assertEqual(rep.errors, [])
        self.assertEqual(len(rep.warnings), 1, rep.warnings)

    def test_a_comparison_family_kind_is_legal(self) -> None:
        for kind in MOTION["card_form_map"]["comparison"]:
            self.assertEqual(self._warns(kind, dict(self.SPEC)), [], kind)

    def test_one_numeric_token_is_below_the_floor(self) -> None:
        self.assertEqual(
            self._warns("statement-card", {"headline": "91.9 is the score"}),
            [])

    def test_no_spoken_comparative_marker_no_warn(self) -> None:
        words = _words("the score moved to 91.9 and then 85.6 on the bench")
        self.assertEqual(
            self._warns("statement-card", dict(self.SPEC), words=words), [])

    def test_comparative_spoken_outside_the_window_no_warn(self) -> None:
        # near_s = 3.0 → the 10-14s card hears [7,17]s; speak "versus" at 40s.
        words = _words("the numbers moved a lot") + \
            _words("versus the old run", start=40.0)
        self.assertEqual(
            self._warns("statement-card", dict(self.SPEC), words=words), [])

    def test_evidence_and_icon_slots_owe_no_form(self) -> None:
        spec = {"headline": "The numbers moved.",
                "evidence1": "91.9 vs 85.6", "iconFile": "chart-2.svg"}
        self.assertEqual(self._warns("statement-card", spec), [])

    def test_caption_layer_kinds_are_exempt(self) -> None:
        for kind in MOTION["variety"]["layer_kinds"]:
            self.assertEqual(self._warns(kind, dict(self.SPEC)), [], kind)


# --------------------------------------------------- LL-016 variety doctrine --
def _vg(start: float, kind: str, spec: dict | None = None) -> dict:
    return {"outStart": start, "outEnd": start + 3.0, "kind": kind,
            "anchor": "free-band", "spec": spec or {}}


def _variety_report(graphics: list[dict], mode: str = "longform",
                    scope: str | None = "produced",
                    out_dur: float | None = None,
                    lanes: dict | None = None) -> pl.Report:
    target: dict = {"mode": mode}
    if scope is not None:
        target["scope"] = scope
    if lanes is not None:
        target["lanes"] = lanes
    bound = [{**row, "id": f"g-{index:08x}",
              "semanticBeatId": f"test-beat-{index}"}
             for index, row in enumerate(graphics)]
    decisions = [{"beatId": row["semanticBeatId"], "decision": "graphic",
                  "kind": row["kind"], "graphicId": row["id"]}
                 for row in bound]
    rep = pl.Report()
    plv.check_variety({"target": target, "graphicsTrack": bound,
                       "graphicsDecisions": decisions},
                      mode, rep, out_dur)
    return rep


def _variety_findings(graphics: list[dict], mode: str = "longform",
                      scope: str | None = "produced",
                      out_dur: float | None = None) -> list[str]:
    rep = _variety_report(graphics, mode, scope, out_dur)
    return rep.errors + rep.warnings


class ConsecutiveKindTests(unittest.TestCase):
    """LL-016(a) — never the same form twice in a row."""

    def test_back_to_back_same_kind_errors_for_produced_longform(self) -> None:
        rep = _variety_report([_vg(10, "statement-card"),
                               _vg(20, "statement-card")])
        self.assertEqual(len(rep.errors), 1, rep.errors)
        self.assertEqual(rep.warnings, [])
        self.assertIn("LESSON-030", rep.errors[0])

    def test_three_distinct_alternating_kinds_are_clean(self) -> None:
        self.assertEqual(_variety_findings([_vg(10, "statement-card"),
                                            _vg(20, "glass-rail"),
                                            _vg(30, "whiteboard-list")]), [])

    def test_statements_chain_is_a_deliberate_swap(self) -> None:
        # NATEHERK_CARDS #19: the kicker swaps IN PLACE on the same chassis.
        findings = _variety_findings([
            _vg(10, "statement-card"),
            _vg(20, "statement-card", {"statements": "Hold it.|DAY ONE."})])
        self.assertEqual(findings, [])

    def test_caption_layer_repeats_are_exempt(self) -> None:
        kind = MOTION["variety"]["layer_kinds"][0]
        self.assertEqual(_variety_findings([_vg(10, kind), _vg(20, kind)]), [])

    def test_a_caption_layer_does_not_break_adjacency(self) -> None:
        # Two cards separated only by a caption layer ARE consecutive.
        kind = MOTION["variety"]["layer_kinds"][0]
        rep = _variety_report([_vg(10, "stat-card"), _vg(15, kind),
                               _vg(20, "stat-card")])
        self.assertEqual(len(rep.errors), 1, rep.errors)

    def test_three_in_a_row_errors_per_pair(self) -> None:
        rep = _variety_report([_vg(10, "chip-row"), _vg(20, "chip-row"),
                               _vg(30, "chip-row")])
        adjacency = [error for error in rep.errors if "graphicsTrack[" in error]
        self.assertEqual(len(adjacency), 2, rep.errors)

    def test_unsorted_track_is_ordered_by_out_start(self) -> None:
        findings = _variety_findings([_vg(30, "whiteboard-list"),
                                      _vg(10, "stat-card"),
                                      _vg(20, "glass-rail")])
        self.assertEqual(findings, [])          # sorted: stat, rail, whiteboard

    def test_shorts_get_the_consecutive_warn_too(self) -> None:
        rep = _variety_report([_vg(5, "chip-row"), _vg(12, "chip-row")],
                              mode="short")
        self.assertEqual(rep.errors, [])
        self.assertEqual(len(rep.warnings), 1, rep.warnings)


class LocalKindDiversityTests(unittest.TestCase):
    """LL-016(c) — retention windows cannot hide under the 6-card global floor."""

    @staticmethod
    def _local(rep: pl.Report, label: str) -> list[str]:
        return [error for error in rep.errors if label in error]

    def test_observed_three_cards_two_kinds_fails_short_output_intro(self) -> None:
        graphics = [_vg(5, "statement-card"), _vg(20, "glass-rail"),
                    _vg(35, "statement-card")]
        rep = _variety_report(graphics, out_dur=44.0)
        errors = self._local(rep, "first minute")
        self.assertEqual(len(errors), 1, rep.errors)
        self.assertIn("[0,44s]", errors[0])
        self.assertIn("3 info-bearing graphic windows / 2 kinds", errors[0])
        self.assertIn("at least 4 windows and 4 distinct", errors[0])

    def test_three_cards_three_kinds_still_fails_absolute_intro_floor(self) -> None:
        graphics = [_vg(5, "statement-card"), _vg(20, "glass-rail"),
                    _vg(35, "whiteboard-list")]
        rep = _variety_report(graphics, out_dur=44.0)
        errors = self._local(rep, "first minute")
        self.assertEqual(len(errors), 1, rep.errors)
        self.assertIn("needs at least 4 windows and 4 distinct", errors[0])

    def test_four_cards_four_kinds_passes_44s_intro_floor(self) -> None:
        graphics = [_vg(5, "statement-card"), _vg(15, "glass-rail"),
                    _vg(25, "whiteboard-list"), _vg(35, "nateherk-pipeline")]
        rep = _variety_report(graphics, out_dur=44.0)
        self.assertEqual(self._local(rep, "first minute"), [])

    def test_four_cards_three_kinds_fails_just_below_duration_threshold(self) -> None:
        graphics = [_vg(4, "statement-card"), _vg(12, "glass-rail"),
                    _vg(21, "whiteboard-list"), _vg(31, "statement-card")]
        rep = _variety_report(graphics, out_dur=39.92)
        errors = self._local(rep, "first minute")
        self.assertEqual(len(errors), 1, rep.errors)
        self.assertIn("4 info-bearing graphic windows / 3 kinds", errors[0])
        self.assertIn("4 distinct forms", errors[0])

    def test_alternating_two_template_intro_fails_below_threshold(self) -> None:
        graphics = [_vg(4, "statement-card"), _vg(12, "glass-rail"),
                    _vg(21, "statement-card"), _vg(31, "glass-rail")]
        rep = _variety_report(graphics, out_dur=39.92)
        errors = self._local(rep, "first minute")
        self.assertEqual(len(errors), 1, rep.errors)
        self.assertIn("4 info-bearing graphic windows / 2 kinds", errors[0])

    def test_four_distinct_forms_pass_just_below_duration_threshold(self) -> None:
        graphics = [_vg(4, "statement-card"), _vg(12, "glass-rail"),
                    _vg(21, "whiteboard-list"), _vg(31, "nateherk-pipeline")]
        rep = _variety_report(graphics, out_dur=39.92)
        self.assertEqual(self._local(rep, "first minute"), [])

    def test_operator_waived_graphics_has_no_absolute_floor(self) -> None:
        rep = _variety_report([], out_dur=44.0, lanes={"graphics": "off"})
        self.assertEqual(self._local(rep, "first minute"), [])

    def test_four_cards_two_kinds_fails_early_three_minute_window(self) -> None:
        graphics = [_vg(5, "statement-card"), _vg(15, "glass-rail"),
                    _vg(25, "whiteboard-list"), _vg(35, "nateherk-pipeline"),
                    _vg(90, "statement-card")]
        rep = _variety_report(graphics, out_dur=150.0)
        errors = self._local(rep, "first three minutes")
        self.assertEqual(len(errors), 1, rep.errors)
        self.assertIn("5 info-bearing graphic windows / 4 kinds", errors[0])
        self.assertIn("at least 6 windows and 5 distinct", errors[0])

    def test_four_cards_three_kinds_passes_early_floor(self) -> None:
        graphics = [_vg(5, "statement-card"), _vg(15, "glass-rail"),
                    _vg(25, "whiteboard-list"), _vg(35, "nateherk-pipeline"),
                    _vg(90, "nateherk-scoreboard"), _vg(130, "statement-card")]
        rep = _variety_report(graphics, out_dur=150.0)
        self.assertEqual(self._local(rep, "first three minutes"), [])

    def test_output_duration_excludes_later_card_from_early_window(self) -> None:
        graphics = [_vg(5, "statement-card"), _vg(15, "glass-rail"),
                    _vg(25, "whiteboard-list"), _vg(35, "nateherk-pipeline"),
                    _vg(90, "nateherk-scoreboard"), _vg(130, "statement-card")]
        rep = _variety_report(graphics, out_dur=120.0)
        self.assertEqual(self._local(rep, "first three minutes"), [])


class KindDiversityTests(unittest.TestCase):
    """LL-016(b) — the produced/full longform distinct-kind floor."""

    def _diversity(self, warns: list[str]) -> list[str]:
        return [w for w in warns if "graphic windows use only" in w]

    def test_two_kinds_over_six_windows_error(self) -> None:
        graphics = [_vg(10 * i, ("stat-card", "glass-rail")[i % 2])
                    for i in range(6)]
        errors = self._diversity(_variety_report(graphics).errors)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("floor 3", errors[0])          # ceil(0.5 × 6)
        self.assertIn("LESSON-030", errors[0])

    def test_three_kinds_over_six_windows_pass(self) -> None:
        kinds = ("stat-card", "glass-rail", "chip-row")
        graphics = [_vg(10 * i, kinds[i % 3]) for i in range(6)]
        self.assertEqual(self._diversity(_variety_findings(graphics)), [])

    def test_ratio_math_at_eight_windows(self) -> None:
        kinds = ("stat-card", "glass-rail", "chip-row")
        graphics = [_vg(10 * i, kinds[i % 3]) for i in range(8)]
        errors = self._diversity(_variety_report(graphics).errors)
        self.assertEqual(len(errors), 1, errors)      # 3 < ceil(0.5 × 8) = 4
        self.assertIn("floor 4", errors[0])

    def test_below_min_windows_is_not_judged(self) -> None:
        graphics = [_vg(10 * i, ("stat-card", "glass-rail")[i % 2])
                    for i in range(5)]
        self.assertEqual(self._diversity(_variety_findings(graphics)), [])

    def test_shorts_are_not_gated(self) -> None:
        graphics = [_vg(3 * i, ("stat-card", "glass-rail")[i % 2])
                    for i in range(6)]
        self.assertEqual(
            self._diversity(_variety_findings(graphics, mode="short")), [])

    def test_trim_and_light_scopes_are_not_gated(self) -> None:
        graphics = [_vg(10 * i, ("stat-card", "glass-rail")[i % 2])
                    for i in range(6)]
        for scope in ("trim", "light"):
            self.assertEqual(
                self._diversity(_variety_findings(graphics, scope=scope)),
                [], scope)

    def test_default_scope_is_produced_and_gated(self) -> None:
        graphics = [_vg(10 * i, ("stat-card", "glass-rail")[i % 2])
                    for i in range(6)]
        errors = self._diversity(_variety_report(graphics, scope=None).errors)
        self.assertEqual(len(errors), 1, errors)

    def test_caption_layers_do_not_count_as_windows(self) -> None:
        layer = MOTION["variety"]["layer_kinds"][0]
        graphics = [_vg(10 * i, ("stat-card", "glass-rail")[i % 2])
                    for i in range(5)] + [_vg(60, layer)]
        self.assertEqual(self._diversity(_variety_findings(graphics)), [])


# ---------------------------------------------------------- prompt wiring --
class LessonWireTests(unittest.TestCase):
    """The Brain lessons are wired into BOTH authoring surfaces (task 2)."""

    @staticmethod
    def _auto_prompt_source() -> str:
        return (_REPO / "src" / "app" / "api" / "producer" / "auto-edit"
                / "authoring-prompt.ts").read_text(encoding="utf-8")

    def test_auto_edit_authoring_prompt_reads_the_ledger(self) -> None:
        ts = self._auto_prompt_source()
        self.assertIn("scripts/producer/docs/findings/FAILURE_LEDGER.md", ts)
        self.assertIn("Brain lessons", ts)
        self.assertIn("MANDATORY", ts)

    def test_skill_step_4_reads_the_ledger(self) -> None:
        skill = (_REPO / ".claude" / "skills" / "producer"
                 / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("docs/findings/FAILURE_LEDGER.md", skill)
        self.assertIn("Brain lessons", skill)

    def test_card_form_map_is_wired_into_both_authoring_surfaces(self) -> None:
        # LL-015/LL-016: one line each pointing the brain at the catalog.
        ts = self._auto_prompt_source()
        self.assertIn("card_form_map", ts)
        self.assertIn("INFORMATION SHAPE", ts)
        skill = (_REPO / ".claude" / "skills" / "producer"
                 / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("card_form_map", skill)


if __name__ == "__main__":
    unittest.main(verbosity=2)
