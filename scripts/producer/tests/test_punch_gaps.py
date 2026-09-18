"""Punch reproduction-gap tests (G1-G5, G17 + music assets — PUNCH_STYLE.md).

Covers: the WHISPER caption preset (G2), exit-on-cut clamp math + lint (G4),
the blur+desat takeover base vocabulary + filter graph (G5), the style-aware
punch ceiling (G17), and the builtin starter-bed registration (assets/music).
The shout-lockup comp (G1/G3) is exercised by a real hyperframes render in the
verification pass; here we assert its contract surface (template exists, comps
conventions present).
"""
import copy
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from _common import *  # noqa: F401,F403

_REPO = Path(__file__).resolve().parents[3]           # PROJECT_SNIPER
_HAVE_FF = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


# --------------------------------------------------------------------------- #
# G2 — whisper caption preset
# --------------------------------------------------------------------------- #
class WhisperCaptionTests(unittest.TestCase):
    """CAP1/CAP2/CAP3: 1-3 word verbatim cues, sentence case, no karaoke,
    inline amber tier-A emphasis, y0.60-0.64 band at center x0.5."""

    WORDS = [
        {"word": "we", "start": 0.0, "end": 0.2},
        {"word": "cut", "start": 0.2, "end": 0.4},
        {"word": "the", "start": 0.4, "end": 0.6},
        {"word": "filler", "start": 0.6, "end": 0.9},
        {"word": "zero", "start": 1.5, "end": 1.8},
        {"word": "sales.", "start": 1.8, "end": 2.1},
        {"word": "next", "start": 2.2, "end": 2.4},
    ]
    M = cap.CAPTIONS["WHISPER"]

    def test_cue_grouping_1_to_3_words_and_sentence_seam(self) -> None:
        cues = cw._whisper_cues(cap._merge_punctuation(self.WORDS), self.M)
        texts = [[w["word"] for w in c] for c in cues]
        # 3-word cap; sentence end ("sales.") closes the cue so "next" never
        # joins it despite the 0.1s gap.
        self.assertEqual(texts, [["we", "cut", "the"], ["filler"],
                                 ["zero", "sales."], ["next"]])

    def test_style_geometry_and_no_karaoke(self) -> None:
        ass = cap.build_ass(self.WORDS, "whisper")
        # 2.2%H face (42px @1920), soft shadow, NO outline (CAP2 row).
        self.assertIn("Style: Whisper,Inter,42,", ass)
        # Band center: mean(0.60, 0.64) * 1920 = 1190; center x = 540 (x0.5).
        self.assertIn("\\pos(540,1190)", ass)
        # CAP1: karaoke sweep rate ZERO — no \k tags anywhere.
        self.assertNotIn("\\k", ass)
        self.assertEqual(ass.count("Dialogue:"), 4)

    def test_sentence_case(self) -> None:
        ass = cap.build_ass(self.WORDS, "whisper")
        self.assertIn("We cut the", ass)      # sentence start capitalized
        self.assertIn("}filler", ass)         # mid-sentence cue stays verbatim
        self.assertIn("Next", ass)            # cue after "sales." capitalized

    def test_inline_amber_from_first_frame(self) -> None:
        cfg = {**cap.CAPTIONS, "emphasisWords": ["zero"]}
        ass = cap.build_ass(self.WORDS, "whisper", cfg)
        # CAP3: tier-A tint is an INLINE override on the cue's first frame —
        # #F2D24B -> ASS BGR 4BD2F2, reset with bare \c; never its own event.
        self.assertIn("{\\c&H4BD2F2&}zero{\\c}", ass)
        self.assertEqual(ass.count("Dialogue:"), 4)   # no extra accent events

    def test_lint_accepts_whisper_style(self) -> None:
        plan = good_plan()
        plan["captions"]["style"] = "whisper"
        errors = pl.lint(plan, MANIFEST).errors
        self.assertFalse([e for e in errors if "captions.style" in e], errors)

    def test_event_count(self) -> None:
        self.assertEqual(cw.event_count(self.WORDS), 4)


# --------------------------------------------------------------------------- #
# G4 — exit-on-cut clamp math + lint wiring
# --------------------------------------------------------------------------- #
def _two_cut_plan(graphics: list[dict]) -> dict:
    """Three-segment cutTrack: output [0,10) + [10,18) + [18,23).

    Segment 2 runs 10s of source at speed 1.25 -> 8s of output, so the second
    seam (18.0) proves seam math is speed-aware, not source-time arithmetic.
    """
    plan = good_plan()
    plan["cutTrack"] = [
        {"sourceId": "raw-1", "start": 0.0, "end": 10.0, "speed": 1.0},
        {"sourceId": "raw-1", "start": 30.0, "end": 40.0, "speed": 1.25},
        {"sourceId": "raw-1", "start": 50.0, "end": 55.0, "speed": 1.0},
    ]
    plan["graphicsTrack"] = graphics
    return plan


def _gfx(**over) -> dict:
    entry = {"outStart": 8.0, "outEnd": 12.0, "kind": "punch-shout-lockup",
             "anchor": "free-band", "reason": "keyword lockup",
             "spec": {"payload": "Creating"}}
    entry.update(over)
    return entry


class ExitOnCutTests(unittest.TestCase):
    def test_seams_from_plan_speed_aware(self) -> None:
        # Seam 2 = 10 + 10/1.25 = 18.0 (output time, not source arithmetic).
        self.assertEqual(eoc.seams_from_plan(_two_cut_plan([])), [10.0, 18.0])

    def test_clamp_to_next_seam(self) -> None:
        seams = [10.0]
        self.assertEqual(eoc.effective_out_end(
            _gfx(outEnd=14.0, exitOnCut=True), seams), 10.0)

    def test_no_seam_after_start_leaves_end(self) -> None:
        self.assertEqual(eoc.effective_out_end(
            _gfx(outStart=12.0, outEnd=14.0, exitOnCut=True), [10.0]), 14.0)

    def test_flag_off_is_identity(self) -> None:
        self.assertEqual(eoc.effective_out_end(
            _gfx(outEnd=14.0), [10.0]), 14.0)

    def test_apply_returns_clamped_copy_and_count(self) -> None:
        plan = _two_cut_plan([_gfx(outEnd=12.0, exitOnCut=True), _gfx()])
        track, clamped = eoc.apply_exit_on_cut(plan)
        self.assertEqual(clamped, 1)
        self.assertEqual(track[0]["outEnd"], 10.0)
        self.assertEqual(track[1]["outEnd"], 12.0)
        # The plan itself is never mutated (render-time projection only).
        self.assertEqual(plan["graphicsTrack"][0]["outEnd"], 12.0)

    def test_no_flags_is_passthrough(self) -> None:
        plan = _two_cut_plan([_gfx()])
        original = copy.deepcopy(plan)
        track, clamped = eoc.apply_exit_on_cut(plan)
        self.assertEqual(clamped, 0)
        self.assertEqual(track, plan["graphicsTrack"])
        self.assertEqual(plan, original)

    def test_lint_rejects_non_boolean_flag(self) -> None:
        plan = _two_cut_plan([_gfx(exitOnCut="yes")])
        errors = pl.lint(plan, MANIFEST).errors
        self.assertTrue(any("exitOnCut must be a boolean" in e for e in errors),
                        errors)

    def test_lint_warns_when_clamp_collapses_hold(self) -> None:
        # outStart 9.5 -> clamp to seam 10.0 -> 0.5s hold < hold_min 1.0.
        plan = _two_cut_plan([_gfx(outStart=9.5, outEnd=14.0, exitOnCut=True)])
        rep = pl.lint(plan, MANIFEST)
        self.assertTrue(any("exitOnCut clamps" in w for w in rep.warnings),
                        rep.warnings)

    def test_lint_clean_flagged_entry(self) -> None:
        plan = _two_cut_plan([_gfx(exitOnCut=True)])
        errors = pl.lint(plan, MANIFEST).errors
        self.assertFalse([e for e in errors if "exitOnCut" in e], errors)


# --------------------------------------------------------------------------- #
# G5 — blur+desat takeover base
# --------------------------------------------------------------------------- #
class TakeoverBaseTests(unittest.TestCase):
    def test_vocabulary(self) -> None:
        self.assertEqual(eoc.entry_errors(
            {"takeoverBase": "blur-desat", "anchor": "free-band"}, "t"), [])
        errs = eoc.entry_errors({"takeoverBase": "vhs"}, "t")
        self.assertTrue(any("not in" in e for e in errs), errs)

    def test_illegal_anchors(self) -> None:
        for anchor in ("own-screen", "focus-shift"):
            errs = eoc.entry_errors(
                {"takeoverBase": "blur-desat", "anchor": anchor}, "t")
            self.assertTrue(any("illegal with anchor" in e for e in errs),
                            (anchor, errs))

    def test_lint_accepts_blur_desat_entry(self) -> None:
        plan = _two_cut_plan([_gfx(takeoverBase="blur-desat", exitOnCut=True)])
        errors = pl.lint(plan, MANIFEST).errors
        self.assertFalse([e for e in errors if "takeoverBase" in e], errors)

    def test_graph_blurs_and_desats_under_window(self) -> None:
        clip = {"path": "x.mov", "outStart": 1.0, "outEnd": 2.0,
                "takeoverBase": "blur-desat"}
        graph, final = gs._build_graph([clip])
        self.assertIn("gblur=sigma=24,hue=s=0", graph)
        self.assertEqual(graph.count("between(t,1.0000,2.0000)"), 2)  # base + comp
        # The comp still overlays ON TOP of the treated base.
        self.assertIn("overlay=enable", graph)

    def test_graph_without_flag_is_untouched(self) -> None:
        clip = {"path": "x.mov", "outStart": 1.0, "outEnd": 2.0}
        graph, _ = gs._build_graph([clip])
        self.assertNotIn("gblur", graph)
        self.assertNotIn("hue=s=0", graph)


# --------------------------------------------------------------------------- #
# G17 — style-aware punch ceiling
# --------------------------------------------------------------------------- #
class PunchCeilingTests(unittest.TestCase):
    def _errors(self, zoom: float, pace: str | None = None) -> list[str]:
        plan = good_plan()
        if pace:
            plan["target"]["pace"] = pace
        plan["punchIns"] = [{"outStart": 5.0, "outEnd": 7.0, "zoom": zoom}]
        return [e for e in pl.lint(plan, MANIFEST).errors if "zoom" in e]

    def test_default_cap_stays_125(self) -> None:
        self.assertTrue(self._errors(1.35))          # over the 1.25 doctrine cap
        self.assertFalse(self._errors(1.2))

    def test_punch_cap_admits_measured_band(self) -> None:
        # Measured biggest legal step x1.44 (DaG @17.0) -> profile cap 1.45.
        self.assertFalse(self._errors(1.35, pace="punch"))
        self.assertFalse(self._errors(1.45, pace="punch"))

    def test_punch_cap_rejects_outlier(self) -> None:
        # The x1.92 Daf outlier is NOT admitted.
        self.assertTrue(self._errors(1.5, pace="punch"))

    def test_other_paces_keep_default(self) -> None:
        self.assertTrue(self._errors(1.35, pace="talking-head"))

    def test_profile_value_inside_primitive_hard_band(self) -> None:
        profile = plm.MODES["short"]["pacing_punch"]
        self.assertLessEqual(profile["punch_zoom_max"], pin.ZOOM_MAX_HARD)


# --------------------------------------------------------------------------- #
# Music assets — builtin starter bed registration
# --------------------------------------------------------------------------- #
class BuiltinMusicTests(unittest.TestCase):
    BED = _REPO / "assets" / "music" / "default-bed.mp3"

    def test_default_bed_ships_in_repo(self) -> None:
        self.assertTrue(self.BED.is_file(), self.BED)

    @unittest.skipUnless(_HAVE_FF, "needs ffprobe")
    def test_default_bed_probes_60s(self) -> None:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(self.BED)],
            capture_output=True, text=True, check=True).stdout
        self.assertAlmostEqual(float(out.strip()), 60.0, delta=1.0)

    @unittest.skipUnless(_HAVE_FF, "needs ffmpeg")
    def test_scan_builtin_music_continues_ids_and_dedupes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            track = Path(tmp) / "calm" / "bed.wav"
            track.parent.mkdir()
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                 "-i", "sine=frequency=220:duration=1", str(track)],
                check=True)
            existing = [{"id": "music-1", "path": "/project/track.mp3"}]
            entries = iscan.scan_builtin_music(Path(tmp), existing)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["id"], "music-2")   # ids continue
            self.assertEqual(entries[0]["source"], "builtin")
            self.assertEqual(entries[0]["vibe"], ["calm"])
            self.assertTrue(entries[0]["licensed"])
            # Already-cataloged path is skipped (project music dir IS assets).
            dup = iscan.scan_builtin_music(
                Path(tmp), existing + [{"id": "music-2", "path": str(track)}])
            self.assertEqual(dup, [])

    def test_missing_builtin_dir_is_empty(self) -> None:
        self.assertEqual(iscan.scan_builtin_music(None, []), [])
        self.assertEqual(
            iscan.scan_builtin_music(Path("/nonexistent-xyz"), []), [])

    @unittest.skipUnless(_HAVE_FF, "needs ffprobe")
    def test_bed_resolves_through_music_stage_contract(self) -> None:
        # plan.music.assetId resolution reads manifest music entries by path —
        # a builtin entry must satisfy the same contract (id + existing path).
        entries = iscan.scan_builtin_music(self.BED.parent, [])
        self.assertEqual(entries[0]["id"], "music-1")
        self.assertTrue(os.path.isfile(entries[0]["path"]))


# --------------------------------------------------------------------------- #
# G1/G3 — shout-lockup comp contract surface (render exercised out-of-suite)
# --------------------------------------------------------------------------- #
class ShoutLockupTemplateTests(unittest.TestCase):
    COMP = _REPO / "templates" / "motion" / "compositions" / "punch-shout-lockup.html"
    TOKENS = _REPO / "templates" / "motion" / "tokens.css"
    HELPER = _REPO / "templates" / "motion" / "motion-tokens.js"

    def test_comp_exists_with_house_conventions(self) -> None:
        html = self.COMP.read_text(encoding="utf-8")
        self.assertIn('data-composition-id="punch-shout-lockup"', html)
        self.assertIn("window.__timelines", html)
        self.assertIn("data-composition-variables", html)
        self.assertIn('gsap.timeline({ paused: true })', html)
        self.assertIn("/motion-tokens.js", html)        # consumes G4 tokens

    def test_tokens_css_carries_lemon_and_serif_display(self) -> None:
        css = self.TOKENS.read_text(encoding="utf-8")
        self.assertIn("--lemon: #F5E960", css)
        self.assertIn("--font-serif-display", css)
        self.assertIn('font-family: "ChunkFive"', css)
        self.assertIn("--pop-in-dur", css)

    def test_motion_tokens_helper(self) -> None:
        js = self.HELPER.read_text(encoding="utf-8")
        self.assertIn("__motionTokens", js)
        self.assertIn("POP_IN_S = 2 / FPS", js)          # <=2-frame budget
        self.assertIn("instantOut", js)


if __name__ == "__main__":
    unittest.main()
