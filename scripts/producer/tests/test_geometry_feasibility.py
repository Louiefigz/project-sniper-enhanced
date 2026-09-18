"""Geometry feasibility lint (contract v3 item #3) — the plan-time half.

Covers the shared occupancy predicate (caption band included, bandYOffsetPx
honored), the pure proxy→crop→punch composition math, the unified punch
scale mirror, and the lint verdict paths: WARN-with-evidence on a synthetic
tight-face plan, SKIP-with-evidence on out-of-depth compositions, and the
geometry_predictions.json side artifact.
"""
import json
import os
import tempfile
import unittest
from unittest import mock

from _common import *  # noqa: F401,F403  (exports fs = planner.free_space)

import gate_policy
import cut_speed as cs
from motion.punch_in import PunchWindow
from planner import geometry_feasibility as gf
from planner import geometry_proxy as gproxy
from planner.geometry_proxy import punch_scale_at
from planner import occupancy as occ
from planner import delivery_canvas as dc


def _plan(**over) -> dict:
    base = {
        "planVersion": 1,
        "target": {"mode": "short", "scope": "produced"},
        "cutTrack": [{"sourceId": "raw-1", "start": 0.0, "end": 30.0,
                      "speed": 1.0}],
        "reframe": {"strategy": "face"},
        "captions": {"burn": True, "style": "karaoke"},
        "graphicsTrack": [{"outStart": 4.0, "outEnd": 8.0, "kind": "chip-row",
                           "anchor": "headroom", "spec": {"items": ["a"]},
                           "reason": "test"}],
    }
    base.update(over)
    return base


def _run_for(plan: dict) -> gf.LintRun:
    return gf.LintRun(plan, {"sources": []}, "cache", (1080, 1920),
                      mode="short")


# A face whose delivery framing is TIGHT (60% of canvas width) and mid-frame:
# headroom above the hair and the lower third are both too short for the comp.
_TIGHT_FACE = (150.0, 500.0, 650.0, 700.0)
_TIGHT_GEOM = gproxy.DeliveryGeom(face_px=_TIGHT_FACE, hair_top=400.0,
                                  punch_scale=1.12, crop_strategy="face")
_BIG_CONTENT = (60, 300, 960, 900)      # 900x600 — fits no candidate band


class SharedOccupancyTests(unittest.TestCase):
    """The ONE occupancy predicate lint and render placement both consume."""

    def test_caption_band_honors_band_y_offset(self) -> None:
        x0, y0, x1, y1 = occ.caption_band_rect((1080, 1920))
        self.assertEqual((y0, y1), (1150, 1340))
        self.assertEqual((x0, x1), (0.0, 1080.0))
        _, y0s, _, y1s = occ.caption_band_rect((1080, 1920), 200)
        self.assertEqual((y0s, y1s), (950, 1140))
        x0, y0, x1, y1 = occ.caption_band_rect((3840, 2160))
        self.assertEqual((x0, y0, x1, y1),
                         (0.0, 1720.0, 3840.0, 1960.0))
        _, y0s, _, y1s = occ.caption_band_rect((3840, 2160), 200)
        self.assertEqual((y0s, y1s), (1320.0, 1560.0))

    def test_build_map_marks_the_caption_band_occupied(self) -> None:
        face = (400.0, 300.0, 280.0, 300.0)
        fmap = occ.build_map(face, set(), (1080, 1920))
        # A grid cell in the caption band (y ~1200, far from face/body column)
        # must read occupied; without the band it is free.
        row = int(1245 // (1920 / fmap.grid_rows))
        col = 0                                       # x ~0..90, body-free
        self.assertTrue(fmap.occupancy[row][col])
        rects = occ.occupied_rects(face, (1080, 1920), occ.OccupancyExtras())
        self.assertEqual(len(rects), 3)               # face+hair, body, band

    def test_render_side_assemble_free_map_delegates_to_shared(self) -> None:
        face = (400.0, 300.0, 280.0, 300.0)
        via_fs = fs.assemble_free_map(face, set(), (1080, 1920), hair_top=250.0)
        via_occ = occ.build_map(face, set(), (1080, 1920),
                                occ.OccupancyExtras(hair_top=250.0))
        self.assertEqual(via_fs.as_dict(), via_occ.as_dict())


class CompositionMathTests(unittest.TestCase):
    """Pure proxy→crop→punch mapping (the lint's delivery-geometry compose)."""

    def test_crop_to_delivery_maps_through_the_reframe_window(self) -> None:
        crop = {"cropX": 300, "cropWidth": 304, "frameHeight": 540}
        rect = gproxy.crop_to_delivery((320.0, 100.0, 76.0, 108.0), crop,
                                       (1080, 1920))
        sx, sy = 1080 / 304, 1920 / 540
        self.assertAlmostEqual(rect[0], (320 - 300) * sx, places=4)
        self.assertAlmostEqual(rect[1], 100 * sy, places=4)
        self.assertAlmostEqual(rect[2], 76 * sx, places=4)
        self.assertAlmostEqual(rect[3], 108 * sy, places=4)

    def test_punch_rect_expands_about_the_focal_point(self) -> None:
        out = gproxy.punch_rect((100.0, 100.0, 200.0, 200.0), 1.5,
                                (540.0, 960.0))
        self.assertAlmostEqual(out[0], 540 + (100 - 540) * 1.5)
        self.assertAlmostEqual(out[1], 960 + (100 - 960) * 1.5)
        self.assertAlmostEqual(out[2], 300.0)
        self.assertAlmostEqual(out[3], 300.0)
        same = gproxy.punch_rect((100.0, 100.0, 200.0, 200.0), 1.0, (0.0, 0.0))
        self.assertEqual(same, (100.0, 100.0, 200.0, 200.0))

    def test_punch_scale_at_covers_every_window_family(self) -> None:
        static = PunchWindow(2.0, 4.0, 1.2)
        self.assertEqual(punch_scale_at(static, 3.0), 1.2)
        self.assertEqual(punch_scale_at(static, 5.0), 1.0)
        ramp = PunchWindow(0.0, 10.0, 1.0, origin="ramp", ramp_dir="in",
                           ramp_rate=0.01)
        self.assertAlmostEqual(punch_scale_at(ramp, 10.0), 1.1)
        push = PunchWindow(0.0, 5.0, 1.3, origin="push", attack_s=1.0)
        self.assertAlmostEqual(punch_scale_at(push, 3.0), 1.3)

    def test_max_punch_takes_the_overlap_maximum(self) -> None:
        wins = [PunchWindow(2.0, 6.0, 1.12, center_x=0.4),
                PunchWindow(7.0, 9.0, 1.4, center_x=0.6)]
        scale, center = gproxy.max_punch(wins, 4.0, 8.0)
        self.assertAlmostEqual(scale, 1.4)
        self.assertAlmostEqual(center[0], 0.6)
        scale, center = gproxy.max_punch(wins, 20.0, 22.0)
        self.assertEqual((scale, center), (1.0, (0.5, 0.5)))

    def test_crops_for_window_dedupes_and_filters(self) -> None:
        wins = [{"outStart": 0.0, "outEnd": 5.0, "cropX": 10, "cropWidth": 300},
                {"outStart": 5.0, "outEnd": 9.0, "cropX": 10, "cropWidth": 300},
                {"outStart": 9.0, "outEnd": 12.0, "cropX": 90, "cropWidth": 300}]
        got = gproxy.crops_for_window(wins, 4.0, 10.0)
        self.assertEqual([w["cropX"] for w in got], [10, 90])

    def test_proxy_profile_snaps_even_and_keeps_fps(self) -> None:
        from fractions import Fraction
        full = cs.Profile(1920, 1080, Fraction(30000, 1001), "yuv420p")
        proxy = cs.proxy_profile(full, 0.5)
        self.assertEqual((proxy.width, proxy.height), (960, 540))
        self.assertEqual(proxy.fps, full.fps)
        with self.assertRaises(ValueError):
            cs.proxy_profile(full, 1.5)

    def test_native_longform_canvas_comes_from_first_cut_source(self) -> None:
        plan = _plan(target={"mode": "longform", "scope": "produced"},
                     reframe={"strategy": "none"})
        manifest = {"sources": [{"id": "raw-1",
                                 "resolution": [3840, 2160],
                                 "rotation": 0}]}
        self.assertEqual(dc.resolve_delivery_canvas(plan, manifest),
                         (3840, 2160))
        manifest["sources"][0]["resolution"] = [2160, 3840]
        manifest["sources"][0]["rotation"] = 90
        self.assertEqual(dc.resolve_delivery_canvas(plan, manifest),
                         (3840, 2160))


class LintVerdictTests(unittest.TestCase):
    """WARN-with-evidence / SKIP-with-evidence through the real chooser."""

    def _checked(self, run: gf.LintRun, geom, content=_BIG_CONTENT) -> None:
        entry = run.plan["graphicsTrack"][0]
        with mock.patch.object(gf, "render_entry",
                               return_value={"path": "c.mov", "fmt": "mov",
                                             "kind": "chip-row",
                                             "cached": True, "key": "k"}), \
             mock.patch.object(gf, "_content_bbox", return_value=content), \
             mock.patch.object(gf, "_clip_dims",
                               return_value=run.canvas):
            gf.check_window(run, "graphicsTrack[0] chip-row", entry, geom)

    def test_tight_face_fires_warn_with_anatomy_evidence(self) -> None:
        run = _run_for(_plan())
        self._checked(run, _TIGHT_GEOM)
        self.assertEqual(len(run.verdicts), 1)
        verdict = run.verdicts[0]
        self.assertEqual(verdict.severity, "WARN")     # A3: uncalibrated
        self.assertEqual(verdict.gate, gf.GATE)
        payload = json.loads(verdict.evidence.split("— ", 1)[1])
        self.assertAlmostEqual(payload["faceWidthFrac"], 650 / 1080, places=3)
        self.assertEqual(payload["contentDims"], [900, 600])
        self.assertEqual(payload["punchScale"], 1.12)
        self.assertTrue(payload["regionsTried"])       # candidates enumerated
        self.assertEqual(gate_policy.resolve(verdict, run.plan["target"]),
                         "advise")

    def test_feasible_geometry_stays_silent_and_predicts(self) -> None:
        run = _run_for(_plan())
        wide_face = gproxy.DeliveryGeom((400.0, 300.0, 280.0, 300.0), 250.0,
                                        1.0, "face")
        self._checked(run, wide_face, content=(200, 855, 880, 1055))
        self.assertEqual(run.verdicts, [])
        self.assertEqual(len(run.predictions), 1)
        row = run.predictions[0]
        self.assertIsNotNone(row["region"])
        self.assertEqual(len(row["expandedFace"]), 4)

    def test_baseline_look_refuses_loudly(self) -> None:
        reason = gf.applicability_skip(_plan(baselineLook={"enabled": True}))
        self.assertIn("baselineLook", reason)
        self.assertIn("manual reframe",
                      gf.applicability_skip(_plan(reframe={"strategy": "face",
                                                           "crop": [0, 0, 1, 1]})))
        self.assertIn("strategy",
                      gf.applicability_skip(_plan(reframe={"strategy": "center"})))
        self.assertIsNone(gf.applicability_skip(_plan()))
        long_plan = _plan(
            target={"mode": "longform", "scope": "produced"},
            reframe={"strategy": "none"})
        self.assertIsNone(gf.applicability_skip(long_plan))

    def test_broll_and_title_card_overlap_refuse_per_entry(self) -> None:
        plan = _plan(brollTrack=[{"outStart": 5.0, "outEnd": 6.0,
                                  "assetId": "b"}])
        self.assertIn("brollTrack",
                      gf.entry_depth_skip(plan["graphicsTrack"][0], plan))
        plan = _plan(titleCards=[{"outStart": 7.0, "outEnd": 9.0, "text": "x"}])
        self.assertIn("titleCards",
                      gf.entry_depth_skip(plan["graphicsTrack"][0], plan))
        clear = _plan(titleCards=[{"outStart": 0.0, "outEnd": 2.0, "text": "x"}])
        self.assertIsNone(gf.entry_depth_skip(clear["graphicsTrack"][0], clear))

    def test_checked_entries_selects_only_the_v2_placement_class(self) -> None:
        plan = _plan(graphicsTrack=[
            {"outStart": 1.0, "outEnd": 2.0, "kind": "a", "anchor": "headroom"},
            {"outStart": 3.0, "outEnd": 4.0, "kind": "b", "anchor": "own-screen"},
            {"outStart": 5.0, "outEnd": 6.0, "kind": "c", "anchor": "chest",
             "placement": {"x": 10, "y": 10}},
            {"outStart": 7.0, "outEnd": 8.0, "kind": "d", "anchor": "free-band"},
        ])
        picked = [e["kind"] for _i, e in gf.checked_entries(plan)]
        self.assertEqual(picked, ["a"])

    def test_lint_plan_end_to_end_writes_predictions(self) -> None:
        plan = _plan()
        crops = [{"outStart": 0.0, "outEnd": 30.0, "cropX": 480,
                  "cropWidth": 1080, "frameWidth": 1920, "frameHeight": 1920,
                  "strategy": "face"}]
        with tempfile.TemporaryDirectory() as tmp:
            run = gf.LintRun(plan, {"sources": []}, "cache", (1080, 1920),
                             mode="short")
            with mock.patch.object(gf, "environment_issue", return_value=None), \
                 mock.patch.object(gf.gproxy, "render_proxy",
                                   return_value={"path": "p.mp4",
                                                 "elapsedS": 0.1,
                                                 "scale": 0.5}), \
                 mock.patch.object(gf.gproxy, "reframe_crop_windows",
                                   return_value=crops), \
                 mock.patch.object(gf.gproxy, "observe_window",
                                   return_value=((630.0, 500.0, 650.0, 700.0),
                                                 400.0, (1080, 1920))), \
                 mock.patch.object(gf, "render_entry",
                                   return_value={"path": "c.mov", "fmt": "mov",
                                                 "kind": "chip-row",
                                                 "cached": True, "key": "k"}), \
                 mock.patch.object(gf, "_content_bbox",
                                   return_value=_BIG_CONTENT), \
                 mock.patch.object(gf, "_clip_dims",
                                   return_value=(1080, 1920)):
                gf.lint_plan(run, tmp, tmp)
            self.assertEqual(run.metrics["checked"], 1)
            self.assertEqual(run.metrics["warned"], 1)
            path = os.path.join(tmp, gf.PREDICTIONS_FILENAME)
            with open(path) as f:
                predictions = json.load(f)
            self.assertEqual(predictions["gate"], gf.GATE)
            self.assertEqual(len(predictions["windows"]), 1)
            self.assertIn("expandedFace", predictions["windows"][0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
