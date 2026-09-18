#!/usr/bin/env python3
"""Face-anchored recompose + smooth-longform grammar tests (operator defect
report 2026-07-10): motion/recompose.py solver + window emission,
punch_in releaseS easing, and plan_lint_smooth enforcement (pop boundaries,
under-panel guard, rail recompose, layout discipline, flash warns)."""
import copy
import unittest
from unittest import mock

from _common import *  # noqa: F401,F403

from motion import recompose as rc
import plan_lint_smooth as pls
from producer_config import MOTION

_REC = MOTION["recompose"]


def longform_plan(**over) -> dict:
    """A lint-clean longform excerpt plan (10 x 6s segments, seams at 6..54)."""
    plan = {
        "planVersion": 1,
        "target": {"mode": "longform", "durationTargetS": 60, "excerpt": True},
        "cutTrack": [{"sourceId": "raw-1", "start": i * 6.0,
                      "end": (i + 1) * 6.0, "speed": 1.0} for i in range(10)],
        "reframe": {"strategy": "face"},
        "captions": {"burn": False, "style": "line"},
        "faceBBoxNorm": [0.47, 0.28, 0.16, 0.20],   # face center (0.55, 0.38)
    }
    plan.update(over)
    return plan


def rail_entry(start: float = 10.0, hold: float = 6.0, **over) -> dict:
    entry = {"outStart": start, "outEnd": start + hold, "kind": "glass-rail",
             "anchor": "free-band", "reason": "system map",
             "spec": {"eyebrow": "The pipeline", "title1": "Intake",
                      "sub1": "raw in", "entrance": "rail-push"}}
    entry.update(over)
    return entry


class RecomposeSolverTests(unittest.TestCase):
    """The scale+pan solver against the MEASURED defect numbers."""

    def test_measured_rail_case_lands_remaining_space_center(self) -> None:
        # Defect 1: ours held fx 0.507±0.035 under a 0.331W left rail; the
        # reference lands 0.667±0.012 = remaining-space center. Solve for the
        # measured face (fx 0.55) and verify the landing via the crop mirror.
        width = _REC["geometry"]["glass-rail"]["width_frac"]
        target = rc.clear_center([width, 1.0])
        self.assertAlmostEqual(target, 0.6651, places=4)
        zoom, cx = rc.solve_recompose(0.55, target)
        self.assertLessEqual(zoom, _REC["zoom_cap"])
        self.assertAlmostEqual(rc.face_out_x(0.55, zoom, cx), target, places=3)

    def test_zoom_is_pan_enabling_minimum_plus_margin(self) -> None:
        # z >= target/fx (crop pan room), bumped by the margin — never more.
        zoom, _ = rc.solve_recompose(0.55, 0.6651)
        self.assertAlmostEqual(zoom, (0.6651 / 0.55) * _REC["zoom_margin"],
                               places=3)

    def test_face_already_centered_floors_at_perceptible_zoom(self) -> None:
        zoom, cx = rc.solve_recompose(0.6651, 0.6651)
        self.assertAlmostEqual(zoom, _REC["zoom_floor"], places=4)
        self.assertAlmostEqual(rc.face_out_x(0.6651, zoom, cx), 0.6651,
                               places=3)

    def test_right_rail_clear_region_solves_leftward(self) -> None:
        # Face 0.45, panel on the RIGHT -> clear [0, 0.6698], target 0.3349.
        target = rc.clear_center([0.0, 0.6698])
        zoom, cx = rc.solve_recompose(0.45, target)
        self.assertAlmostEqual(rc.face_out_x(0.45, zoom, cx), target, places=3)

    def test_infeasible_recompose_fails_loud(self) -> None:
        # Face far left, target far right: needs zoom past the cap -> raise.
        with self.assertRaises(ValueError):
            rc.solve_recompose(0.2, 0.85)

    def test_bounded_solver_accepts_a_small_jump_cut_miss(self) -> None:
        zoom, center = rc.solve_recompose_bounded(0.49, 0.6875)
        landed = rc.face_out_x(0.49, zoom, center)
        self.assertAlmostEqual(zoom, _REC["zoom_cap"], places=4)
        self.assertLessEqual(abs(landed - 0.6875),
                             _REC["max_landing_error_frac"])
        self.assertGreater(landed, 0.65)

    def test_bounded_solver_rejects_a_large_layout_miss(self) -> None:
        with self.assertRaises(ValueError):
            rc.solve_recompose_bounded(0.2, 0.85)

    def test_edge_face_fails_loud(self) -> None:
        for fx in (0.0, 1.0):
            with self.assertRaises(ValueError):
                rc.solve_recompose(fx, 0.6651)

    def test_bad_clear_x_fails_loud(self) -> None:
        for bad in ([0.5], [0.7, 0.3], [-0.1, 0.5], [0.2, 1.2], "left",
                    [True, 1.0]):
            with self.assertRaises(ValueError):
                rc.clear_center(bad)

    def test_center_y_keeps_vertical_position_within_crop(self) -> None:
        cy = rc.solve_center_y(0.38, 1.25)
        self.assertGreaterEqual(cy, 0.5 / 1.25)
        self.assertLessEqual(cy, 1.0 - 0.5 / 1.25)


class PushReleaseTests(unittest.TestCase):
    """punch_in releaseS — eased release so pushes never pop back to wide."""

    def _win(self, release: float = 0.4):
        (w,) = pin.parse_windows([{"outStart": 2.0, "outEnd": 8.0,
                                   "zoom": 1.2, "attackS": 0.5,
                                   "releaseS": release}])
        return w

    def test_release_resolves_to_wide_at_out_end(self) -> None:
        w = self._win()
        self.assertAlmostEqual(pin.push_scale_at(w, 2.0), 1.0, places=4)
        self.assertAlmostEqual(pin.push_scale_at(w, 5.0), 1.2, places=4)  # hold
        self.assertAlmostEqual(pin.push_scale_at(w, 7.8), 1.1, places=4)  # mid
        self.assertAlmostEqual(pin.push_scale_at(w, 8.0), 1.0, places=4)  # wide
        self.assertGreater(pin.push_scale_at(w, 7.61), 1.19)   # hold until tail

    def test_no_release_still_holds_to_the_end(self) -> None:
        w = self._win(0.0)
        self.assertAlmostEqual(pin.push_scale_at(w, 8.0), 1.2, places=4)

    def test_release_expr_carries_both_eases(self) -> None:
        expr = pin._push_zoom_expr(self._win())
        self.assertEqual(expr.count("clip("), 6)     # attack + release smoothsteps
        self.assertIn("t-7.600000", expr)            # release starts at outEnd-0.4

    def test_attack_plus_release_over_window_rejected(self) -> None:
        with self.assertRaises(ValueError):
            pin.parse_windows([{"outStart": 0.0, "outEnd": 1.0, "zoom": 1.2,
                                "attackS": 0.6, "releaseS": 0.6}])

    def test_negative_release_rejected(self) -> None:
        with self.assertRaises(ValueError):
            pin.parse_windows([{"outStart": 0.0, "outEnd": 2.0, "zoom": 1.2,
                                "attackS": 0.5, "releaseS": -0.1}])


class WindowEmissionTests(unittest.TestCase):
    """window_for_entry / stamp / apply — the plan-side wire."""

    def test_window_shape_lead_attack_release(self) -> None:
        plan = longform_plan()
        entry = rail_entry(recompose={"clearX": [0.3302, 1.0]})
        w = rc.window_for_entry(entry, plan, 60.0)
        self.assertAlmostEqual(w["outStart"], 10.0 - _REC["lead_s"], places=3)
        self.assertAlmostEqual(w["outEnd"], 16.0, places=3)
        self.assertEqual(w["role"], "recompose")
        self.assertEqual(w["attackS"], _REC["move_s"])
        self.assertEqual(w["releaseS"], _REC["move_s"])
        self.assertAlmostEqual(
            rc.face_out_x(0.55, w["zoom"], w["centerX"]), 0.6651, places=3)
        # The emitted window parses clean through the render primitive.
        (win,) = pin.parse_windows([w])
        self.assertTrue(win.is_push)

    def test_solver_uses_face_after_baseline_transform(self) -> None:
        plan = longform_plan(
            baselineLook={"zoom": 1.15, "centerX": 0.5, "centerY": 0.5})
        entry = rail_entry(recompose={"clearX": [0.3302, 1.0]})
        window = rc.window_for_entry(entry, plan, 60.0)
        baseline_face = rc.face_out_x(0.55, 1.15, 0.5)
        landed = rc.face_out_x(
            baseline_face, window["zoom"], window["centerX"])
        self.assertAlmostEqual(landed, rc.clear_center([0.3302, 1.0]),
                               places=3)

    def test_missing_face_bbox_fails_loud(self) -> None:
        plan = longform_plan()
        del plan["faceBBoxNorm"]
        entry = rail_entry(recompose={"clearX": [0.3302, 1.0]})
        with self.assertRaises(ValueError):
            rc.window_for_entry(entry, plan, 60.0)

    def test_each_rail_uses_its_own_measured_face_window(self) -> None:
        first = rail_entry(start=10.0)
        second = rail_entry(start=30.0, kind="module-rail", spec={})
        plan = longform_plan(graphicsTrack=[first, second])
        zones = [
            {"faceBBoxNorm": [0.40, 0.20, 0.16, 0.24]},
            {"faceBBoxNorm": [0.48, 0.20, 0.16, 0.24]},
        ]
        with mock.patch("motion.visual_state.classify_zones",
                        return_value=zones) as classify:
            count = rc.stamp_entry_face_bboxes(plan, "baselined.mp4")
        self.assertEqual(count, 2)
        self.assertEqual(classify.call_args.args[1], [
            {"outStart": 10.0, "outEnd": 16.0},
            {"outStart": 30.0, "outEnd": 36.0},
        ])
        self.assertEqual(first["faceBBoxNorm"], zones[0]["faceBBoxNorm"])
        self.assertEqual(second["faceBBoxNorm"], zones[1]["faceBBoxNorm"])
        self.assertEqual(first["faceBBoxSource"], "measured-entry-window")

    def test_hold_too_short_for_both_eases_fails_loud(self) -> None:
        entry = rail_entry(hold=0.6, recompose={"clearX": [0.3302, 1.0]})
        with self.assertRaises(ValueError):
            rc.window_for_entry(entry, longform_plan(), 60.0)

    def test_stamp_defaults_every_registered_free_band_rail(self) -> None:
        plan = longform_plan(graphicsTrack=[
            rail_entry(),
            rail_entry(start=20.0, kind="module-rail", spec={}),
            rail_entry(start=30.0, kind="module-bullet-bars", spec={}),
            {"outStart": 40.0, "outEnd": 46.0, "kind": "statement-card",
             "anchor": "own-screen", "reason": "beat", "spec": {}}])
        self.assertEqual(rc.stamp_recompose(plan), 3)
        self.assertEqual([row["recompose"]["clearX"]
                          for row in plan["graphicsTrack"][:3]], [
                              [0.3302, 1.0], [0.3302, 1.0], [0.375, 1.0]])
        self.assertNotIn("recompose", plan["graphicsTrack"][3])
        self.assertEqual(rc.stamp_recompose(plan), 0)        # idempotent

    def test_registered_rail_cannot_opt_out(self) -> None:
        plan = longform_plan(graphicsTrack=[rail_entry(recompose=False)])
        with self.assertRaisesRegex(ValueError, "cannot disable"):
            rc.stamp_recompose(plan)

    def test_stamp_right_side_rail_clears_left(self) -> None:
        entry = rail_entry()
        entry["spec"]["side"] = "right"
        plan = longform_plan(graphicsTrack=[entry])
        rc.stamp_recompose(plan)
        self.assertEqual(entry["recompose"]["clearX"], [0.0, 0.6698])

    def test_apply_rebuilds_windows_idempotently(self) -> None:
        plan = longform_plan(graphicsTrack=[rail_entry()])
        summary = rc.apply_recompose(plan, 60.0)
        self.assertEqual((summary["stamped"], summary["windows"]), (1, 1))
        once = copy.deepcopy(plan["punchIns"])
        summary2 = rc.apply_recompose(plan, 60.0)
        self.assertEqual(summary2["replaced"], 1)
        self.assertEqual(plan["punchIns"], once)

    def test_apply_keeps_other_punches_and_guards_overlap(self) -> None:
        plan = longform_plan(graphicsTrack=[rail_entry()],
                             punchIns=[{"outStart": 30.0, "outEnd": 31.2,
                                        "zoom": 1.1}])
        rc.apply_recompose(plan, 60.0)
        self.assertEqual(len(plan["punchIns"]), 2)
        # Defect 4: a punch DURING the rail window collides -> fail loud.
        plan["punchIns"] = [{"outStart": 12.0, "outEnd": 13.2, "zoom": 1.1}]
        with self.assertRaises(ValueError):
            rc.apply_recompose(plan, 60.0)

    def test_apply_rejects_shorts(self) -> None:
        plan = good_plan()
        with self.assertRaises(ValueError):
            rc.apply_recompose(plan, 30.0)


class SmoothLintTests(unittest.TestCase):
    """plan_lint_smooth via the full lint gate — longform only."""

    def _errors(self, plan: dict) -> list[str]:
        return pl.lint(plan, MANIFEST).errors

    def _warnings(self, plan: dict) -> list[str]:
        return pl.lint(plan, MANIFEST).warnings

    def test_static_pop_off_seam_errors_on_longform(self) -> None:
        plan = longform_plan(punchIns=[{"outStart": 8.0, "outEnd": 9.2,
                                        "zoom": 1.1}])   # seams at 6/12
        self.assertTrue(any("shorts grammar" in e for e in self._errors(plan)),
                        self._errors(plan))

    def test_static_pop_on_seam_is_legal(self) -> None:
        # Onset AND release both land on seams (6 -> 12): G6 punch-cut.
        plan = longform_plan(punchIns=[{"outStart": 6.0, "outEnd": 12.0,
                                        "zoom": 1.1}])
        self.assertFalse([e for e in self._errors(plan)
                          if "shorts grammar" in e], self._errors(plan))

    def test_push_without_release_pops_at_end(self) -> None:
        plan = longform_plan(punchIns=[{"outStart": 6.0, "outEnd": 9.0,
                                        "zoom": 1.15, "attackS": 0.4}])
        errs = [e for e in self._errors(plan) if "9.00s" in e]
        self.assertTrue(errs, self._errors(plan))

    def test_push_with_release_is_smooth(self) -> None:
        plan = longform_plan(punchIns=[{"outStart": 6.0, "outEnd": 9.0,
                                        "zoom": 1.15, "attackS": 0.4,
                                        "releaseS": 0.4}])
        self.assertFalse([e for e in self._errors(plan)
                          if "shorts grammar" in e], self._errors(plan))

    def test_fast_attack_under_ease_floor_errors(self) -> None:
        plan = longform_plan(punchIns=[{"outStart": 6.0, "outEnd": 9.0,
                                        "zoom": 1.15, "attackS": 0.1,
                                        "releaseS": 0.4}])
        self.assertTrue(any("ease floor" in e for e in self._errors(plan)),
                        self._errors(plan))

    def test_shorts_keep_pop_grammar(self) -> None:
        # The same off-seam static pop stays LEGAL on a short (pop = shorts).
        plan = good_plan()
        plan["punchIns"] = [{"outStart": 8.0, "outEnd": 9.2, "zoom": 1.1}]
        self.assertFalse([e for e in self._errors(plan)
                          if "shorts grammar" in e], self._errors(plan))

    def test_pop_under_live_panel_errors_even_on_seam(self) -> None:
        # Defect 4: seam at 12s sits INSIDE the rail window 10-16 -> footage
        # jumps against a fixed graphic.
        plan = longform_plan(
            graphicsTrack=[rail_entry(recompose=False)],
            punchIns=[{"outStart": 12.0, "outEnd": 18.0, "zoom": 1.1}])
        self.assertTrue(any("while a panel is on screen" in e
                            for e in self._errors(plan)), self._errors(plan))

    def test_pop_under_own_screen_takeover_is_invisible_and_legal(self) -> None:
        plan = longform_plan(
            graphicsTrack=[{"outStart": 10.0, "outEnd": 16.0,
                            "kind": "statement-card", "anchor": "own-screen",
                            "reason": "beat", "spec": {"text": "x"}}],
            punchIns=[{"outStart": 12.0, "outEnd": 18.0, "zoom": 1.1}])
        self.assertFalse([e for e in self._errors(plan)
                          if "panel is on screen" in e], self._errors(plan))

    def test_on_seam_pop_near_graphic_edge_warns(self) -> None:
        plan = longform_plan(
            graphicsTrack=[{"outStart": 12.3, "outEnd": 16.0,
                            "kind": "stat-card", "anchor": "free-band",
                            "reason": "stat", "spec": {},
                            "faceBBoxNorm": [0.47, 0.28, 0.16, 0.2]}],
            punchIns=[{"outStart": 12.0, "outEnd": 18.0, "zoom": 1.1}])
        self.assertTrue(any("two visual events stack" in w
                            for w in self._warnings(plan)),
                        self._warnings(plan))

    def test_rail_without_recompose_window_fails_closed(self) -> None:
        plan = longform_plan(graphicsTrack=[rail_entry()])
        self.assertTrue(any("rail recompose is not delivery-safe" in error
                            for error in self._errors(plan)), self._errors(plan))

    def test_rail_with_applied_recompose_is_clean_and_exempt(self) -> None:
        plan = longform_plan(graphicsTrack=[rail_entry()])
        rc.apply_recompose(plan, 60.0)
        rep = pl.lint(plan, MANIFEST)
        self.assertFalse([e for e in rep.errors if "shorts grammar" in e
                          or "zoom events" in e], rep.errors)
        self.assertFalse([e for e in rep.errors if "rail recompose" in e],
                         rep.errors)
        self.assertFalse([w for w in rep.warnings if "counted against" in w],
                         rep.warnings)

    def test_rail_optout_fails_closed(self) -> None:
        plan = longform_plan(graphicsTrack=[rail_entry(recompose=False)])
        self.assertTrue(any("cannot disable" in error
                            for error in self._errors(plan)), self._errors(plan))

    def test_recompose_transform_drift_fails_closed(self) -> None:
        plan = longform_plan(graphicsTrack=[rail_entry()])
        rc.apply_recompose(plan, 60.0)
        plan["punchIns"][0]["centerX"] += 0.05
        self.assertTrue(any("differs in centerX" in error
                            for error in self._errors(plan)), self._errors(plan))

    def test_recompose_on_own_screen_errors(self) -> None:
        entry = {"outStart": 10.0, "outEnd": 16.0, "kind": "statement-card",
                 "anchor": "own-screen", "reason": "beat", "spec": {},
                 "recompose": {"clearX": [0.33, 1.0]}}
        plan = longform_plan(graphicsTrack=[entry])
        self.assertTrue(any("nothing to re-center" in e
                            for e in self._errors(plan)), self._errors(plan))

    def test_malformed_recompose_fields_error(self) -> None:
        entry = rail_entry(recompose={"clearX": [0.9, 0.1], "leadS": 2.0,
                                      "moveS": 0.01})
        plan = longform_plan(graphicsTrack=[entry])
        errs = self._errors(plan)
        for needle in ("clearX", "leadS", "moveS"):
            self.assertTrue(any(needle in e for e in errs), (needle, errs))

    def test_layout_family_discipline_warns_over_cap(self) -> None:
        kinds = ("glass-rail", "module-takeover", "glass-lower-third",
                 "statement-card", "whiteboard-list")   # 5 families > cap 3
        graphics = [{"outStart": 6.0 + i * 8, "outEnd": 10.0 + i * 8,
                     "kind": k, "anchor": "own-screen", "reason": "x",
                     "spec": {}} for i, k in enumerate(kinds)]
        rep = pl.Report()
        pls._check_layout_families(graphics, rep)
        self.assertTrue(any("layout families" in w for w in rep.warnings),
                        rep.warnings)
        rep2 = pl.Report()
        pls._check_layout_families(graphics[:2], rep2)
        self.assertEqual(rep2.warnings, [])

    def test_flash_transitions_warn_on_longform(self) -> None:
        plan = longform_plan(transitions=[{"outTime": 8.0,
                                           "kind": "light-leak"}])
        self.assertTrue(any("off-grammar for longform" in w
                            for w in self._warnings(plan)),
                        self._warnings(plan))
        short = good_plan()
        short["transitions"] = [{"outTime": 8.0, "kind": "light-leak"}]
        self.assertFalse([w for w in pl.lint(short, MANIFEST).warnings
                          if "off-grammar" in w])

    def test_release_s_shape_checked_by_punch_lint(self) -> None:
        plan = longform_plan(punchIns=[{"outStart": 6.0, "outEnd": 8.0,
                                        "zoom": 1.15, "attackS": 1.5,
                                        "releaseS": 1.5}])
        self.assertTrue(any("releaseS" in e for e in self._errors(plan)),
                        self._errors(plan))


class StampFaceBboxTests(unittest.TestCase):
    """measure-when-absent: the pre-gate step that lets recompose run standalone
    (recompose.py --video) and the checkpoint recenter without a hand-stamped box."""

    def _plan_with_rail(self) -> dict:
        plan = longform_plan()
        plan.pop("faceBBoxNorm", None)
        plan["graphicsTrack"] = [rail_entry()]
        return plan

    def _patch_measure(self, fn):
        original = rc.measure_face_bbox
        rc.measure_face_bbox = fn
        self.addCleanup(lambda: setattr(rc, "measure_face_bbox", original))

    def test_existing_bbox_is_returned_without_measuring(self) -> None:
        plan = longform_plan()                 # already carries faceBBoxNorm
        plan["graphicsTrack"] = [rail_entry()]
        calls: list = []
        self._patch_measure(lambda *a: calls.append(a) or [0.0, 0.0, 1.0, 1.0])
        self.assertEqual(rc.stamp_face_bbox(plan, "x.mp4", 60.0),
                         plan["faceBBoxNorm"])
        self.assertEqual(calls, [])            # never touched the video

    def test_noop_when_no_rail_requires_recompose(self) -> None:
        plan = longform_plan()
        plan.pop("faceBBoxNorm", None)
        plan["graphicsTrack"] = []             # no occluding rail
        self._patch_measure(lambda *a: (_ for _ in ()).throw(AssertionError()))
        self.assertIsNone(rc.stamp_face_bbox(plan, "x.mp4", 60.0))
        self.assertNotIn("faceBBoxNorm", plan)

    def test_measures_and_stamps_plan_wide_when_absent(self) -> None:
        plan = self._plan_with_rail()
        measured = [0.47, 0.28, 0.16, 0.20]    # the box the other tests use
        self._patch_measure(lambda v, d: list(measured))
        self.assertEqual(rc.stamp_face_bbox(plan, "src.mp4", 60.0), measured)
        self.assertEqual(plan["faceBBoxNorm"], measured)
        # stamped plan-wide -> apply_recompose now succeeds with no explicit face
        rc.apply_recompose(plan, 60.0)
        self.assertTrue(any(w.get("role") == "recompose"
                            for w in plan["punchIns"]))

    def test_unmeasurable_face_leaves_plan_unstamped_fail_closed(self) -> None:
        plan = self._plan_with_rail()
        def boom(video, out_dur):
            raise RuntimeError("no cv2")
        self._patch_measure(boom)
        self.assertIsNone(rc.stamp_face_bbox(plan, "src.mp4", 60.0))
        self.assertNotIn("faceBBoxNorm", plan)  # never fabricated


if __name__ == "__main__":
    unittest.main(verbosity=2)
