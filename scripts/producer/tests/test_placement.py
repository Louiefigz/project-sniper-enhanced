"""Explicit-placement contract tests (entry.placement beats anchor resolution).

Covers the three legs of the contract:
  * PRECEDENCE — stage_placement.resolve_placement uses the explicit {x, y} pin and
    never consults resolve_offset_v2 / the v1 fallback for a placed entry.
  * ABSENT = UNTOUCHED — entries without placement go down the exact existing
    anchor path (same calls, same values, byte-identical filter graph).
  * LINT MATRIX — plan_lint_motion._check_placement: finite numbers, on-canvas
    (error), shorts SAFE_BOX edges (warning naming the edge), own-screen ban.
"""
import math
import copy
import unittest
from unittest import mock

from _common import *  # noqa: F401,F403

from graphics import delivery_geometry as dg
from graphics import graphics_stage as gs
from graphics import placement_context as pc
from graphics import stage_placement as sp
from planner import occupancy as occ
from planner import free_space_sample as fss
from producer_config import PLACEMENT_SCALE

# A synthetic rendered-content footprint (x0, y0, x1, y1) on the comp canvas.
_CONTENT = (200, 855, 880, 1055)


def _entry(**over) -> dict:
    base = {"outStart": 4.0, "outEnd": 6.0, "kind": "stat-card",
            "anchor": "free-band",
            "spec": {"value": "TEST", "label": "PLACEMENT"},
            "reason": "test"}
    base.update(over)
    return base


class PlacementPrecedenceTests(unittest.TestCase):
    """Explicit placement wins outright; failures are loud, never a fallback."""

    def test_placement_beats_anchor_resolution(self) -> None:
        entry = _entry(anchor="headroom", faceBBoxNorm=[0.3, 0.2, 0.3, 0.3],
                       placement={"x": 60, "y": 300})
        with mock.patch.object(sp, "_content_bbox", return_value=_CONTENT), \
             mock.patch.object(sp, "resolve_offset_v2",
                               side_effect=AssertionError("anchor path used")), \
             mock.patch.object(sp, "resolve_offset",
                               side_effect=AssertionError("v1 path used")):
            x, y, meta = sp.resolve_placement(entry, "fake.mov", "base.mp4")
        self.assertEqual((x, y), (60 - _CONTENT[0], 300 - _CONTENT[1]))
        self.assertEqual(meta["region"], "explicit-placement")
        self.assertEqual(meta["placedBBox"][:2], [60, 300])

    def test_placed_content_lands_at_the_point(self) -> None:
        entry = _entry(placement={"x": 0, "y": 0})
        with mock.patch.object(sp, "_content_bbox", return_value=_CONTENT):
            x, y, meta = sp.resolve_placement(entry, "fake.mov", "base.mp4")
        self.assertEqual(meta["placedBBox"],
                         [0, 0, _CONTENT[2] - _CONTENT[0], _CONTENT[3] - _CONTENT[1]])
        self.assertEqual((x, y), (-_CONTENT[0], -_CONTENT[1]))

    def test_own_screen_placement_raises(self) -> None:
        entry = _entry(anchor="own-screen", placement={"x": 60, "y": 300})
        with self.assertRaisesRegex(ValueError, "full-frame"):
            sp.resolve_placement(entry, "fake.mov", "base.mp4")

    def test_malformed_placement_raises(self) -> None:
        for bad in ([60, 300], {"x": 60}, {"x": "60", "y": 300},
                    {"x": float("nan"), "y": 300}, {"x": True, "y": 300},
                    {"x": float("inf"), "y": 0}):
            with self.assertRaises(ValueError, msg=f"accepted {bad!r}"):
                sp.resolve_placement(_entry(placement=bad), "fake.mov", "base.mp4")

    def test_measurement_failure_is_loud_not_a_fallback(self) -> None:
        entry = _entry(placement={"x": 60, "y": 300})
        with mock.patch.object(sp, "_content_bbox",
                               side_effect=RuntimeError("no alpha content")), \
             mock.patch.object(sp, "resolve_offset",
                               side_effect=AssertionError("v1 fallback used")):
            with self.assertRaisesRegex(RuntimeError, "no alpha content"):
                sp.resolve_placement(entry, "fake.mov", "base.mp4")


class AbsentPlacementPathTests(unittest.TestCase):
    """No placement key → the pre-existing anchor path, bit for bit."""

    def test_registered_edge_rail_stays_at_its_authored_origin(self) -> None:
        content = (0, 0, 633, 1079)
        entry = _entry(kind="nateherk-rail", anchor="beside-face",
                       recompose={"clearX": [0.3302, 1.0]})
        with mock.patch.object(sp, "_content_bbox", return_value=content), \
             mock.patch.object(sp, "resolve_offset_v2",
                               side_effect=AssertionError("rail was floated")):
            x, y, meta = sp.resolve_placement(entry, "rail.mov", "base.mp4")
        self.assertEqual((x, y), (0, 0))
        self.assertEqual(meta["region"], "fixed-canvas")
        self.assertEqual(meta["placedBBox"], list(content))

    def test_absent_placement_uses_v2_verbatim(self) -> None:
        sentinel = (7, 9, {"region": "sentinel"})
        with mock.patch.object(sp, "resolve_offset_v2", return_value=sentinel), \
             mock.patch.object(sp, "_content_bbox",
                               side_effect=AssertionError("content probed")):
            self.assertEqual(sp.resolve_placement(_entry(), "fake.mov", "b.mp4"), sentinel)

    def test_absent_placement_keeps_v1_fallback(self) -> None:
        with mock.patch.object(sp, "resolve_offset_v2",
                               side_effect=RuntimeError("no cv2")), \
             mock.patch.object(sp, "resolve_offset", return_value=(3, 4)):
            x, y, meta = sp.resolve_placement(_entry(), "fake.mov", "b.mp4")
        self.assertEqual((x, y, meta["region"]), (3, 4, "v1-fallback"))

    def test_v1_fallback_still_emits_measured_placement_evidence(self) -> None:
        meta = {"anchor": "free-band", "region": "v1-fallback",
                "fallback": True}
        with mock.patch.object(dg, "_content_bbox", return_value=_CONTENT), \
             mock.patch.object(dg, "_clip_dims", return_value=(1920, 1080)):
            measured = dg.fallback_placement_evidence(
                "fake.mov", (3, 4), meta, (1920, 1080))
        self.assertEqual(measured["contentBBox"], list(_CONTENT))
        self.assertEqual(measured["placedBBox"],
                         [203, 859, 883, 1059])

    def test_own_screen_scales_to_the_delivery_canvas(self) -> None:
        dims = {"comp.mp4": (1920, 1080), "base.mp4": (3840, 2160)}
        with mock.patch.object(sp, "_clip_dims", side_effect=lambda name: dims[name]):
            x, y, meta = sp.resolve_placement(
                _entry(anchor="own-screen"), "comp.mp4", "base.mp4")
        self.assertEqual((x, y), (0, 0))
        self.assertEqual(meta["placedBBox"], [0, 0, 3840, 2160])
        self.assertEqual(meta["scaledDims"], [3840, 2160])
        graph, _ = gs._build_graph([{
            "path": "comp.mp4", "outStart": 2.0, "outEnd": 4.0,
            "anchor": "own-screen", "x": x, "y": y,
            "scaleDims": meta["scaledDims"],
        }])
        self.assertIn("scale=3840:2160:flags=lanczos", graph)

    def test_own_screen_rejects_a_mismatched_aspect(self) -> None:
        dims = {"comp.mp4": (1080, 1920), "base.mp4": (3840, 2160)}
        with mock.patch.object(sp, "_clip_dims", side_effect=lambda name: dims[name]):
            with self.assertRaisesRegex(ValueError, "does not match delivery aspect"):
                sp.resolve_placement(_entry(anchor="own-screen"), "comp.mp4", "base.mp4")

    def test_4k_free_band_scales_full_canvas_and_authored_geometry(self) -> None:
        meta = {"anchor": "free-band", "region": "explicit-placement",
                "placement": [60, 300], "contentBBox": [300, 200, 900, 500],
                "placedBBox": [60, 300, 660, 600]}
        with mock.patch.object(dg, "_clip_dims", return_value=(1920, 1080)):
            x, y, scaled = gs._delivery_geometry(
                "comp.mov", (-240, 100), meta, (3840, 2160))
        self.assertEqual((x, y), (-480, 200))
        self.assertEqual(scaled["scaledDims"], [3840, 2160])
        self.assertEqual(scaled["placement"], [120, 600])
        self.assertEqual(scaled["placedBBox"], [120, 600, 1320, 1200])
        graph, _ = gs._build_graph([{
            "path": "comp.mov", "outStart": 2.0, "outEnd": 4.0,
            "anchor": "free-band", "x": x, "y": y,
            "scaleDims": scaled["scaledDims"],
        }])
        self.assertIn("scale=3840:2160:flags=lanczos", graph)
        self.assertIn("overlay=x=-480:y=200:", graph)

    def test_render_all_wires_4k_free_band_scaling_into_clip(self) -> None:
        rendered = {"path": "comp.mov", "cached": True, "key": "k",
                    "kind": "stat-card", "fmt": "mov"}
        dims = {"base.mp4": (3840, 2160), "comp.mov": (1920, 1080)}
        with mock.patch.object(gs, "render_entry", return_value=rendered), \
             mock.patch.object(gs, "_clip_fps", return_value=30.0), \
             mock.patch.object(gs, "resolve_placement", return_value=(0, 0, {
                 "anchor": "free-band", "region": None,
             })), mock.patch.object(gs, "_clip_dims",
                                    side_effect=lambda name: dims[name]), \
             mock.patch.object(dg, "_clip_dims",
                               side_effect=lambda name: dims[name]), \
             mock.patch.object(gs, "emit"):
            clips, _rows = gs._render_all([_entry()], None, "base.mp4")
        self.assertEqual(clips[0]["scaleDims"], [3840, 2160])
        self.assertEqual((clips[0]["x"], clips[0]["y"]), (0, 0))

    def test_1080_free_band_geometry_and_graph_stay_unchanged(self) -> None:
        meta = {"anchor": "free-band", "region": None}
        with mock.patch.object(dg, "_clip_dims", return_value=(1920, 1080)):
            x, y, same = gs._delivery_geometry(
                "comp.mov", (0, 0), meta, (1920, 1080))
        self.assertEqual((x, y), (0, 0))
        self.assertIs(same, meta)
        self.assertNotIn("scaledDims", same)
        graph, _ = gs._build_graph([{
            "path": "comp.mov", "outStart": 2.0, "outEnd": 4.0,
            "anchor": "free-band", "x": x, "y": y,
        }])
        self.assertNotIn("scale=", graph)

    def test_4k_face_anchor_fails_instead_of_double_scaling_offset(self) -> None:
        meta = {"anchor": "headroom", "region": "headroom",
                "contentBBox": [300, 200, 900, 500],
                "placedBBox": [60, 80, 660, 380]}
        with mock.patch.object(dg, "_clip_dims", return_value=(1920, 1080)):
            with self.assertRaisesRegex(ValueError, "delivery-sized footprint"):
                gs._delivery_geometry("comp.mov", (-240, -120), meta,
                                      (3840, 2160))

    def test_delivery_resolved_4k_face_anchor_is_not_double_scaled(self) -> None:
        meta = {"anchor": "headroom", "region": "headroom",
                "faceAware": True, "authoredCanvas": [1920, 1080],
                "canvas": [3840, 2160], "scaledDims": [3840, 2160],
                "contentBBox": [600, 400, 1800, 1000],
                "placedBBox": [120, 160, 1320, 760]}
        with mock.patch.object(dg, "_clip_dims", return_value=(1920, 1080)):
            x, y, fitted = gs._delivery_geometry(
                "comp.mov", (-480, -240), meta, (3840, 2160))
        self.assertEqual((x, y), (-480, -240))
        self.assertEqual(fitted["placedBBox"], meta["placedBBox"])
        self.assertEqual(fitted["scaledDims"], [3840, 2160])
        self.assertEqual(fitted["canvasScale"], [2.0, 2.0])

    def test_zero_offset_filter_graph_is_byte_stable(self) -> None:
        clips = [{"path": "c.mov", "outStart": 2.0, "outEnd": 4.0,
                  "anchor": "free-band", "x": 0, "y": 0}]
        graph, final = gs._build_graph(clips)
        self.assertEqual(graph,
                         "[1:v]setpts=PTS-STARTPTS+2.0000/TB[ov0];"
                         "[0:v][ov0]overlay=enable='between(t,2.0000,4.0000)'"
                         ":format=auto[gc0]")
        self.assertEqual(final, "[gc0]")

    def test_negative_offset_reaches_the_overlay_string(self) -> None:
        clips = [{"path": "c.mov", "outStart": 2.0, "outEnd": 4.0,
                  "anchor": "free-band", "x": -140, "y": -555}]
        graph, _ = gs._build_graph(clips)
        self.assertIn("overlay=x=-140:y=-555:", graph)


class FaceAwareFreeBandTests(unittest.TestCase):
    """Portrait free-band clips inherit face authority and avoid occlusion."""

    @staticmethod
    def _map():
        return occ.build_map(
            (240.0, 724.0, 444.0, 444.0), set(), (1080, 1920),
            occ.OccupancyExtras(),
        )

    def test_global_face_box_is_bound_without_mutating_plan(self) -> None:
        plan = {
            "faceBBoxNorm": [0.2, 0.3, 0.4, 0.2],
            "graphicsTrack": [
                _entry(),
                _entry(anchor="headroom"),
                _entry(anchor="own-screen"),
                _entry(placement={"x": 60, "y": 300}),
            ],
        }
        before = copy.deepcopy(plan)
        track = pc.bind_plan_face_bbox(plan["graphicsTrack"], plan)
        self.assertEqual(track[0]["faceBBoxNorm"], plan["faceBBoxNorm"])
        self.assertEqual(track[1]["faceBBoxNorm"], plan["faceBBoxNorm"])
        self.assertNotIn("faceBBoxNorm", track[2])
        self.assertNotIn("faceBBoxNorm", track[3])
        self.assertEqual(plan, before)

    def test_malformed_global_face_box_fails_closed(self) -> None:
        plan = {"faceBBoxNorm": [0.2, 0.3, float("nan"), 0.2],
                "graphicsTrack": [_entry()]}
        with self.assertRaisesRegex(ValueError, "faceBBoxNorm"):
            pc.bind_plan_face_bbox(plan["graphicsTrack"], plan)

    def test_malformed_entry_box_uses_valid_global_without_mutation(self) -> None:
        plan = {"faceBBoxNorm": [0.2, 0.3, 0.4, 0.2],
                "graphicsTrack": [
                    _entry(faceBBoxNorm=[0.8, 0.3, 0.4, 0.2])]}
        before = copy.deepcopy(plan)
        track = pc.bind_plan_face_bbox(plan["graphicsTrack"], plan)
        self.assertEqual(track[0]["faceBBoxNorm"], plan["faceBBoxNorm"])
        self.assertEqual(plan, before)

    def test_malformed_entry_box_without_global_fails_closed(self) -> None:
        plan = {"graphicsTrack": [_entry(faceBBoxNorm=[0.2, 0.3, 0.0, 0.2])]}
        with self.assertRaisesRegex(ValueError, "graphicsTrack faceBBoxNorm"):
            pc.bind_plan_face_bbox(plan["graphicsTrack"], plan)

    def test_normalized_face_box_requires_positive_in_bounds_area(self) -> None:
        self.assertTrue(ga.valid_face_bbox([0.2, 0.3, 0.4, 0.2]))
        bad = (
            [0.2, 0.3, 0.0, 0.2], [0.2, 0.3, 0.4, 0.0],
            [-0.1, 0.3, 0.4, 0.2], [0.8, 0.3, 0.4, 0.2],
            [0.2, 0.9, 0.4, 0.2], [0.2, 0.3, float("nan"), 0.2],
        )
        for bbox in bad:
            self.assertFalse(ga.valid_face_bbox(bbox), bbox)
            self.assertFalse(plm._valid_bbox(bbox), bbox)

    def test_plan_lint_resolution_skips_bad_entry_for_valid_global(self) -> None:
        bad_entry = {"faceBBoxNorm": [0.8, 0.3, 0.4, 0.2]}
        global_bbox = [0.2, 0.3, 0.4, 0.2]
        self.assertEqual(
            plm._resolve_face_bbox(bad_entry, None, global_bbox),
            global_bbox,
        )

    def _resolve(self, content: tuple, free_map=None) -> tuple:
        entry = _entry(faceBBoxNorm=[0.2, 0.3, 0.4, 0.2])
        with mock.patch.object(
                fs, "build_free_map", return_value=free_map or self._map()), \
             mock.patch.object(ga, "_content_bbox", return_value=content), \
             mock.patch.object(ga, "_clip_dims", return_value=(1080, 1920)):
            return ga.resolve_offset_v2(entry, "comp.mov", "base.mp4")

    def test_clear_authored_section_marker_is_preserved_and_measured(self) -> None:
        x, y, meta = self._resolve((0, 206, 537, 511))
        self.assertEqual((x, y), (0, 0))
        self.assertEqual(meta["region"], "authored-clear")
        self.assertTrue(meta["faceAware"])
        self.assertEqual(meta["placedBBox"], [0, 206, 537, 511])
        self.assertEqual(len(meta["expandedFace"]), 4)

    def test_face_occluding_chip_row_moves_above_the_hair(self) -> None:
        _x, _y, meta = self._resolve((234, 731, 754, 1016))
        self.assertEqual(meta["region"], "headroom")
        self.assertLessEqual(meta["placedBBox"][3], meta["expandedFace"][1])
        self.assertNotEqual(meta["placedBBox"], [234, 731, 754, 1016])

    def test_tall_chip_stack_downscales_to_a_legal_headroom_region(self) -> None:
        _x, _y, meta = self._resolve((153, 400, 835, 1100))
        self.assertEqual(meta["region"], "headroom")
        self.assertLess(meta["scale"], 1.0)
        self.assertGreaterEqual(meta["scale"], PLACEMENT_SCALE["min"])
        self.assertIn("scaledDims", meta)
        self.assertLessEqual(meta["placedBBox"][3], meta["expandedFace"][1])

    def test_unplaceable_portrait_footprint_raises_typed_failure(self) -> None:
        tight = occ.build_map(
            (240.0, 400.0, 444.0, 444.0), set(), (1080, 1920),
            occ.OccupancyExtras(),
        )
        with self.assertRaises(occ.NoLegalRegion):
            self._resolve((0, 0, 1080, 1920), tight)

    def test_4k_landscape_solver_uses_delivery_space_end_to_end(self) -> None:
        fmap = occ.build_map(
            (1500.0, 600.0, 500.0, 500.0), set(), (3840, 2160),
            occ.OccupancyExtras(hair_top=520.0),
        )
        entry = _entry(anchor="headroom",
                       faceBBoxNorm=[0.39, 0.28, 0.13, 0.23])
        with mock.patch.object(fs, "build_free_map", return_value=fmap), \
             mock.patch.object(ga, "_content_bbox",
                               return_value=(300, 200, 900, 400)), \
             mock.patch.object(ga, "_clip_dims", return_value=(1920, 1080)):
            x, y, meta = ga.resolve_offset_v2(
                entry, "comp.mov", "base.mp4")
        self.assertEqual(meta["canvas"], [3840, 2160])
        self.assertEqual(meta["authoredCanvas"], [1920, 1080])
        self.assertEqual(meta["contentBBox"], [600.0, 400.0, 1800.0, 800.0])
        self.assertEqual(meta["scaledDims"], [3840, 2160])
        self.assertLessEqual(meta["placedBBox"][3], meta["expandedFace"][1])
        with mock.patch.object(dg, "_clip_dims", return_value=(1920, 1080)):
            fitted = dg.fit_delivery_geometry(
                "comp.mov", (x, y), meta, (3840, 2160))
        self.assertEqual(fitted[:2], (x, y))

    def test_sampler_grid_uses_decoded_landscape_dimensions(self) -> None:
        import numpy as np
        import cv2

        cap = mock.Mock()
        cap.isOpened.return_value = True
        cap.get.side_effect = lambda field: (
            384 if field == cv2.CAP_PROP_FRAME_WIDTH else 216)
        frame = np.zeros((216, 384, 3), dtype=np.uint8)
        with mock.patch.object(cv2, "VideoCapture", return_value=cap), \
             mock.patch("motion.face_track._load_cascade", return_value=object()), \
             mock.patch("motion.face_track._sample_times", return_value=[1.0]), \
             mock.patch("motion.face_track._read_at", return_value=frame), \
             mock.patch("motion.visual_state._largest_face", return_value=None), \
             mock.patch.object(fss, "busy_cells", return_value=set()) as busy:
            _frames, _face, _cells, canvas = fss.sample_window(
                "landscape.mp4", 0.0, 2.0)
        self.assertEqual(canvas, (384, 216))
        self.assertEqual(busy.call_args.args[1].canvas, (384, 216))

    def test_search_boundary_motion_is_not_claimed_as_measured_hair(self) -> None:
        import numpy as np

        frames = []
        for x in (12, 32, 52, 22, 42):
            frame = np.zeros((100, 100, 3), dtype=np.uint8)
            frame[1:30, x:x + 12] = 255
            frames.append(frame)
        self.assertIsNone(fss.measure_hair_top(frames, 50.0, 80.0))


class PlacementLintTests(unittest.TestCase):
    """plan_lint wiring + the _check_placement matrix (error/warn/clean)."""

    def _report(self, g: dict, mode: str = "short") -> "pl.Report":
        rep = pl.Report()
        plm._check_placement("graphicsTrack[0]", g, mode, rep)
        return rep

    def test_valid_short_placement_is_clean(self) -> None:
        rep = self._report(_entry(placement={"x": 200, "y": 400}))
        self.assertEqual((rep.errors, rep.warnings), ([], []))

    def test_no_placement_is_a_noop(self) -> None:
        rep = self._report(_entry())
        self.assertEqual((rep.errors, rep.warnings), ([], []))

    def test_non_dict_placement_errors(self) -> None:
        rep = self._report(_entry(placement=[60, 300]))
        self.assertTrue(any("object {x, y}" in e for e in rep.errors), rep.errors)

    def test_non_finite_and_missing_components_error(self) -> None:
        for bad in ({"x": 60}, {"x": float("nan"), "y": 1}, {"x": None, "y": 1},
                    {"x": "60", "y": 1}, {"x": True, "y": 1}):
            rep = self._report(_entry(placement=bad))
            self.assertTrue(any("finite number" in e for e in rep.errors),
                            f"{bad!r}: {rep.errors}")

    def test_off_canvas_placement_errors(self) -> None:
        for bad in ({"x": 2000, "y": 300}, {"x": -1, "y": 300},
                    {"x": 60, "y": 1920}, {"x": 60, "y": -5}):
            rep = self._report(_entry(placement=bad))
            self.assertTrue(any("outside the 1080x1920" in e for e in rep.errors),
                            f"{bad!r}: {rep.errors}")

    def test_longform_uses_its_own_canvas(self) -> None:
        ok = self._report(_entry(placement={"x": 1500, "y": 900}), mode="longform")
        self.assertEqual((ok.errors, ok.warnings), ([], []))
        bad = self._report(_entry(placement={"x": 1500, "y": 1500}), mode="longform")
        self.assertTrue(any("outside the 1920x1080" in e for e in bad.errors),
                        bad.errors)

    def test_own_screen_placement_errors(self) -> None:
        rep = self._report(_entry(anchor="own-screen",
                                  placement={"x": 60, "y": 300}))
        self.assertTrue(any("full-frame" in e for e in rep.errors), rep.errors)

    def test_shorts_safe_box_warns_and_names_the_edge(self) -> None:
        cases = (({"x": 10, "y": 400}, "left"), ({"x": 200, "y": 100}, "top"),
                 ({"x": 1000, "y": 400}, "right"), ({"x": 200, "y": 1500}, "bottom"))
        for placement, edge in cases:
            rep = self._report(_entry(placement=placement))
            self.assertEqual(rep.errors, [], f"{edge}: {rep.errors}")
            self.assertTrue(any(f"SAFE_BOX {edge} edge" in w for w in rep.warnings),
                            f"{edge}: {rep.warnings}")

    def test_safe_box_is_shorts_only(self) -> None:
        rep = self._report(_entry(placement={"x": 10, "y": 100}), mode="longform")
        self.assertEqual((rep.errors, rep.warnings), ([], []))

    def test_wired_into_full_plan_lint(self) -> None:
        plan = good_plan()
        plan["graphicsTrack"] = [_entry(placement={"x": 200, "y": 400})]
        self.assertEqual(pl.lint(plan, MANIFEST).errors, [])
        plan["graphicsTrack"] = [_entry(placement={"x": -1, "y": 400})]
        errors = pl.lint(plan, MANIFEST).errors
        self.assertTrue(any("outside the 1080x1920" in e for e in errors), errors)
        plan["graphicsTrack"] = [_entry(placement={"x": 200, "y": 100})]
        rep = pl.lint(plan, MANIFEST)
        self.assertEqual(rep.errors, [])
        self.assertTrue(any("SAFE_BOX top edge" in w for w in rep.warnings),
                        rep.warnings)


class RefitIgnoresPlacementTests(unittest.TestCase):
    """placement is SPATIAL: a cutTrack refit remaps TIME, never the pin."""

    def test_placement_survives_a_refit_shift(self) -> None:
        from edit.plan_refit import refit_plan

        pin = {"x": 120, "y": 380}
        old = {"cutTrack": [{"sourceId": "raw", "start": 10.0, "end": 50.0}],
               "target": {"mode": "longform"},
               "graphicsTrack": [_entry(outStart=25.0, outEnd=30.0,
                                        placement=dict(pin))]}
        new = {"cutTrack": [{"sourceId": "raw", "start": 10.0, "end": 25.0},
                            {"sourceId": "raw", "start": 30.0, "end": 50.0}],
               "target": {"mode": "longform"},
               "graphicsTrack": [_entry(outStart=25.0, outEnd=30.0,
                                        placement=dict(pin))]}
        plan, report = refit_plan(old, new)
        g = plan["graphicsTrack"][0]
        self.assertAlmostEqual(g["outStart"], 20.0, places=2)   # time remapped
        self.assertEqual(g["placement"], pin)                   # pin untouched
        self.assertTrue(any(r.get("remapped") for r in report), report)


if __name__ == "__main__":
    unittest.main(verbosity=2)
