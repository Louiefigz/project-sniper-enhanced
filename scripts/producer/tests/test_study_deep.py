#!/usr/bin/env python3
"""DEEP STUDY pipeline vs a constructed clip (tests/_deep_synth.py).

The synthetic clip bakes in a KNOWN hard cut, instant card (+OCR text), a
power3-out zoom, a from-left 18-frame sweep, an instant panel-out, a 15-frame
freeze, a bell-eased 40px pan, a white flash and a word-by-word caption bar —
the pipeline must recover each one's type, timing, magnitude and easing.
Pure-function passes (easing fit, karaoke, cues, semantics harness, word
lock) get direct unit tests below the e2e block.
"""

import json
import os
import shutil
import tempfile
import unittest

from _common import *  # noqa: F401,F403

import _deep_synth as synth
from producer_config import BROLL
from study import deep_captions as dcap
from study import deep_easing as dease
from study import deep_semantics as dsem
from study import deep_wordlock as dwl
from study.deep_config import DEEP
from study.study_deep import main as deep_main

_DIR = tempfile.mkdtemp(prefix="deep-study-")
_VIDEO = os.path.join(_DIR, "synthetic.mp4")
_OUT = os.path.join(_DIR, "study")
_DEEP: dict = {}
GT = synth.GROUND_TRUTH


def setUpModule() -> None:
    """Render the clip and run the WHOLE deterministic pipeline once."""
    synth.write_video(_VIDEO)
    os.makedirs(_OUT, exist_ok=True)
    # P1 stub: states OCR is covered by unit tests; a full study_video run
    # here would only slow the suite down.
    with open(os.path.join(_OUT, "fingerprint.json"), "w") as fh:
        json.dump({"states": []}, fh)
    words_path = os.path.join(_DIR, "words.json")
    with open(words_path, "w") as fh:
        json.dump(synth.synthetic_words(), fh)
    import sys
    argv, sys.argv = sys.argv, ["study_deep.py", _VIDEO, _OUT,
                                "--transcript", words_path]
    try:
        rc = deep_main()
    finally:
        sys.argv = argv
    if rc != 0:
        raise RuntimeError("study_deep exited nonzero on the synthetic clip")
    with open(os.path.join(_OUT, "deep_study.json")) as fh:
        _DEEP.update(json.load(fh))


def tearDownModule() -> None:
    shutil.rmtree(_DIR, ignore_errors=True)


def _events(etype: str) -> list[dict]:
    return [e for e in _DEEP["events"] if e["type"] == etype]


def _near(events: list[dict], t: float, tol: float = 0.15) -> dict:
    hits = [e for e in events if abs(e["t"] - t) <= tol]
    if not hits:
        raise AssertionError(
            f"no event near t={t} in {[(e['type'], e['t']) for e in events]}")
    return hits[0]


class CutAndFlashTests(unittest.TestCase):
    def test_hard_cut_recovered(self) -> None:
        cut = _near(_events("cut"), GT["cutT"])
        self.assertEqual(cut["transition"]["class"], "hard-cut")
        self.assertGreaterEqual(cut["coverage"], 0.55)

    def test_flash_recovered_and_merged(self) -> None:
        flashes = _events("flash")
        self.assertEqual(len(flashes), 1)
        self.assertAlmostEqual(flashes[0]["t"], GT["flashT"], delta=0.15)

    def test_jump_cut_is_cut_with_punch_never_eased_zoom(self) -> None:
        """Fix 2+4: a <=3-frame scale step = class 'cut' with punch
        magnitude, NEVER an eased zoom (the acid phantom-zoom failure)."""
        cut = _near(_events("cut"), GT["jumpCutT"])
        self.assertLessEqual(cut["transition"]["frames"], 3)
        self.assertEqual(cut["detail"].get("punch"), "in")
        self.assertAlmostEqual(cut["detail"]["dScalePct"],
                               GT["jumpPunchPct"],
                               delta=0.5 * GT["jumpPunchPct"])
        phantom = [e for e in _DEEP["events"] if e["type"].startswith("zoom")
                   and abs(e["t"] - GT["jumpCutT"]) < 0.4]
        self.assertFalse(phantom, f"phantom eased zoom at the jump cut: "
                                  f"{phantom}")


class GraphicEventTests(unittest.TestCase):
    def test_card_in_out_with_bbox(self) -> None:
        card = _near(_events("graphic-in"), GT["cardInT"])
        _near(_events("graphic-out"), GT["cardOutT"])
        for got, want in zip(card["bbox"], GT["cardBboxNorm"]):
            self.assertAlmostEqual(got, want, delta=0.08)

    def test_panel_sweep_direction_and_frames(self) -> None:
        panel = _near(_events("panel-in"), GT["sweepT"])
        self.assertEqual(panel["transition"]["class"], "sweep")
        self.assertEqual(panel["transition"]["direction"],
                         GT["sweepDirection"])
        self.assertAlmostEqual(panel["transition"]["frames"],
                               GT["sweepFrames"], delta=4)
        _near(_events("panel-out"), GT["panelOutT"])

    def test_keyword_pop_in_and_out(self) -> None:
        """Fix 1: instant localized pops the d-metric misses (pop scan)."""
        pop = _near(_events("graphic-in"), GT["popT"])
        self.assertEqual(pop["transition"]["class"], "pop")
        self.assertLessEqual(pop["transition"]["frames"], 2)
        _near(_events("graphic-out"), GT["popOutT"])


class MotionEventTests(unittest.TestCase):
    def test_zoom_magnitude_and_easing(self) -> None:
        zoom = _near(_events("zoom-in"), GT["zoomT"], tol=0.25)
        self.assertAlmostEqual(zoom["magnitude"], GT["zoomMagnitude"],
                               delta=0.06)
        self.assertGreaterEqual(zoom["durationFrames"], 15)
        self.assertLessEqual(zoom["durationFrames"], 34)
        self.assertEqual(zoom["easing"]["bestFit"], GT["zoomEasing"])
        self.assertGreaterEqual(zoom["easing"]["r2"], 0.9)

    def test_pan_magnitude_direction_easing(self) -> None:
        pan = _near(_events("pan"), GT["panT"], tol=0.25)
        self.assertAlmostEqual(pan["magnitude"], GT["panPx"], delta=10)
        self.assertEqual(pan["detail"]["direction"], GT["panDirection"])
        self.assertEqual(pan["easing"]["bestFit"], GT["panEasing"])

    def test_freeze_recovered(self) -> None:
        frz = _near(_events("freeze"), GT["freezeT"], tol=0.2)
        self.assertAlmostEqual(frz["durationFrames"], GT["freezeFrames"],
                               delta=2)
        self.assertGreaterEqual(len(_DEEP["freezes"]), 1)

    def test_no_motion_span_left_unexplained(self) -> None:
        self.assertLessEqual(_DEEP["unclassifiedRuns"], 1)


class TextPassTests(unittest.TestCase):
    def _graphic(self, t: float) -> dict:
        hits = [g for g in _DEEP["text"]["graphics"] if abs(g["t"] - t) <= 0.2]
        self.assertTrue(hits, f"no OCR readout near t={t}")
        return hits[0]

    def test_card_text_and_colors(self) -> None:
        card = self._graphic(GT["cardInT"])
        self.assertIn("HELLO", card["text"].upper())
        self.assertIn("WORLD", card["text"].upper())
        self.assertGreater(card["heightFracH"], 0.03)
        # white glyphs on a near-black card
        self.assertGreater(int(card["textColor"][1:3], 16), 160)
        self.assertLess(int(card["bgColor"][1:3], 16), 80)

    def test_per_word_appearance_timing(self) -> None:
        bar = self._graphic(GT["barInT"])
        seen = {w["word"].upper(): w["t"] for w in bar["words"]}
        for word, t_in in GT["wordsT"].items():
            self.assertIn(word, seen)
            self.assertAlmostEqual(seen[word], t_in, delta=0.25)

    def test_caption_system_stats(self) -> None:
        caps = _DEEP["text"]["captions"]
        self.assertTrue(caps["detected"])
        self.assertEqual(caps["positionBand"], "bottom")
        self.assertGreaterEqual(caps["cues"], 2)
        self.assertFalse(caps["karaoke"])


class WordLockTests(unittest.TestCase):
    def test_stats_present_and_cut_locked(self) -> None:
        wl = _DEEP["wordLock"]
        self.assertGreater(wl["words"], 0)
        self.assertIsNotNone(wl["medianAbsDtS"])
        cut_rows = [r for r in wl["events"]
                    if r["type"] == "cut" and abs(r["t"] - GT["cutT"]) < 0.2]
        self.assertTrue(cut_rows)
        self.assertLessEqual(cut_rows[0]["dtS"], 0.08)

    def test_semantics_skipped_by_default(self) -> None:
        self.assertEqual(_DEEP["semantics"], {"ran": False})


class EasingFitUnitTests(unittest.TestCase):
    def _fit(self, fn, n: int = 24) -> dict:
        path = [fn(i / (n - 1)) for i in range(n)]
        return dease.fit_easing(path)

    def test_each_model_recovers_itself(self) -> None:
        cases = {"linear": lambda u: u,
                 "power2-out": lambda u: 1 - (1 - u) ** 2,
                 "power3-out": lambda u: 1 - (1 - u) ** 3,
                 "bell": lambda u: u * u * (3 - 2 * u)}
        for name, fn in cases.items():
            fit = self._fit(fn)
            self.assertEqual(fit["bestFit"], name, f"{name} misfit: {fit}")
            self.assertGreaterEqual(fit["r2"], 0.99)

    def test_short_or_flat_paths_return_none(self) -> None:
        self.assertIsNone(dease.fit_easing([0.0, 1.0]))
        self.assertIsNone(dease.fit_easing([1.0] * 10))


class CaptionUnitTests(unittest.TestCase):
    def test_karaoke_detected_on_word_color_change(self) -> None:
        frames = [{"HELLO": (240, 240, 240), "WORLD": (240, 240, 240)},
                  {"HELLO": (250, 180, 40), "WORLD": (240, 240, 240)}]
        self.assertTrue(dcap.detect_karaoke(frames))

    def test_no_karaoke_on_stable_colors(self) -> None:
        frames = [{"HELLO": (240, 240, 240)}, {"HELLO": (235, 238, 244)}]
        self.assertFalse(dcap.detect_karaoke(frames))

    def test_cues_merge_similar_texts_only(self) -> None:
        obs = [dcap.BandObs(t=0.0, text="ONE"),
               dcap.BandObs(t=0.5, text="ONE"),
               dcap.BandObs(t=1.0, text="TOTALLY DIFFERENT"),
               dcap.BandObs(t=1.5, text="")]
        cues = dcap.cues_from_obs(obs)
        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0]["tEnd"], 0.5)


class SemanticsHarnessUnitTests(unittest.TestCase):
    def test_claude_model_is_explicit_and_safe(self) -> None:
        previous = os.environ.pop("SNIPER_CLAUDE_MODEL", None)
        def restore() -> None:
            if previous is None:
                os.environ.pop("SNIPER_CLAUDE_MODEL", None)
            else:
                os.environ["SNIPER_CLAUDE_MODEL"] = previous

        self.addCleanup(restore)
        self.assertEqual(dsem.claude_model(), "sonnet")
        os.environ["SNIPER_CLAUDE_MODEL"] = "claude-sonnet-4-6[1m]"
        self.assertEqual(dsem.claude_model(), "claude-sonnet-4-6[1m]")
        os.environ["SNIPER_CLAUDE_MODEL"] = "--model injection"
        with self.assertRaises(RuntimeError):
            dsem.claude_model()

    def test_parse_reply_enforces_schema(self) -> None:
        good = '{"kindGuess": "stat-card", "stylingTokens": ["serif"], ' \
               '"layout": "centered"}'
        self.assertEqual(dsem.parse_reply(good)["kindGuess"], "stat-card")
        with self.assertRaises(ValueError):
            dsem.parse_reply('{"kindGuess": "x", "stylingTokens": "not-a-list"}')
        with self.assertRaises(ValueError):
            dsem.parse_reply("no json here")

    def test_run_semantics_with_injected_spawn(self) -> None:
        from study.deep_frames import probe_video
        info = probe_video(_VIDEO)
        events = [e for e in _DEEP["events"] if e["type"] == "graphic-in"][:1]
        reply = '{"kindGuess": "lower-third", "stylingTokens": ["mono"], ' \
                '"layout": "bottom bar"}'
        result = dsem.run_semantics(_VIDEO, info, events, _OUT,
                                    spawn=lambda prompt: reply)
        self.assertTrue(result["ran"])
        self.assertEqual(result["events"][0]["kindGuess"], "lower-third")
        for path in result["events"][0]["frames"]:
            self.assertTrue(os.path.isfile(path))

    def test_bad_reply_recorded_as_event_error(self) -> None:
        from study.deep_frames import probe_video
        info = probe_video(_VIDEO)
        events = [e for e in _DEEP["events"] if e["type"] == "graphic-in"][:1]
        result = dsem.run_semantics(_VIDEO, info, events, _OUT,
                                    spawn=lambda prompt: "not json")
        self.assertIn("error", result["events"][0])


class WordLockUnitTests(unittest.TestCase):
    def test_stats_arithmetic(self) -> None:
        words = [{"word": "a", "start": 1.0, "end": 1.4}]
        events = [{"id": "ev-001", "t": 1.05, "type": "cut"},
                  {"id": "ev-002", "t": 2.0, "type": "flash"}]
        stats = dwl.word_lock_stats(events, words, {"transcriptPath": "x"})
        self.assertAlmostEqual(stats["events"][0]["dtS"], 0.05, places=4)
        self.assertAlmostEqual(stats["events"][1]["dtS"], 0.6, places=4)
        self.assertEqual(stats["within150msPct"], 50.0)

    def test_no_words_reports_skip_shape(self) -> None:
        stats = dwl.word_lock_stats([], [], {"skipped": "why"})
        self.assertEqual(stats["skipped"], "why")
        self.assertIsNone(stats["medianAbsDtS"])


# SYNTHETIC ``cueTexts`` shaped like the LL-012 false positives: OCR'd text
# from the screen-share region of a long-form with NO caption track. Each list
# holds 40 cues; most are ordinary on-screen text, and a minority are editor
# chrome or file paths (list A: 3 path-char cues + 2 chrome-token cues =
# 0.125; list B: 2 path-char cues + 5 chrome-token cues = 0.175). Original
# text written for this test — no third-party material.
_SCREEN_SHARE_CUES_A = [
    "Welcome back", "Chapter two", "Weekly plan", "Draft outline",
    "Intro hook", "Section one", "Notes", "Review pass", "Scene list",
    "Shot three", "Voice take", "Rough cut", "Morning block", "Plan B",
    "Team sync", "Open questions", "Next steps", "Budget", "Launch",
    "/Users/editor/Projects/launch", "Q3 goals", "Checklist", "Ideas",
    "EXPORT_FINAL_V2.MOV", "Script v4", "Topic map", "Outline",
    "C:\\Clips\\intro", "Frame rate: 30 fps", "Aspect ratio 16:9",
    "Priorities", "Summary", "Key points", "Wrap up", "Thanks",
    "Recap", "Part three", "Timing", "Hook ideas", "Closing line",
]
_SCREEN_SHARE_CUES_B = [
    "Getting started", "Menu", "Edit", "View", "Window", "Help",
    "Inspector", "Library", "Sequence one", "Marker", "Title card",
    "Stock library", "Download settings", "Resolution 1920",
    "Stickers panel", "Sort files by name", "Track one", "Track two",
    "Master", "Levels", "Speed", "Crop", "Transform", "Opacity",
    "Blend mode", "Normal", "Keyframes", "Zoom", "Fit", "Snapping",
    "/Volumes/Media/raw", "draft_v3_notes", "Playhead", "In point",
    "Out point", "Duration", "Render", "Preview", "Share", "Done",
]


class CaptionChromeGateTests(unittest.TestCase):
    """LL-012: screen-share false positives (synthetic, same shape) must
    clear the UI-chrome rejection threshold, while genuine caption text
    stays under."""

    # Synthetic genuine caption lines of an editing walkthrough — they
    # deliberately include the speakable UI vocabulary such a walkthrough's
    # real captions use (import / timeline / color / desktop).
    GENUINE = [
        "so the first thing we do is import",
        "drag the clip onto the timeline here",
        "then we fix the color before anything else",
        "save it to the desktop for now",
        "this is where most people get stuck",
        "trim the start so it opens on action",
        "and now the whole sequence plays clean",
        "let me show you why that matters",
    ]

    def test_screen_share_chrome_list_a_rejected(self) -> None:
        self.assertGreaterEqual(dcap.chrome_cue_fraction(_SCREEN_SHARE_CUES_A),
                                DEEP["caption_chrome_max_frac"])

    def test_screen_share_chrome_list_b_rejected(self) -> None:
        self.assertGreaterEqual(dcap.chrome_cue_fraction(_SCREEN_SHARE_CUES_B),
                                DEEP["caption_chrome_max_frac"])

    def test_genuine_caption_text_passes(self) -> None:
        self.assertLess(dcap.chrome_cue_fraction(self.GENUINE),
                        DEEP["caption_chrome_max_frac"])
        for cue in self.GENUINE:
            self.assertFalse(dcap.cue_is_chrome(cue), cue)

    def test_path_chars_and_chrome_tokens_flag_cues(self) -> None:
        self.assertTrue(dcap.cue_is_chrome("/Users/editor/Projects"))
        self.assertTrue(dcap.cue_is_chrome("EXPORT_FINAL_V2.MOV"))
        self.assertTrue(dcap.cue_is_chrome("(1) Aspect ratio 16:9"))
        self.assertFalse(dcap.cue_is_chrome("ONE TWO THREE"))
        self.assertEqual(dcap.chrome_cue_fraction([]), 0.0)


# SYNTHETIC word-timed caption file in the roll-up VTT shape (a plain
# roll-over line, a <c>-tagged payload line, a 10 ms repeat cue, then a
# repeat line plus a new payload line) — the LL-013 citation source shape.
# Original text written for this test.
_SYNTHETIC_VTT_EXCERPT = """WEBVTT
Kind: captions
Language: en

00:12:05.200 --> 00:12:07.040 align:start position:0%
and the reason this works is the
30-second<00:12:05.760><c> checklist</c><00:12:06.300><c> keeps</c><00:12:06.420><c> every</c><00:12:06.560><c> edit</c><00:12:06.700><c> on</c><00:12:06.880><c> track</c>

00:12:07.040 --> 00:12:07.050 align:start position:0%
30-second checklist keeps every edit on track


00:12:07.050 --> 00:12:08.600 align:start position:0%
30-second checklist keeps every edit on track
because<00:12:07.400><c> it</c><00:12:07.560><c> is</c><00:12:07.740><c> short</c><00:12:07.980><c> enough</c><00:12:08.320><c> to</c>
"""


class VttWordTests(unittest.TestCase):
    """LL-013: ``parse_vtt_words`` reads word timings from a VTT and a
    sibling .vtt auto-discovers — the wordLock pass runs without an API, so
    word-timed citations can be machine-read instead of hand-copied."""

    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="vtt-words-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.vtt = os.path.join(self.dir, "ref.en.vtt")
        with open(self.vtt, "w", encoding="utf-8") as fh:
            fh.write(_SYNTHETIC_VTT_EXCERPT)

    def test_synthetic_excerpt_word_timing(self) -> None:
        words = dwl.parse_vtt_words(self.vtt)
        by = {w["word"]: w for w in words}
        self.assertAlmostEqual(by["30-second"]["start"], 725.2, places=3)
        self.assertAlmostEqual(by["checklist"]["start"], 725.76, places=3)
        self.assertAlmostEqual(by["track"]["end"], 727.04, places=3)
        # roll-up repeat lines contribute no duplicate words
        self.assertEqual(sum(1 for w in words if w["word"] == "checklist"), 1)

    def test_citation_read_from_word_timings_sits_inside_trigger_band(self) -> None:
        """A trigger phrase starting at 725.2s with inserts at +0.9s / +1.15s
        is inside ``BROLL['trigger_latency_s']`` (EDITCRAFT_LESSONS §2.1)."""
        words = dwl.parse_vtt_words(self.vtt)
        start = {w["word"]: w["start"] for w in words}["30-second"]
        lo, hi = BROLL["trigger_latency_s"]
        for insert_t in (726.1, 726.35):
            self.assertGreaterEqual(insert_t - start, lo)
            self.assertLessEqual(insert_t - start, hi)

    def test_sibling_vtt_autodiscovery(self) -> None:
        video = os.path.join(self.dir, "ref.webm")
        with open(video, "w") as fh:
            fh.write("")
        out_dir = os.path.join(self.dir, "out")
        os.makedirs(out_dir)
        words, meta = dwl.load_words(video, out_dir, None)
        self.assertEqual(meta.get("source"), "vtt-sibling")
        self.assertTrue(meta["transcriptPath"].endswith("ref.en.vtt"))
        self.assertTrue(any(w["word"] == "checklist" for w in words))

    def test_explicit_transcript_accepts_vtt_path(self) -> None:
        words, meta = dwl.load_words(os.path.join(self.dir, "none.mp4"),
                                     self.dir, self.vtt)
        self.assertTrue(any(w["word"] == "30-second" for w in words))
        self.assertTrue(meta["transcriptPath"].endswith(".vtt"))

    def test_cue_level_vtt_fails_loudly(self) -> None:
        path = os.path.join(self.dir, "plain.vtt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nhello world\n")
        with self.assertRaises(ValueError):
            dwl.parse_vtt_words(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
