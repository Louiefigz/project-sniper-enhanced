"""Onset-clipped word survival across word-safe micro-cuts (the real-word bug)."""
import unittest

from _common import *  # noqa: F401,F403
from compile_timeline import compile_plan, remap_words


class OnsetClippedWordTests(unittest.TestCase):
    PLAN = {"cutTrack": [
        {"sourceId": "s", "start": 10.0, "end": 20.0, "speed": 1.0},
        {"sourceId": "s", "start": 25.15, "end": 30.0, "speed": 1.0},
    ]}

    def test_word_clipped_5ms_at_seam_survives_clamped(self) -> None:
        tmap = compile_plan(self.PLAN)
        words = [{"word": "real", "start": 25.145, "end": 25.47}]
        kept = remap_words(words, "s", tmap)
        self.assertEqual(len(kept), 1)
        self.assertAlmostEqual(kept[0]["start"], 10.0, places=3)

    def test_word_mostly_cut_still_dropped(self) -> None:
        tmap = compile_plan(self.PLAN)
        words = [{"word": "like", "start": 24.5, "end": 25.2}]
        kept = remap_words(words, "s", tmap)
        self.assertEqual(kept, [])

    def test_fully_kept_words_unchanged(self) -> None:
        tmap = compile_plan(self.PLAN)
        words = [{"word": "data", "start": 25.5, "end": 25.8}]
        kept = remap_words(words, "s", tmap)
        self.assertEqual(len(kept), 1)
