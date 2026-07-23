"""captions tests (split from selftest.py)."""
import unittest

from _common import *  # noqa: F401,F403


class MinimalCaptionTests(unittest.TestCase):
    """Minimal word-at-a-time style (R1/R2): event granularity, hold bounds,
    two-tone accent-style assignment, chest/face-relative band, lint wiring."""

    # 3 near-touching words (group, cap 3), a 4th (cap -> solo), an emphasis
    # word after a gap (solo accent), then a trailing word.
    WORDS = [
        {"word": "we", "start": 0.0, "end": 0.2},
        {"word": "cut", "start": 0.2, "end": 0.4},
        {"word": "the", "start": 0.4, "end": 0.6},
        {"word": "filler", "start": 0.6, "end": 0.9},
        {"word": "zero", "start": 1.5, "end": 1.8},
        {"word": "sales.", "start": 1.8, "end": 2.1},
    ]
    M = cap.CAPTIONS["MINIMAL"]

    def _events(self, emphasis=frozenset()):
        return cm._minimal_events(cap._merge_punctuation(self.WORDS),
                                  self.M, set(emphasis))

    def test_event_granularity_and_phrase_cap(self) -> None:
        events = self._events()
        # No event exceeds the 3-word phrase cap; a >120ms gap breaks a phrase.
        self.assertTrue(all(len(ws) <= self.M["phrase_max_words"]
                            for ws, _ in events))
        self.assertEqual([w["word"] for w in events[0][0]], ["we", "cut", "the"])
        self.assertEqual([w["word"] for w in events[1][0]], ["filler"])

    def test_emphasis_word_is_solo_accent(self) -> None:
        events = self._events({"zero"})
        accents = [ws for ws, is_acc in events if is_acc]
        self.assertEqual(len(accents), 1)
        self.assertEqual([w["word"] for w in accents[0]], ["zero"])
        # Its neighbours never absorb it into a phrase.
        self.assertTrue(all(len(ws) == 1 or "zero" not in [w["word"] for w in ws]
                            for ws, _ in events))

    def test_hold_bounds(self) -> None:
        # Normal events hold >= min_hold; a rapid word is bounded by next onset.
        events = self._events({"zero"})
        windows = cm._minimal_windows(events, self.M)
        starts = [w[0][0]["start"] for w in events]
        for i, (s, e) in enumerate(windows):
            self.assertGreater(e, s)
            nxt = starts[i + 1] if i + 1 < len(windows) else e
            floor = min(self.M["min_hold_s"], nxt - s) if i + 1 < len(windows) \
                else self.M["min_hold_s"]
            self.assertGreaterEqual(e - s, floor - 1e-6)

    def test_hang_capped_at_phrase_end(self) -> None:
        # 'filler' ends at 0.9, next word at 1.5 (0.6s gap): it must clear
        # hang_s (0.4s) after it stops, not linger to the next onset.
        windows = cm._minimal_windows(self._events({"zero"}), self.M)
        self.assertAlmostEqual(windows[1][1], 0.9 + self.M["hang_s"], places=3)

    def test_accent_style_assignment_in_ass(self) -> None:
        ass = cap.build_ass(self.WORDS, "minimal",
                            {**cap.CAPTIONS, "emphasisWords": ["Zero"]})  # case-insensitive
        accent_events = [ln for ln in ass.splitlines()
                         if ln.startswith("Dialogue:") and "MinimalAccent" in ln]
        self.assertEqual(len(accent_events), 1)
        self.assertIn("zero", accent_events[0])
        self.assertIn("Style: Minimal,Inter,", ass)
        self.assertIn("Style: MinimalAccent,Georgia,", ass)
        # Every event is chest-anchored via an explicit \pos.
        dialogues = [ln for ln in ass.splitlines() if ln.startswith("Dialogue:")]
        self.assertTrue(all("\\pos(" in ln for ln in dialogues))

    def test_band_center_chest_default(self) -> None:
        self.assertEqual(cm._minimal_band_center(cap.CAPTIONS), 1100)

    def test_band_center_carries_c12_shift(self) -> None:
        cfg = dict(cap.CAPTIONS)
        cfg["baseline_max_y"] = cap.CAPTIONS["baseline_max_y"] - 200  # C12 up-shift
        self.assertEqual(cm._minimal_band_center(cfg), 900)

    def test_band_center_face_relative_and_clamped(self) -> None:
        cfg = dict(cap.CAPTIONS)
        cfg["faceBBoxNorm"] = [0.3, 0.2, 0.4, 0.4]     # bbox bottom = 0.6
        self.assertEqual(cm._minimal_band_center(cfg),
                         round((0.6 + self.M["face_gap_frac"]) * 1920))
        cfg["faceBBoxNorm"] = [0.1, 0.7, 0.3, 0.3]     # bottom = 1.0 -> clamp
        clamped = cm._minimal_band_center(cfg)
        self.assertLessEqual(clamped, 1920 - 520 - self.M["font_size"] // 2)

    def test_lint_accepts_minimal_style(self) -> None:
        plan = good_plan()
        plan["captions"]["style"] = "minimal"
        self.assertEqual(pl.lint(plan, MANIFEST).errors, [])

    def test_build_ass_rejects_unknown_style(self) -> None:
        self.assertRaises(ValueError, cap.build_ass, self.WORDS, "bogus")


class AspectGeometryTests(unittest.TestCase):
    """Captions must be positioned for the ACTUAL delivery frame — a 16:9 longform
    lands lower-CENTER third, NOT the 9:16 mid-chest the portrait CANVAS forced."""

    WORDS = [{"word": "this", "start": 0.0, "end": 0.4},
             {"word": "is", "start": 0.4, "end": 0.6},
             {"word": "a", "start": 0.6, "end": 0.7},
             {"word": "test", "start": 0.7, "end": 1.1}]

    def _style_and_playres(self, aspect):
        cfg = cap.caption_cfg_for_aspect(aspect)
        ass = cap.build_ass(self.WORDS, "line", cfg)
        style = [l for l in ass.splitlines() if l.startswith("Style: Caption")][0]
        playres = [l for l in ass.splitlines() if l.startswith("PlayResY")][0]
        return cfg, style.split(","), playres

    def test_16x9_lands_lower_center_on_a_1080_tall_frame(self) -> None:
        cfg, f, playres = self._style_and_playres("16:9")
        self.assertEqual(playres, "PlayResY: 1080")
        mv, mr, ml, size = int(f[-2]), int(f[-3]), int(f[-4]), int(f[2])
        self.assertEqual(cfg["canvas"]["height"] - mv, 980)   # baseline = lower third
        self.assertEqual(ml, mr)                              # centered
        self.assertGreater(size, cap.CAPTIONS["font_size"])   # bigger/bolder than 9:16

    def test_9x16_is_unchanged(self) -> None:
        cfg, f, playres = self._style_and_playres("9:16")
        self.assertEqual(playres, "PlayResY: 1920")
        self.assertEqual(cfg["canvas"]["height"] - int(f[-2]),
                         cap.CAPTIONS["baseline_max_y"])       # 1340, as before

    def test_unknown_aspect_falls_back_to_portrait(self) -> None:
        self.assertEqual(cap.caption_cfg_for_aspect("21:9")["canvas"]["height"], 1920)

if __name__ == "__main__":
    unittest.main(verbosity=2)


class HookCardCaptionSuppressionTests(unittest.TestCase):
    """LESSON-022: caption cues overlapping a titleCard window are dropped so
    the hook zone shows the designed lockup instead of captions."""

    WORDS = [
        {"word": "your", "start": 0.1, "end": 0.4},
        {"word": "sign", "start": 0.4, "end": 0.8},
        {"word": "to", "start": 0.8, "end": 1.0},
        {"word": "stop", "start": 1.0, "end": 1.6},
        {"word": "body", "start": 2.6, "end": 3.0},
        {"word": "starts", "start": 3.0, "end": 3.4},
    ]

    def test_cues_under_card_dropped_body_cues_survive(self) -> None:
        import tempfile
        from graphics.graphics_stage import suppress_captions
        ass = cap.build_ass(self.WORDS, "minimal",
                            cap.caption_cfg_for_aspect("9:16"))
        with tempfile.NamedTemporaryFile("w", suffix=".ass",
                                         delete=False) as f:
            f.write(ass)
            path = f.name
        dropped = suppress_captions(path, path, [(0.0, 2.2)])
        self.assertGreater(dropped, 0)
        with open(path, encoding="utf-8") as f:
            out = f.read()
        # Hook-window cues are gone; the first body cue survives verbatim.
        self.assertNotIn("sign", out)
        self.assertIn("body", out)
