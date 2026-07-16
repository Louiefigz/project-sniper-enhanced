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


# Verbatim ``cueTexts`` from the EC1/EC2 deep studies that FALSELY read as a
# detected caption system (LL-012) — editor UI chrome + file paths OCR'd out
# of screen-share zones on longforms with NO caption track.
_EC1_FALSE_CUES = [
    "a", "om", "e 708 SOR",
    "B- TI bd a) on Ton Effects Traraitions C ines 0906 (1) (1) Aspect "
    "ratio: mate...",
    "(0) On J TI Audio Toa Effects Traraitions C wice in mage, nes 0906 "
    "(1) (1) presets Aspect ratio: ock mate... Color 700",
    "TI Be 0906 (1) Data/Projects/ Reo. 709 SOR",
    "TI ‘Stickers Effects Traraitions o> mage, es 0906 (1) at "
    "Data/Projects (1) Aspect ratio: i} mate... i Color spece: Rec. 709 SOR",
    "Tot TI ont Ww mage, (1) Rec. 709 SOR",
    "TI in mage, nes 0906 (1) Be /Users/example-user/Mov a (1 Aspect "
    "ratio: Color space: Reo. 709 SOR",
    "Treraitions a", "SIMPLE", "SIMPLE AS)", "0", "il", "PS", "oe,", "ig",
    "STRUC E a", "ss", "ig", "ge", "1080P", "xX 1080P", "WHICH", "ig",
    "a ig", "ig", "ig", "SIMn", "SIMPLE", "ig", "ig", "ig", "wr ig", "ig",
    "fi", "ig", "an", "as ig", "ig",
]
_EC2_FALSE_CUES = [
    "ora Grap 2024-01-2812-28-| Gra Ge", "mm Ge", "t 10:57", "M wa 9:20",
    "9:20", "3.) 2)", "we", "SCOR", "SCONFLICTS_IMG_3392 MOV [V] ml",
    "6 5 MOV [V] Chi", "SCONFLICTS_IMG_3392 MOV i mi", "Wr",
    "Free Stock Video jo", "Stock Video", "8 Free Stock Video wo HOO",
    "ree Stock Video", "1.) THE HARD TRU", "i", "if t fi Fa", "a t te 4 s",
    "66",
    "2 truths 1 lie Terraria 36 GO TO CHANNEL ANALYTICS G0 TO VIDEO "
    "ANALYTICS SEE COMMENTS (1)",
    "Average percentage viewed 2 truths 1 lie Likes 30 GO TO CHANNEL "
    "ANALYTICS GO TO VIDEO ANALYTICS SEE COMMENTS (1)",
    "Views how to craft the ankh shield in terraria 22% Average "
    "percentage viewed 30 2 truths 1 lie Likes GO TO CHANNEL ANALYTICS "
    "GO TO VIDEO ANALYTICS",
    "8 0 vee Views how to craft the ankh shield in terraria 22% Average "
    "percentage viewed 30 2 truths he Terraria Likes TO VIDEO ANALYTICS "
    "GO TO CHANNEL ANALYTICS",
    "Ranking by views Views 80 terraspark crafting tree 22% how to craft "
    "the ankh shield in terraria Average percentage viewed 2 truths 1 he "
    "Likes",
    "110f10 Last 48 hours wws Ranking by views terraspark crafting tree "
    "Views how to craft the ankh shield in ter Average percentage viewed "
    "22% 2 truths 1 lie Terraria 30 Likes",
    "WHY?", "=r q a", "SS ba", "We a The Best Worst BA",
    "wll The Best Worst BA 1216", "The Best Worst BA Ay", "Se", "bi,", "4",
    "ei a*",
    "Lost in How Freeze to W 2345 Uncle Roger Found IMPRESSIVE FRIED "
    "RICE 1253 Winter Bulk Day",
    "How to NOT ‘reeze to Death! Winter IMPRESSIVE FRIED RICE Uncle "
    "Roger Found THE MOS\" 7",
    "in Uncle Roger Found THE MOST ‘Winter Bulk Armes views month ago",
]


class CaptionChromeGateTests(unittest.TestCase):
    """LL-012: the real EC1/EC2 screen-share false positives must clear the
    UI-chrome rejection threshold, while genuine caption text stays under."""

    # Real caption lines of the SAME tutorial (the EC1 VTT) — deliberately
    # includes the speakable UI vocabulary an editing tutorial legitimately
    # captions (import / timeline / color / desktop).
    GENUINE = [
        "cap cut is without a doubt the best",
        "beginner-friendly editing program and",
        "recommend using the downloadable desktop",
        "content to import your content into cap",
        "in chronological order on the timeline",
        "content color and sound with talking",
        "nice and easy import and organize your",
        "10-step workflow to create YouTube",
    ]

    def test_ec1_screen_share_chrome_rejected(self) -> None:
        self.assertGreaterEqual(dcap.chrome_cue_fraction(_EC1_FALSE_CUES),
                                DEEP["caption_chrome_max_frac"])

    def test_ec2_screen_share_chrome_rejected(self) -> None:
        self.assertGreaterEqual(dcap.chrome_cue_fraction(_EC2_FALSE_CUES),
                                DEEP["caption_chrome_max_frac"])

    def test_genuine_caption_text_passes(self) -> None:
        self.assertLess(dcap.chrome_cue_fraction(self.GENUINE),
                        DEEP["caption_chrome_max_frac"])
        for cue in self.GENUINE:
            self.assertFalse(dcap.cue_is_chrome(cue), cue)

    def test_path_chars_and_chrome_tokens_flag_cues(self) -> None:
        self.assertTrue(dcap.cue_is_chrome("/Users/example-user/Mov"))
        self.assertTrue(dcap.cue_is_chrome("SCONFLICTS_IMG_3392 MOV [V] ml"))
        self.assertTrue(dcap.cue_is_chrome("(1) Aspect ratio: mate..."))
        self.assertFalse(dcap.cue_is_chrome("ONE TWO THREE"))
        self.assertEqual(dcap.chrome_cue_fraction([]), 0.0)


# Verbatim excerpt of the EC1 VTT (the "14-day filmmaker" pitch beat) —
# the corrected §2.1 citation source (LL-013).
_EC1_VTT_EXCERPT = """WEBVTT
Kind: captions
Language: en

00:29:28.480 --> 00:29:30.350 align:start position:0%
free but first let me tell you about
14-day<00:29:29.000><c> filmmaker</c><00:29:29.679><c> if</c><00:29:29.760><c> you</c><00:29:29.840><c> want</c><00:29:29.919><c> to</c><00:29:30.039><c> learn</c>

00:29:30.350 --> 00:29:30.360 align:start position:0%
14-day filmmaker if you want to learn


00:29:30.360 --> 00:29:31.870 align:start position:0%
14-day filmmaker if you want to learn
everything<00:29:30.720><c> there</c><00:29:30.880><c> is</c><00:29:31.080><c> to</c><00:29:31.279><c> shooting</c><00:29:31.720><c> and</c>
"""


class VttWordTests(unittest.TestCase):
    """LL-013: word timings parse straight from a YouTube-style VTT, and a
    sibling .vtt auto-discovers — the wordLock pass runs with zero API, so
    word-timed citations can be machine-read instead of hand-copied."""

    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="vtt-words-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.vtt = os.path.join(self.dir, "ref.en.vtt")
        with open(self.vtt, "w", encoding="utf-8") as fh:
            fh.write(_EC1_VTT_EXCERPT)

    def test_real_ec1_excerpt_word_timing(self) -> None:
        words = dwl.parse_vtt_words(self.vtt)
        by = {w["word"]: w for w in words}
        self.assertAlmostEqual(by["14-day"]["start"], 1768.48, places=3)
        self.assertAlmostEqual(by["filmmaker"]["start"], 1769.0, places=3)
        self.assertAlmostEqual(by["learn"]["end"], 1770.35, places=3)
        # roll-up repeat lines contribute no duplicate words
        self.assertEqual(sum(1 for w in words if w["word"] == "filmmaker"), 1)

    def test_corrected_citation_sits_inside_trigger_band(self) -> None:
        """The §2.1 pair: word 1768.48 → zoom 1769.39 / graphic 1769.65."""
        words = dwl.parse_vtt_words(self.vtt)
        start = {w["word"]: w["start"] for w in words}["14-day"]
        lo, hi = BROLL["trigger_latency_s"]
        for insert_t in (1769.39, 1769.65):
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
        self.assertTrue(any(w["word"] == "filmmaker" for w in words))

    def test_explicit_transcript_accepts_vtt_path(self) -> None:
        words, meta = dwl.load_words(os.path.join(self.dir, "none.mp4"),
                                     self.dir, self.vtt)
        self.assertTrue(any(w["word"] == "14-day" for w in words))
        self.assertTrue(meta["transcriptPath"].endswith(".vtt"))

    def test_cue_level_vtt_fails_loudly(self) -> None:
        path = os.path.join(self.dir, "plain.vtt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nhello world\n")
        with self.assertRaises(ValueError):
            dwl.parse_vtt_words(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
