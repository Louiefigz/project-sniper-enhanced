"""Word-locked seams (NATEHERK_STUDY T-G / §5 item 5).

``planner/word_lock.py``: snap transitions outTimes + graphic outStarts onto
kept-word boundaries; ``plan_lint_motion.check_word_lock`` WARNs on seams
>150ms off-boundary. Deterministic, driven by kept OUTPUT-time words.
"""
import unittest

from _common import *  # noqa: F401,F403
from planner import word_lock as wl
from producer_config import MOTION


def _w(start: float, end: float) -> dict:
    return {"word": "x", "start": float(start), "end": float(end)}


# Kept words in output time: boundaries at 1.0/1.4, 2.0/2.4, 8.0/8.5
WORDS = [_w(1.0, 1.4), _w(2.0, 2.4), _w(8.0, 8.5)]
TOL = MOTION["word_lock"]["warn_off_boundary_s"]


class SnapTests(unittest.TestCase):
    def test_boundaries_are_sorted_deduped_starts_and_ends(self) -> None:
        words = [_w(2.0, 2.4), _w(1.0, 1.4), _w(1.0, 1.4)]
        self.assertEqual(wl.word_boundaries(words), [1.0, 1.4, 2.0, 2.4])

    def test_snap_moves_to_nearest_boundary_within_budget(self) -> None:
        self.assertEqual(wl.snap_to_word_boundary(2.1, WORDS, 0.3), 2.0)
        self.assertEqual(wl.snap_to_word_boundary(1.5, WORDS, 0.3), 1.4)

    def test_snap_beyond_budget_returns_t_unchanged(self) -> None:
        self.assertEqual(wl.snap_to_word_boundary(5.0, WORDS, 0.3), 5.0)

    def test_snap_tie_takes_earlier_boundary(self) -> None:
        self.assertEqual(wl.snap_to_word_boundary(1.7, WORDS, 0.5), 1.4)

    def test_no_words_returns_t(self) -> None:
        self.assertEqual(wl.snap_to_word_boundary(2.1, [], 0.3), 2.1)


class SnapPlanSeamsTests(unittest.TestCase):
    def _plan(self) -> dict:
        return {"transitions": [{"outTime": 2.1, "kind": "white-flash"},
                                {"outTime": 5.0, "kind": "white-flash"}],
                "graphicsTrack": [{"outStart": 8.1, "outEnd": 11.1,
                                   "kind": "stat-card"}]}

    def test_seams_snap_and_windows_translate(self) -> None:
        out, moves = wl.snap_plan_seams(self._plan(), WORDS, 0.3)
        self.assertEqual(out["transitions"][0]["outTime"], 2.0)
        self.assertEqual(out["transitions"][1]["outTime"], 5.0)   # off-budget
        g = out["graphicsTrack"][0]
        self.assertEqual((g["outStart"], g["outEnd"]), (8.0, 11.0))  # hold kept
        self.assertEqual([(m["track"], m["index"]) for m in moves],
                         [("transitions", 0), ("graphicsTrack", 0)])

    def test_input_plan_is_never_mutated(self) -> None:
        plan = self._plan()
        wl.snap_plan_seams(plan, WORDS, 0.3)
        self.assertEqual(plan["transitions"][0]["outTime"], 2.1)
        self.assertEqual(plan["graphicsTrack"][0]["outStart"], 8.1)

    def test_on_boundary_seam_reports_no_move(self) -> None:
        plan = {"transitions": [{"outTime": 2.0, "kind": "white-flash"}]}
        _, moves = wl.snap_plan_seams(plan, WORDS, 0.3)
        self.assertEqual(moves, [])


class WordLockLintTests(unittest.TestCase):
    def _warns(self, plan, words) -> list[str]:
        rep = pl.Report()
        plm.check_word_lock(plan, words, rep)
        return rep.warnings

    def test_off_boundary_seams_warn(self) -> None:
        # 2.2 sits 0.2s from both 2.0 and 2.4; 8.75 sits 0.25s past 8.5
        plan = {"transitions": [{"outTime": 2.2}],
                "graphicsTrack": [{"outStart": 8.75, "outEnd": 10.0}]}
        warns = self._warns(plan, WORDS)
        self.assertEqual(len(warns), 2, warns)
        self.assertTrue(all("word boundary" in w for w in warns), warns)

    def test_on_boundary_and_within_tolerance_stay_silent(self) -> None:
        plan = {"transitions": [{"outTime": 2.0}, {"outTime": 2.0 + TOL - 0.05}],
                "graphicsTrack": [{"outStart": 8.0, "outEnd": 10.0}]}
        self.assertEqual(self._warns(plan, WORDS), [])

    def test_no_words_no_warns(self) -> None:
        plan = {"transitions": [{"outTime": 2.1}]}
        self.assertEqual(self._warns(plan, []), [])

    def test_plan_lint_runs_word_lock_only_when_words_given(self) -> None:
        plan = good_plan()
        plan["transitions"] = [{"outTime": 9.37, "kind": "white-flash"}]
        base = pl.lint(plan, MANIFEST)                    # no words: unchanged
        self.assertFalse([w for w in base.warnings if "word boundary" in w])
        with_words = pl.lint(plan, MANIFEST, WORDS)
        self.assertTrue([w for w in with_words.warnings if "word boundary" in w],
                        with_words.warnings)


if __name__ == "__main__":
    unittest.main(verbosity=2)
