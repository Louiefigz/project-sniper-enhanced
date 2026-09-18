"""plan_refit tests — output-time windows must survive a cutTrack edit.

The invariant: after refit_plan(old, new), every window points at the SAME
SOURCE CONTENT it did before the cut edit (shifted/shrunk as needed), and
windows whose content was removed are dropped with a report row — never left
dangling past the new duration (the lint failure this module exists to prevent).
"""
import unittest

from _common import *  # noqa: F401,F403
from edit.plan_refit import refit_plan


def _plan(cut_track: list[dict], **tracks) -> dict:
    return {"cutTrack": cut_track, "target": {"mode": "longform"}, **tracks}


CUT_OLD = [{"sourceId": "raw", "start": 10.0, "end": 50.0}]          # 40s output


class EndTrimTests(unittest.TestCase):
    """Trim the tail: trailing windows clamp or drop, earlier ones are untouched."""

    def _refit(self, **tracks):
        old = _plan([dict(CUT_OLD[0])], **tracks)
        new = _plan([{"sourceId": "raw", "start": 10.0, "end": 45.0}], **tracks)
        return refit_plan(old, new)                                   # 35s output

    def test_early_window_is_untouched(self) -> None:
        plan, _ = self._refit(punchIns=[{"outStart": 5.0, "outEnd": 8.0, "zoom": 1.1}])
        self.assertEqual(plan["punchIns"][0]["outStart"], 5.0)
        # ends may shrink ≤1ms: the overlap-safe end remap (see _remap_end)
        self.assertAlmostEqual(plan["punchIns"][0]["outEnd"], 8.0, delta=0.002)

    def test_trailing_window_clamps_to_new_end(self) -> None:
        plan, report = self._refit(treatmentMap=[{"outStart": 32.0, "outEnd": 40.0}])
        self.assertEqual(plan["treatmentMap"][0]["outStart"], 32.0)
        self.assertAlmostEqual(plan["treatmentMap"][0]["outEnd"], 35.0, places=2)
        # Regression: a clamp-only refit MUST report (assemble persists on change)
        self.assertTrue(any(r.get("remapped") and r["track"] == "treatmentMap"
                            for r in report))

    def test_report_addresses_a_remapped_element_by_stable_id(self) -> None:
        plan, report = self._refit(graphicsTrack=[{
            "id": "g-stable", "outStart": 32.0, "outEnd": 40.0,
            "kind": "statement-card"}])
        self.assertEqual(plan["graphicsTrack"][0]["id"], "g-stable")
        changed = next(row for row in report if row.get("remapped"))
        self.assertEqual(changed["elementId"], "g-stable")

    def test_window_past_new_end_is_dropped_and_reported(self) -> None:
        plan, report = self._refit(punchIns=[{"outStart": 36.0, "outEnd": 39.0}])
        self.assertEqual(plan["punchIns"], [])
        self.assertTrue(any(r.get("dropped") and r["track"] == "punchIns"
                            for r in report))

    def test_trailing_transition_is_dropped(self) -> None:
        plan, _ = self._refit(transitions=[{"outTime": 20.0, "kind": "wash"},
                                           {"outTime": 38.0, "kind": "wash"}])
        self.assertEqual([t["outTime"] for t in plan["transitions"]], [20.0])


class MidCutTests(unittest.TestCase):
    """Cut a span out of the middle: later windows shift left by the span."""

    def _refit(self, **tracks):
        old = _plan([dict(CUT_OLD[0])], **tracks)
        new = _plan([{"sourceId": "raw", "start": 10.0, "end": 25.0},   # cut 25-30
                     {"sourceId": "raw", "start": 30.0, "end": 50.0}], **tracks)
        return refit_plan(old, new)                                    # 35s output

    def test_window_after_cut_shifts_left(self) -> None:
        plan, _ = self._refit(graphicsTrack=[{"outStart": 25.0, "outEnd": 30.0,
                                              "kind": "stat-card"}])
        g = plan["graphicsTrack"][0]
        self.assertAlmostEqual(g["outStart"], 20.0, places=2)   # was src 35 → out 20
        self.assertAlmostEqual(g["outEnd"], 25.0, places=2)

    def test_window_inside_cut_is_dropped(self) -> None:
        plan, report = self._refit(punchIns=[{"outStart": 15.5, "outEnd": 19.5}])
        self.assertEqual(plan["punchIns"], [])
        self.assertTrue(any(r.get("dropped") for r in report))

    def test_window_straddling_cut_shrinks_to_survivors(self) -> None:
        plan, _ = self._refit(treatmentMap=[{"outStart": 13.0, "outEnd": 22.0}])
        z = plan["treatmentMap"][0]
        self.assertAlmostEqual(z["outStart"], 13.0, places=2)
        self.assertAlmostEqual(z["outEnd"], 17.0, places=2)     # 22 → src 42 → out 17

    def test_chapter_at_cut_start_walks_to_next_kept_moment(self) -> None:
        plan, _ = self._refit(chapters=[{"outStart": 16.0, "title": "Part 2"}])
        self.assertAlmostEqual(plan["chapters"][0]["outStart"], 15.0, places=2)

    def test_audio_gain_window_remaps_like_the_rest(self) -> None:
        plan, _ = self._refit(audioGain=[{"outStart": 30.0, "outEnd": 34.0, "dB": -6}])
        w = plan["audioGain"][0]
        self.assertAlmostEqual(w["outStart"], 25.0, places=2)
        self.assertAlmostEqual(w["outEnd"], 29.0, places=2)
        self.assertEqual(w["dB"], -6)


class NoOpTests(unittest.TestCase):
    """An unchanged cutTrack must be a BYTE-IDENTICAL no-op.

    Direct-mapped ends restore the query epsilon (identity — repeated refits
    must not compound a −1ms drift per rebuild); only seam-walked ends skip
    the compensation, so straddling windows can never be pushed into overlap.
    """

    def test_identical_cut_track_changes_nothing(self) -> None:
        tracks = {"punchIns": [{"outStart": 5.0, "outEnd": 8.0, "zoom": 1.1}],
                  "transitions": [{"outTime": 20.0, "kind": "wash"}]}
        old = _plan([dict(CUT_OLD[0])], **tracks)
        new = _plan([dict(CUT_OLD[0])], **tracks)
        plan, report = refit_plan(old, new)
        self.assertEqual(plan["punchIns"][0]["outStart"], 5.0)
        self.assertEqual(plan["punchIns"][0]["outEnd"], 8.0)
        self.assertEqual(plan["punchIns"][0]["zoom"], 1.1)
        self.assertEqual(plan["transitions"], tracks["transitions"])
        self.assertFalse([r for r in report if r.get("dropped")])

    def test_repeated_refit_is_idempotent(self) -> None:
        # The compounding-drift regression: refit once (real cut), then refit
        # the RESULT against its own timebase — second pass must change nothing.
        tracks = {"punchIns": [{"outStart": 5.0, "outEnd": 8.0, "zoom": 1.1}],
                  "audioGain": [{"outStart": 12.0, "outEnd": 20.0, "dB": -3}]}
        old = _plan([dict(CUT_OLD[0])], **tracks)
        new = _plan([{"sourceId": "raw", "start": 10.0, "end": 45.0}], **tracks)
        once, _ = refit_plan(old, new)
        twice, _ = refit_plan(new, once)   # same timebase → identity
        self.assertEqual(once["punchIns"], twice["punchIns"])
        self.assertEqual(once["audioGain"], twice["audioGain"])


class RestoreGrowthTests(unittest.TestCase):
    """UN-CUT: the cutTrack GROWS (a previously-cut middle span is restored).

    Old timebase = [10-25]+[30-50] (span 25-30 cut, 35s out); new = [10-50]
    (40s out). Growth is the mirror of MidCutTests: every old-output moment
    still exists in the new map (restore only ADDS source), so _remap maps
    directly — windows BEFORE the restore are unchanged, windows AFTER shift
    RIGHT by exactly the restored span, and nothing is ever dropped.
    """

    def _refit(self, **tracks):
        old = _plan([{"sourceId": "raw", "start": 10.0, "end": 25.0},
                     {"sourceId": "raw", "start": 30.0, "end": 50.0}], **tracks)
        new = _plan([dict(CUT_OLD[0])], **tracks)     # restore 25-30 → 40s out
        return refit_plan(old, new)

    def test_window_before_restore_is_unchanged(self) -> None:
        plan, _ = self._refit(punchIns=[{"outStart": 5.0, "outEnd": 8.0,
                                         "zoom": 1.1}])
        self.assertEqual(plan["punchIns"][0]["outStart"], 5.0)
        # ends may shrink ≤1ms: the overlap-safe end remap (see _remap_end)
        self.assertAlmostEqual(plan["punchIns"][0]["outEnd"], 8.0, delta=0.002)

    def test_window_after_restore_shifts_right_by_the_span(self) -> None:
        plan, report = self._refit(graphicsTrack=[{"outStart": 20.0,
                                                   "outEnd": 25.0,
                                                   "kind": "stat-card"}])
        g = plan["graphicsTrack"][0]
        self.assertAlmostEqual(g["outStart"], 25.0, places=2)  # src 35 → out 25
        self.assertAlmostEqual(g["outEnd"], 30.0, places=2)    # +5.0 = the span
        self.assertTrue(any(r.get("remapped") for r in report))

    def test_point_after_restore_shifts_right(self) -> None:
        plan, _ = self._refit(transitions=[{"outTime": 20.0, "kind": "wash"}])
        self.assertAlmostEqual(plan["transitions"][0]["outTime"], 25.0, places=2)

    def test_growth_never_drops_anything(self) -> None:
        _, report = self._refit(
            punchIns=[{"outStart": 5.0, "outEnd": 8.0, "zoom": 1.1}],
            graphicsTrack=[{"outStart": 20.0, "outEnd": 25.0, "kind": "s"}],
            transitions=[{"outTime": 34.0, "kind": "wash"}],   # near old end
            chapters=[{"outStart": 16.0, "title": "Part 2"}])
        self.assertFalse([r for r in report if r.get("dropped")])

    def test_window_straddling_the_restore_grows_over_it(self) -> None:
        # Source-anchored contract: a window spanning the old seam keeps its
        # source endpoints, so it now also covers the restored content.
        plan, _ = self._refit(treatmentMap=[{"outStart": 13.0, "outEnd": 17.0}])
        z = plan["treatmentMap"][0]
        self.assertAlmostEqual(z["outStart"], 13.0, places=2)  # src 23
        self.assertAlmostEqual(z["outEnd"], 22.0, places=2)    # src 32 → out 22


class OutputTraversalFallbackTests(unittest.TestCase):
    """Removed endpoints walk OLD cutTrack order, not source chronology."""

    def test_reordered_cold_open_start_walks_into_main_story(self) -> None:
        # Old output is source 40-50 (cold open), then source 0-30 (story).
        # Trimming 45-50 must walk to source 0 — not the chronologically later
        # source 60 segment that happens to remain in the new plan.
        cuts = [{"sourceId": "raw", "start": 40.0, "end": 50.0},
                {"sourceId": "raw", "start": 0.0, "end": 30.0},
                {"sourceId": "raw", "start": 60.0, "end": 70.0}]
        new_cuts = [{"sourceId": "raw", "start": 40.0, "end": 45.0},
                    {"sourceId": "raw", "start": 0.0, "end": 30.0},
                    {"sourceId": "raw", "start": 60.0, "end": 70.0}]
        tracks = {"graphicsTrack": [{"outStart": 7.0, "outEnd": 15.0,
                                      "kind": "cold-open-label"}]}
        plan, _ = refit_plan(_plan(cuts, **tracks), _plan(new_cuts, **tracks))
        self.assertEqual(plan["graphicsTrack"][0]["outStart"], 5.0)
        self.assertEqual(plan["graphicsTrack"][0]["outEnd"], 10.0)

    def test_reordered_story_end_walks_back_into_cold_open(self) -> None:
        cuts = [{"sourceId": "raw", "start": 40.0, "end": 50.0},
                {"sourceId": "raw", "start": 0.0, "end": 30.0}]
        new_cuts = [{"sourceId": "raw", "start": 40.0, "end": 50.0},
                    {"sourceId": "raw", "start": 5.0, "end": 30.0}]
        tracks = {"treatmentMap": [{"outStart": 8.0, "outEnd": 12.0}]}
        plan, _ = refit_plan(_plan(cuts, **tracks), _plan(new_cuts, **tracks))
        self.assertEqual(plan["treatmentMap"][0]["outStart"], 8.0)
        self.assertEqual(plan["treatmentMap"][0]["outEnd"], 10.0)

    def test_removed_start_walks_across_source_boundary(self) -> None:
        cuts = [{"sourceId": "a", "start": 0.0, "end": 10.0},
                {"sourceId": "b", "start": 0.0, "end": 10.0}]
        new_cuts = [{"sourceId": "a", "start": 0.0, "end": 5.0},
                    {"sourceId": "b", "start": 0.0, "end": 10.0}]
        tracks = {"punchIns": [{"outStart": 7.0, "outEnd": 14.0,
                                  "zoom": 1.1}]}
        plan, _ = refit_plan(_plan(cuts, **tracks), _plan(new_cuts, **tracks))
        self.assertEqual(plan["punchIns"][0]["outStart"], 5.0)
        self.assertEqual(plan["punchIns"][0]["outEnd"], 9.0)

    def test_removed_end_walks_back_across_source_boundary(self) -> None:
        cuts = [{"sourceId": "a", "start": 0.0, "end": 10.0},
                {"sourceId": "b", "start": 0.0, "end": 10.0}]
        new_cuts = [{"sourceId": "a", "start": 0.0, "end": 10.0},
                    {"sourceId": "b", "start": 5.0, "end": 10.0}]
        tracks = {"audioGain": [{"outStart": 8.0, "outEnd": 12.0,
                                   "dB": -3.0}]}
        plan, _ = refit_plan(_plan(cuts, **tracks), _plan(new_cuts, **tracks))
        self.assertEqual(plan["audioGain"][0]["outStart"], 8.0)
        self.assertEqual(plan["audioGain"][0]["outEnd"], 10.0)


class StraddleOverlapTests(unittest.TestCase):
    """Two windows straddling ONE removed span must refit to touching windows.

    The +_EPS end-compensation regression: window1's end remapped via
    _prev_kept(8.0)+eps landed at 8.001 while window2's start via
    _next_kept(13.0) landed at 8.0 → overlapping windows → the lint overlap
    gate hard-rejected the refitted plan and --auto-base failed on a
    legitimate cut edit.
    """

    def test_windows_straddling_one_cut_do_not_overlap(self) -> None:
        from audio.audio_gain import overlap_error, parse_windows
        gains = [{"outStart": 5.0, "outEnd": 10.0, "dB": -6.0},
                 {"outStart": 12.0, "outEnd": 15.0, "dB": 3.0}]
        old = _plan([{"sourceId": "raw", "start": 0.0, "end": 30.0}],
                    audioGain=[dict(g) for g in gains])
        new = _plan([{"sourceId": "raw", "start": 0.0, "end": 8.0},
                     {"sourceId": "raw", "start": 13.0, "end": 30.0}],
                    audioGain=[dict(g) for g in gains])
        plan, _ = refit_plan(old, new)
        self.assertEqual(len(plan["audioGain"]), 2)          # both survive
        w1, w2 = plan["audioGain"]
        self.assertLessEqual(w1["outEnd"], w2["outStart"])   # touching, never over
        self.assertIsNone(overlap_error(parse_windows(plan["audioGain"])))


if __name__ == "__main__":
    unittest.main(verbosity=2)
