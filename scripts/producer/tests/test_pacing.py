"""pacing tests — upstream visual-rhythm coordinator (planner.pacing + lint)."""
import unittest

from _common import *  # noqa: F401,F403


class VisualChangeTimesTests(unittest.TestCase):
    """visual_change_times: the union of every track's change instants."""

    def test_union_across_all_tracks(self) -> None:
        # One instant from each track type; two 10s segments give one internal
        # cut boundary at 10.0. Sorted, none within the dedup window.
        plan = {
            "cutTrack": [
                {"sourceId": "raw-1", "start": 0.0, "end": 10.0, "speed": 1.0},
                {"sourceId": "raw-1", "start": 10.0, "end": 20.0, "speed": 1.0},
            ],
            "graphicsTrack": [{"outStart": 3.0}],
            "brollTrack": [{"outStart": 5.0}],
            "titleCards": [{"outStart": 7.0}],
            "transitions": [{"outTime": 12.0}],
            "punchIns": [{"outStart": 15.0, "role": "emphasis"}],
        }
        self.assertEqual(pac.visual_change_times(plan),
                         [3.0, 5.0, 7.0, 10.0, 12.0, 15.0])

    def test_aliveness_punch_excluded_others_included(self) -> None:
        # The continuous aliveness creep is not a discrete change; a semantic
        # punch is. Single segment -> no cut boundary, so only the punch remains.
        plan = {
            "cutTrack": [{"sourceId": "raw-1", "start": 0.0, "end": 20.0, "speed": 1.0}],
            "punchIns": [{"outStart": 4.0, "role": "aliveness"},
                         {"outStart": 8.0, "role": "emphasis"}],
        }
        times = pac.visual_change_times(plan)
        self.assertIn(8.0, times)
        self.assertNotIn(4.0, times)

    def test_dedup_within_window(self) -> None:
        # A cut boundary at 10.0 and a graphic at 10.1 (< 0.15s apart) are one
        # change, not two.
        plan = {
            "cutTrack": [
                {"sourceId": "raw-1", "start": 0.0, "end": 10.0, "speed": 1.0},
                {"sourceId": "raw-1", "start": 10.0, "end": 20.0, "speed": 1.0},
            ],
            "graphicsTrack": [{"outStart": 10.1}],
        }
        self.assertEqual(pac.visual_change_times(plan), [10.0])

    def test_cut_track_internal_boundaries(self) -> None:
        # Three segments -> two internal boundaries at cumulative OUTPUT offsets
        # (the 2x segment contributes 5s of output, not 10s); the final total is
        # the video end, not a change.
        plan = {"cutTrack": [
            {"sourceId": "raw-1", "start": 0.0, "end": 10.0, "speed": 1.0},   # +10 -> 10
            {"sourceId": "raw-1", "start": 0.0, "end": 10.0, "speed": 2.0},   # +5  -> 15
            {"sourceId": "raw-1", "start": 0.0, "end": 10.0, "speed": 1.0},   # +10 -> 25
        ]}
        self.assertEqual(pac.visual_change_times(plan), [10.0, 15.0])


class PacingReportTests(unittest.TestCase):
    """pacing_report: gaps, longest still stretch, and the change rate."""

    def test_long_gap_appears_in_gaps(self) -> None:
        # Changes at 5s and 35s over a 40s output leave a 30s still stretch,
        # past the longform 20s ceiling.
        plan = {
            "cutTrack": [{"sourceId": "raw-1", "start": 0.0, "end": 40.0, "speed": 1.0}],
            "graphicsTrack": [{"outStart": 5.0}, {"outStart": 35.0}],
        }
        report = pac.pacing_report(plan, 40.0, "longform")
        self.assertIn((5.0, 35.0), report["gaps"])
        self.assertAlmostEqual(report["longest_gap_s"], 30.0)

    def test_well_paced_plan_has_no_gaps(self) -> None:
        # Region-aware well-paced: a ~3s cadence through the 30s hook (≤4s ceiling),
        # then ~8s through the body (≤20s ceiling). No stretch exceeds its region's
        # ceiling — the front-loaded envelope, not a flat rate.
        hook = list(range(3, 31, 3))            # every 3s to 30s
        body = list(range(38, 120, 8))          # every 8s after the hook
        plan = {
            "cutTrack": [{"sourceId": "raw-1", "start": 0.0, "end": 120.0, "speed": 1.0}],
            "graphicsTrack": [{"outStart": float(t)} for t in hook + body],
        }
        report = pac.pacing_report(plan, 120.0, "longform")
        self.assertEqual(report["gaps"], [])

    def test_hook_gap_tighter_than_body(self) -> None:
        # docs/studies/PRODUCTION_ENVELOPE_STUDY.md — the still-gap ceiling is REGION-aware:
        # a 9s hole INSIDE the 30s hook exceeds the tight hook ceiling (4s) and is
        # flagged, while the SAME 12s cadence in the body sits under the 20s body
        # ceiling and is fine. Enforces the front-loaded envelope, not a flat rate.
        hook = [3, 6, 9, 12, 21, 24, 27]        # hole 12->21 (9s) inside the hook
        body = list(range(45, 300, 12))         # 12s cadence, under the 20s body ceiling
        plan = {
            "cutTrack": [{"sourceId": "raw-1", "start": 0.0, "end": 300.0, "speed": 1.0}],
            "graphicsTrack": [{"outStart": float(t)} for t in hook + body],
        }
        report = pac.pacing_report(plan, 300.0, "longform")
        self.assertEqual(report["gaps"], [(12.0, 21.0)])


class CheckPacingTests(unittest.TestCase):
    """check_pacing: WARN gate, gated OFF for clean-cut, silent when well-paced."""

    def _underpaced_longform(self) -> dict:
        # Produced longform with a single 40s segment and no other tracks: no
        # changes at all -> under-paced + a >20s still gap + a flat hook.
        return {
            "planVersion": 1,
            "target": {"mode": "longform", "treatment": "produced", "platforms": []},
            "cutTrack": [{"sourceId": "raw-1", "start": 0.0, "end": 40.0, "speed": 1.0}],
        }

    def _well_paced_longform(self) -> dict:
        # Front-loaded (7 changes in the first 30s hook) then a steady body
        # cadence. Real graphics carry HOLDS (outEnd) — the intro-envelope share
        # floor counts covered seconds, not bare change instants.
        hook = [4, 8, 12, 16, 20, 24, 28]
        body = list(range(40, 300, 10))
        return {
            "planVersion": 1,
            "target": {"mode": "longform", "treatment": "produced", "platforms": []},
            "cutTrack": [{"sourceId": "raw-1", "start": 0.0, "end": 300.0, "speed": 1.0}],
            "graphicsTrack": [{"outStart": float(t), "outEnd": float(t) + 6.0}
                              for t in hook + body],
        }

    def test_underpaced_produced_longform_warns(self) -> None:
        rep = pl.Report()
        plm.check_pacing(self._underpaced_longform(), 40.0, "longform", rep)
        self.assertTrue(any("under-paced" in w for w in rep.warnings), rep.warnings)
        self.assertTrue(any("still-gap" in w for w in rep.warnings), rep.warnings)
        self.assertTrue(any("front-load" in w for w in rep.warnings), rep.warnings)

    def test_clean_cut_plan_not_checked(self) -> None:
        # clean-cut disables the engagement stack, so pacing is cuts-only and
        # this check must stay silent even on an otherwise-flatlining plan.
        plan = self._underpaced_longform()
        plan["target"]["treatment"] = "clean-cut"
        rep = pl.Report()
        plm.check_pacing(plan, 40.0, "longform", rep)
        self.assertEqual(rep.warnings, [])

    def test_legacy_treatment_cannot_downgrade_explicit_produced_scope(self) -> None:
        plan = self._underpaced_longform()
        plan["target"].update(scope="produced", treatment="clean-cut")
        rep = pl.Report()
        plm.check_pacing(plan, 40.0, "longform", rep)
        self.assertTrue(rep.warnings, "explicit produced scope must retain pacing checks")
        self.assertTrue(any("produced intro has no perceived visual change" in error
                            for error in rep.errors), rep.errors)

    def _sparse_short(self) -> dict:
        # A talking-head short: 3 sustained graphics over 35s (~5/min), an ~11s
        # bare stretch — under the FAST short floor (12/min, 8s) but on-style for
        # a continuous single-speaker take.
        return {
            "planVersion": 1,
            "target": {"mode": "short", "treatment": "produced", "platforms": []},
            "cutTrack": [{"sourceId": "raw-1", "start": 0.0, "end": 35.0, "speed": 1.0}],
            "graphicsTrack": [{"outStart": 1.0}, {"outStart": 9.0}, {"outStart": 21.0}],
        }

    def test_talking_head_pace_relaxes_the_short_floor(self) -> None:
        # Default (fast) pace WARNs; target.pace="talking-head" clears it — the
        # gaps are judged against the SAME (16s) ceiling the warning would quote.
        fast = self._sparse_short()
        rep = pl.Report()
        plm.check_pacing(fast, 35.0, "short", rep)
        self.assertTrue(rep.warnings)                       # fast floor fires

        th = self._sparse_short()
        th["target"]["pace"] = "talking-head"
        rep2 = pl.Report()
        plm.check_pacing(th, 35.0, "short", rep2)
        self.assertEqual(rep2.warnings, [])                 # on-style → silent

    def _graphics_carried_short(self) -> dict:
        # An angela-grammar short (docs/studies/ANGELA_STYLE.md): dense graphics
        # (~29 changes/min, max gap 3s) on a single uncut take, but the hook
        # is only ~1.42x denser than the body — the hook lives in the
        # graphics layer, not in cut density (§2 AH3).
        hook = [0.5, 2.0]
        body = [float(t) for t in range(4, 33, 2)]
        return {
            "planVersion": 1,
            "target": {"mode": "short", "treatment": "produced", "platforms": []},
            "cutTrack": [{"sourceId": "raw-1", "start": 0.0, "end": 35.0, "speed": 1.0}],
            "graphicsTrack": [{"outStart": t} for t in hook + body],
        }

    def test_angela_pace_relaxes_the_front_load_only(self) -> None:
        # Default (fast) pace fires ONLY the front-load warning (1.42x < 1.5);
        # target.pace="angela" clears it (floor 1.3) while KEEPING the rate
        # (16/min) and still-gap (8s) floors — the profile relaxes the hook
        # axis, not the density axes.
        fast = self._graphics_carried_short()
        rep = pl.Report()
        plm.check_pacing(fast, 35.0, "short", rep)
        self.assertTrue(any("front-load" in w for w in rep.warnings), rep.warnings)

        ang = self._graphics_carried_short()
        ang["target"]["pace"] = "angela"
        rep2 = pl.Report()
        plm.check_pacing(ang, 35.0, "short", rep2)
        self.assertEqual(rep2.warnings, [])                 # on-style → silent

    def test_well_paced_plan_no_warnings(self) -> None:
        rep = pl.Report()
        plm.check_pacing(self._well_paced_longform(), 300.0, "longform", rep)
        self.assertEqual(rep.warnings, [])

    def test_hook_still_gap_warns_by_region(self) -> None:
        # A 9s hole in the hook (dense body, healthy rate + front-load otherwise)
        # is the ONLY warning, and the message names the hook region + its ceiling.
        hook = [3, 6, 9, 12, 21, 24, 27]        # hole 12->21 (9s) inside the hook
        body = list(range(45, 300, 12))
        plan = {
            "planVersion": 1,
            "target": {"mode": "longform", "treatment": "produced", "platforms": []},
            "cutTrack": [{"sourceId": "raw-1", "start": 0.0, "end": 300.0, "speed": 1.0}],
            "graphicsTrack": [{"outStart": float(t)} for t in hook + body],
        }
        rep = pl.Report()
        plm.check_pacing(plan, 300.0, "longform", rep)
        self.assertTrue(any("hook still-gap" in w for w in rep.warnings), rep.warnings)

    def test_wired_into_full_lint(self) -> None:
        # check_pacing must be reachable from plan_lint.lint's motion pass.
        rep = pl.lint(self._underpaced_longform(), MANIFEST)
        self.assertTrue(any("pacing:" in w for w in rep.warnings), rep.warnings)


class SuggestFillsTests(unittest.TestCase):
    """suggest_fills: proposes discrete changes that break each still-gap."""

    def _one_gap_plan(self, gap_end: float) -> dict:
        # A change at 5s then nothing until gap_end over a matching output.
        return {
            "cutTrack": [{"sourceId": "raw-1", "start": 0.0,
                          "end": gap_end, "speed": 1.0}],
            "graphicsTrack": [{"outStart": 5.0}],
        }

    def test_fill_lands_inside_the_gap(self) -> None:
        # Changes at 0 (cut) + 5 (graphic); every fill sits strictly inside
        # the output. LONGFORM fills propose a GRAPHIC / panel extension —
        # never a punch (LL-007: zooms are not gap-fillers).
        plan = self._one_gap_plan(40.0)
        fills = pac.suggest_fills(plan, 40.0, "longform")
        self.assertTrue(fills)
        for f in fills:
            self.assertTrue(0.0 < f["outStart"] < 40.0)
            self.assertLessEqual(f["outEnd"], 40.0)
            self.assertEqual(f["kind"], "graphic")
            self.assertIn("LL-007", f["reason"])
            self.assertTrue(f["needsOperator"])

    def test_short_fills_keep_the_punch_grammar(self) -> None:
        # Shorts grammar is unchanged: zoom IS the cut (R13), so a short's
        # still-gap fill stays the universal asset-free punch.
        plan = {"cutTrack": [{"sourceId": "raw-1", "start": 0.0,
                              "end": 30.0, "speed": 1.0}]}
        fills = pac.suggest_fills(plan, 30.0, "short")
        self.assertTrue(fills)
        for f in fills:
            self.assertEqual(f["kind"], "punch")
            self.assertNotIn("LL-007", f["reason"])

    def test_fills_break_gap_below_ceiling(self) -> None:
        # Region-aware: every run between consecutive changes must stay under the
        # ceiling AT that point — ~4s in the hook (<30s), ~20s in the body.
        plan = self._one_gap_plan(70.0)
        fills = pac.suggest_fills(plan, 70.0, "longform")
        bounds = sorted([0.0, 5.0] + [f["at"] for f in fills] + [70.0])
        for a, b in zip(bounds, bounds[1:]):
            ceiling = 4.0 if (a + b) / 2 < 30.0 else 20.0
            self.assertLessEqual(b - a, ceiling + 1e-6, (a, b))

    def test_well_paced_plan_suggests_nothing(self) -> None:
        # Region-aware: the hook (first 30s) must be ~4s-dense, the body ~20s.
        # A change every 4s satisfies both ceilings everywhere -> no fills owed.
        plan = {
            "cutTrack": [{"sourceId": "raw-1", "start": 0.0, "end": 60.0, "speed": 1.0}],
            "graphicsTrack": [{"outStart": float(t)} for t in range(4, 60, 4)],
        }
        self.assertEqual(pac.suggest_fills(plan, 60.0, "longform"), [])

    def test_hook_is_densified_finer_than_body(self) -> None:
        # One flat 0->70s cut: the hook (first 30s) must be broken to the ~4s
        # hook ceiling, far finer than the body's ~20s — the front-load fix.
        plan = {"cutTrack": [{"sourceId": "raw-1", "start": 0.0,
                              "end": 70.0, "speed": 1.0}]}
        fills = pac.suggest_fills(plan, 70.0, "longform")
        hook = [f for f in fills if f["at"] < 30.0]
        body = [f for f in fills if f["at"] >= 30.0]
        # >= 6 fills in the 30s hook (4s ceiling) vs at most a couple in the body.
        self.assertGreaterEqual(len(hook), 6, [f["at"] for f in fills])
        hook_rate = len(hook) / 30.0
        body_rate = len(body) / 40.0
        self.assertGreater(hook_rate, body_rate)

    def test_cli_report_shape(self) -> None:
        # _cli_report is JSON-serialisable and carries the fills + gaps + rate.
        import json
        plan = {
            "target": {"mode": "longform"},
            "cutTrack": [{"sourceId": "raw-1", "start": 0.0, "end": 40.0, "speed": 1.0}],
            "graphicsTrack": [{"outStart": 5.0}],
        }
        rep = pac._cli_report(plan)
        json.dumps(rep)  # must not raise (no inf / tuples leaking through)
        self.assertEqual(rep["mode"], "longform")
        self.assertTrue(rep["suggestedFills"])
        self.assertTrue(rep["gaps"])


if __name__ == "__main__":
    unittest.main(verbosity=2)


class NonheadShareTests(unittest.TestCase):
    """nonhead_share: merged graphics+broll coverage over a window."""

    def test_overlapping_windows_merge(self) -> None:
        plan = {"graphicsTrack": [{"outStart": 0.0, "outEnd": 10.0}],
                "brollTrack": [{"outStart": 5.0, "outEnd": 15.0}]}
        self.assertAlmostEqual(pac.nonhead_share(plan, 60.0), 0.25)

    def test_empty_plan_is_zero(self) -> None:
        self.assertEqual(pac.nonhead_share({}, 60.0), 0.0)

    def test_window_clamps_entries(self) -> None:
        plan = {"graphicsTrack": [{"outStart": 55.0, "outEnd": 90.0}]}
        self.assertAlmostEqual(pac.nonhead_share(plan, 60.0), 5.0 / 60.0)


class StagedLandTimesTests(unittest.TestCase):
    """spec.atN lands count as discrete changes (PRO_INTRO_ENVELOPE builds)."""

    def test_at_lands_break_the_gap(self) -> None:
        plan = {
            "cutTrack": [{"sourceId": "raw-1", "start": 0.0, "end": 12.0, "speed": 1.0}],
            "graphicsTrack": [{"outStart": 1.0, "outEnd": 10.0,
                               "spec": {"at1": 2.0, "at2": 5.0, "title": "x"}}],
        }
        times = pac.visual_change_times(plan)
        self.assertIn(3.0, times)   # 1.0 + at1
        self.assertIn(6.0, times)   # 1.0 + at2

    def test_lands_past_out_end_ignored(self) -> None:
        plan = {"graphicsTrack": [{"outStart": 1.0, "outEnd": 4.0,
                                   "spec": {"at1": 5.0}}]}
        self.assertEqual(pac.visual_change_times(plan), [1.0])

    def test_module_lands_count_as_changes(self) -> None:
        # NATEHERK §5.4: narration-paced module builds are real on-screen
        # changes — the rhythm model must not read a building takeover as
        # dead air (list form, the plan_lint_motion-validated shape).
        plan = {"graphicsTrack": [{"outStart": 10.0, "outEnd": 21.0,
                                   "spec": {"moduleLands": [1.2, 4.5, 7.6]}}]}
        times = pac.visual_change_times(plan)
        for t in (10.0, 11.2, 14.5, 17.6):
            self.assertIn(t, times)

    def test_statement_lands_count_number_and_string(self) -> None:
        # statement-card v2 swap times: a bare number and the comp-contract
        # "a,b" string both count; a land past outEnd is ignored.
        plan = {"graphicsTrack": [
            {"outStart": 5.0, "outEnd": 11.0, "spec": {"statementLands": 3.1}},
            {"outStart": 20.0, "outEnd": 30.0,
             "spec": {"statementLands": "2.0,8.0,99"}},
        ]}
        times = pac.visual_change_times(plan)
        for t in (5.0, 8.1, 20.0, 22.0, 28.0):
            self.assertIn(t, times)
        self.assertNotIn(119.0, times)

    def test_malformed_lands_count_nothing(self) -> None:
        # Malformed lands are the lint's job — the rhythm model stays quiet.
        plan = {"graphicsTrack": [{"outStart": 1.0, "outEnd": 9.0,
                                   "spec": {"moduleLands": "a|b",
                                            "statementLands": True}}]}
        self.assertEqual(pac.visual_change_times(plan), [1.0])


class PanelHoldTests(unittest.TestCase):
    """Recomposed panel holds are judged by the BODY still-gap ceiling
    (defect report 2026-07-10: the reference holds rails 6.2-18.4s with zero
    discrete changes inside — 8/8 windows — and plan_lint_smooth forbids
    punching under a live panel, so a hook-ceiling fill would be illegal)."""

    def _rail_plan(self, gs=1.2, ge=8.1):
        return {
            "planVersion": 1,
            "target": {"mode": "longform", "treatment": "produced", "platforms": []},
            "cutTrack": [{"sourceId": "raw-1", "start": 0.0, "end": 300.0, "speed": 1.0}],
            "graphicsTrack": (
                [{"outStart": gs, "outEnd": ge, "kind": "glass-rail",
                  "anchor": "free-band"}]
                + [{"outStart": float(t)} for t in
                   [ge, 12, 16, 20, 24, 28] + list(range(45, 300, 12))]),
            "punchIns": [{"outStart": gs - 0.12, "outEnd": ge, "zoom": 1.32,
                          "attackS": 0.4, "releaseS": 0.4,
                          "role": "recompose", "syncGraphic": gs}],
        }

    def test_recomposed_rail_hold_uses_body_ceiling(self) -> None:
        report = pac.pacing_report(self._rail_plan(), 300.0, "longform")
        self.assertFalse(any(s < 8.2 and e <= 8.2 for s, e in report["gaps"]),
                         report["gaps"])

    def test_same_hold_without_recompose_still_flags(self) -> None:
        plan = self._rail_plan()
        plan["punchIns"] = []
        report = pac.pacing_report(plan, 300.0, "longform")
        self.assertTrue(any(e <= 8.2 for s, e in report["gaps"]),
                        report["gaps"])

    def test_own_screen_hold_is_not_exempt(self) -> None:
        plan = self._rail_plan()
        plan["graphicsTrack"][0]["anchor"] = "own-screen"
        report = pac.pacing_report(plan, 300.0, "longform")
        self.assertTrue(any(e <= 8.2 for s, e in report["gaps"]),
                        report["gaps"])

    def test_suggest_fills_skips_recomposed_hold(self) -> None:
        fills = pac.suggest_fills(self._rail_plan(), 300.0, "longform")
        self.assertFalse(any(1.2 <= f["at"] <= 8.1 for f in fills), fills)
