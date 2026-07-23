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
import unittest
from unittest import mock

from _common import *  # noqa: F401,F403

from graphics import delivery_geometry as dg
from graphics import graphics_stage as gs
from graphics import stage_placement as sp

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
