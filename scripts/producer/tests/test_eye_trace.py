"""Eye-trace continuity tests (LIAM move 4 — gaze bias + Audit B advisory).

Covers the four legs of the primitive:
  * GAZE READ — planner ``gazeXY`` wins, ``faceBBoxNorm`` center falls back,
    nothing known → None; a PRESENT-but-malformed gazeXY raises (fail loud).
  * ADDITIVE BIAS — ``_choose_region`` with a gaze breaks a near-tie toward
    the gaze side but NEVER overrides fit/emptiness legality; gaze=None is
    byte-identical to today's ordering.
  * SIDECAR ROW — ``placement_row`` fuses gaze + landed bbox into the
    normalized screen-unit distance (the measurement's metric).
  * AUDIT — ``evaluate_rows`` + ``audit_motion.check_eye_trace``: WARN past
    ``warn_dist_frac``, jolt-flag suppression, PASS within threshold, and a
    fail-closed evidence gate when the sidecar is absent or unmeasurable.
"""
import json
import math
import os
import tempfile
import unittest

from _common import *  # noqa: F401,F403

from audit.audit_checks import FAIL
from audit import audit_motion as amot
from planner import eye_trace as et
from planner import graphics_anchors as ga
from planner.free_space import FreeMap, Region
from producer_config import MOTION

CFG = MOTION["eye_trace"]


def _entry(**over) -> dict:
    base = {"outStart": 4.0, "outEnd": 6.0, "kind": "stat-card",
            "anchor": "headroom", "spec": {}, "reason": "test"}
    base.update(over)
    return base


def _free_map(regions: list) -> FreeMap:
    """A minimal FreeMap carrying pre-scored regions (canvas 1080x1920)."""
    return FreeMap(canvas_w=1080, canvas_h=1920, face=(390, 460, 300, 380),
                   expanded_face=(315, 300, 765, 840), body_col=None,
                   grid_cols=12, grid_rows=16, occupancy=[], regions=regions)


class GazeReadTests(unittest.TestCase):
    """gaze_xy precedence: gazeXY > faceBBoxNorm center > None; fail loud."""

    def test_gaze_xy_wins_over_face(self) -> None:
        entry = _entry(gazeXY=[0.8, 0.3], faceBBoxNorm=[0.3, 0.2, 0.3, 0.3])
        self.assertEqual(et.gaze_xy(entry), (0.8, 0.3))

    def test_face_center_fallback(self) -> None:
        entry = _entry(faceBBoxNorm=[0.3, 0.2, 0.3, 0.3])
        gx, gy = et.gaze_xy(entry)
        self.assertAlmostEqual(gx, 0.45)
        self.assertAlmostEqual(gy, 0.35)

    def test_no_source_is_none(self) -> None:
        self.assertIsNone(et.gaze_xy(_entry()))

    def test_malformed_face_bbox_is_none(self) -> None:
        # A bad faceBBoxNorm is the ANCHOR path's contract to reject
        # (resolve_offset raises); the gaze read just declines to guess.
        self.assertIsNone(et.gaze_xy(_entry(faceBBoxNorm=[0.3, 0.2, 0.3])))

    def test_malformed_gaze_xy_raises(self) -> None:
        for bad in ([0.5], [0.5, 1.2], ["a", 0.5], [0.5, True], 0.5):
            with self.assertRaises(ValueError):
                et.gaze_xy(_entry(gazeXY=bad))


class DistanceTests(unittest.TestCase):
    """The normalized screen-unit metric (the measurement's: mean 0.351)."""

    def test_dist_frac_is_normalized_euclidean(self) -> None:
        # (540, 480) on 1080x1920 = (0.5, 0.25); gaze (0.5, 0.75) → dy 0.5.
        self.assertAlmostEqual(
            et.dist_frac((540, 480), (0.5, 0.75), (1080, 1920)), 0.5)

    def test_bbox_center_is_the_landing_point(self) -> None:
        bbox = (0, 0, 1080, 960)          # center (540, 480) = (0.5, 0.25)
        self.assertAlmostEqual(
            et.bbox_dist_frac(bbox, (0.5, 0.25), (1080, 1920)), 0.0)

    def test_corner_to_corner_is_sqrt2(self) -> None:
        self.assertAlmostEqual(
            et.dist_frac((0, 0), (1.0, 1.0), (1080, 1920)), math.sqrt(2.0))


class RegionBiasTests(unittest.TestCase):
    """Additive near-tie breaker — bounded by bias_weight, 0 without a gaze."""

    def test_no_gaze_is_zero(self) -> None:
        self.assertEqual(et.region_bias((540, 200), None, (1080, 1920)), 0.0)

    def test_bias_bounded_by_weight(self) -> None:
        at_gaze = et.region_bias((540, 960), (0.5, 0.5), (1080, 1920))
        far = et.region_bias((0, 0), (1.0, 1.0), (1080, 1920))
        self.assertAlmostEqual(at_gaze, CFG["bias_weight"])
        self.assertAlmostEqual(far, 0.0)
        self.assertGreater(at_gaze, far)

    def test_choose_region_near_tie_flips_toward_gaze(self) -> None:
        # Two legal beside-face candidates in a NEAR tie (score gap smaller
        # than the bias swing): the gaze side wins.
        left = Region("left-of-face", 60, 460, 315, 840, "v",
                      emptiness=0.9, score=0.300)
        right = Region("right-of-face", 765, 460, 1020, 840, "v",
                       emptiness=0.9, score=0.301)
        fmap = _free_map([right, left])   # score-sorted desc, right first
        content = (0, 0, 200, 200)
        # Gaze hard LEFT → the 0.001 score gap flips.
        region, fallback = ga._choose_region(fmap, "beside-face", content,
                                             gaze=(0.05, 0.34))
        self.assertEqual(region.name, "left-of-face")
        self.assertFalse(fallback)
        # No gaze → today's ordering (right, the higher raw score).
        region, _ = ga._choose_region(fmap, "beside-face", content)
        self.assertEqual(region.name, "right-of-face")

    def test_bias_never_overrides_a_clear_score_gap(self) -> None:
        # The gap (0.2) dwarfs the max bias swing (bias_weight) — the gaze
        # cannot override a clearly better region (additive, not override).
        left = Region("left-of-face", 60, 460, 315, 840, "v",
                      emptiness=0.9, score=0.10)
        right = Region("right-of-face", 765, 460, 1020, 840, "v",
                       emptiness=0.9, score=0.30)
        fmap = _free_map([right, left])
        region, _ = ga._choose_region(fmap, "beside-face", (0, 0, 200, 200),
                                      gaze=(0.05, 0.34))
        self.assertEqual(region.name, "right-of-face")

    def test_bias_never_legalizes_an_unfit_region(self) -> None:
        # The gaze-side region can't HOLD the content — legality unchanged.
        left = Region("left-of-face", 60, 460, 315, 840, "v",
                      emptiness=0.9, score=0.9)      # width 255 < content 400
        right = Region("right-of-face", 500, 460, 1020, 840, "v",
                       emptiness=0.9, score=0.2)
        fmap = _free_map([left, right])
        region, _ = ga._choose_region(fmap, "beside-face", (0, 0, 400, 200),
                                      gaze=(0.05, 0.34))
        self.assertEqual(region.name, "right-of-face")


class SidecarRowTests(unittest.TestCase):
    """placement_row fuses the gaze read with the landed bbox."""

    def test_row_with_gaze_and_bbox(self) -> None:
        entry = _entry(faceBBoxNorm=[0.35, 0.15, 0.3, 0.3])
        meta = {"region": "headroom", "placedBBox": [200, 100, 880, 300]}
        row = et.placement_row(entry, meta, (1080, 1920))
        self.assertEqual(row["gaze"], [0.5, 0.3])
        self.assertEqual(row["placedBBox"], [200, 100, 880, 300])
        # landed center (540, 200) = (0.5, 0.1042) → dy ≈ 0.1958.
        self.assertAlmostEqual(row["gazeDistFrac"], 0.1958, places=4)
        self.assertFalse(row["deliberateJolt"])

    def test_row_without_gaze_or_bbox_skips_distance(self) -> None:
        row = et.placement_row(_entry(), {"region": None}, (1080, 1920))
        self.assertIsNone(row["gaze"])
        self.assertIsNone(row["gazeDistFrac"])
        entry = _entry(faceBBoxNorm=[0.35, 0.15, 0.3, 0.3])
        row = et.placement_row(entry, {"region": "v1-deviation"}, (1080, 1920))
        self.assertIsNotNone(row["gaze"])
        self.assertIsNone(row["gazeDistFrac"])   # v1 fallback has no bbox

    def test_jolt_flag_reads_the_config_key(self) -> None:
        entry = _entry(**{CFG["jolt_flag_key"]: True})
        row = et.placement_row(entry, {}, (1080, 1920))
        self.assertTrue(row["deliberateJolt"])


def _row(frac, jolt=False, **over) -> dict:
    base = {"kind": "stat-card", "anchor": "headroom", "outStart": 4.0,
            "outEnd": 6.0, "region": "headroom", "placedBBox": [0, 0, 10, 10],
            "canvas": [1080, 1920],
            "gaze": [0.5, 0.5], "gazeDistFrac": frac, "deliberateJolt": jolt}
    base.update(over)
    return base


class EvaluateRowsTests(unittest.TestCase):
    """The pure audit evaluator: threshold, jolt suppression, None skip."""

    def test_violation_past_threshold(self) -> None:
        checked, violations = et.evaluate_rows(
            [_row(CFG["warn_dist_frac"] + 0.01)])
        self.assertEqual((checked, len(violations)), (1, 1))

    def test_within_threshold_passes(self) -> None:
        checked, violations = et.evaluate_rows([_row(CFG["warn_dist_frac"])])
        self.assertEqual((checked, len(violations)), (1, 0))

    def test_jolt_flag_suppresses(self) -> None:
        checked, violations = et.evaluate_rows([_row(1.0, jolt=True)])
        self.assertEqual((checked, len(violations)), (1, 0))

    def test_unmeasurable_rows_skip(self) -> None:
        checked, violations = et.evaluate_rows([_row(None), _row(0.1)])
        self.assertEqual((checked, len(violations)), (1, 0))


class AuditCheckTests(unittest.TestCase):
    """audit_motion.check_eye_trace over a real placement sidecar."""

    _PLAN = {"target": {"mode": "longform", "treatment": "produced"},
             "graphicsTrack": [{"kind": "stat-card"}]}

    def _run(self, rows, plan=None) -> list:
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "graphics_placements.json"), "w") as f:
                json.dump(rows, f)
            selected = plan or {**self._PLAN, "graphicsTrack": [
                {"kind": "stat-card"} for _row_value in (rows or [None])
            ]}
            return amot.check_eye_trace(selected, tmp)

    def test_warns_past_threshold_and_never_fails(self) -> None:
        results = self._run([_row(0.9), _row(0.1)])
        self.assertEqual([r.status for r in results], [amot.WARN])
        self.assertIn("0.90 screen units", results[0].measured)

    def test_clean_rows_pass(self) -> None:
        results = self._run([_row(0.1), _row(None)])
        self.assertEqual([r.status for r in results], [amot.PASS])
        self.assertIn("1 gaze-measurable", results[0].measured)

    def test_missing_sidecar_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            results = amot.check_eye_trace(self._PLAN, tmp)
        self.assertEqual([r.status for r in results], [FAIL])
        self.assertIn("missing", results[0].measured)

    def test_missing_gaze_is_advisory_when_landed_bboxes_exist(self) -> None:
        results = self._run([_row(None), _row(None)])
        self.assertEqual([r.status for r in results], [amot.PASS])
        self.assertIn("landed graphic bbox", results[0].measured)

    def test_missing_landed_bbox_fails_closed(self) -> None:
        results = self._run([_row(None, placedBBox=None)])
        self.assertEqual([r.status for r in results], [FAIL])
        self.assertIn("no measurable landed bbox", results[0].measured)

    def test_own_screen_requires_exact_delivery_coverage(self) -> None:
        plan = {**self._PLAN, "graphicsTrack": [{"anchor": "own-screen"}]}
        good = _row(None, anchor="own-screen", region="full-frame",
                    placedBBox=[0, 0, 3840, 2160], canvas=[3840, 2160])
        self.assertEqual([r.status for r in self._run([good], plan)], [amot.PASS])
        bad = {**good, "placedBBox": [0, 0, 1920, 1080]}
        results = self._run([bad], plan)
        self.assertEqual([r.status for r in results], [FAIL])
        self.assertIn("did not cover", results[0].measured)

    def test_registered_rail_must_be_flush_to_its_authored_edge(self) -> None:
        plan = {**self._PLAN, "graphicsTrack": [{
            "kind": "nateherk-rail", "anchor": "beside-face",
            "spec": {},
        }]}
        good = _row(None, kind="nateherk-rail", anchor="beside-face",
                    region="fixed-canvas", placedBBox=[0, 0, 633, 1079],
                    canvas=[1920, 1080])
        self.assertEqual([r.status for r in self._run([good], plan)],
                         [amot.PASS])
        shifted = {**good, "placedBBox": [149, -78, 782, 1001]}
        results = self._run([shifted], plan)
        self.assertEqual([r.status for r in results], [FAIL])
        self.assertIn("fixed-edge left rail shifted", results[0].measured)

    def test_empty_sidecar_fails_closed(self) -> None:
        results = self._run([])
        self.assertEqual([r.status for r in results], [FAIL])
        self.assertIn("0 row(s) for 1 graphic(s)", results[0].measured)

    def test_no_graphics_or_clean_cut_is_silent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(amot.check_eye_trace(
                {"target": {"treatment": "produced"}}, tmp), [])
            self.assertEqual(amot.check_eye_trace(
                {"target": {"treatment": "clean-cut"},
                 "graphicsTrack": [{"kind": "x"}]}, tmp), [])


if __name__ == "__main__":
    unittest.main()
