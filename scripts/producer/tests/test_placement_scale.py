"""placement.scale contract tests (uniform resize about the placement pin).

Covers the four legs of the CONTRACT:
  * SCALE MATH — stage_placement.scale_geometry: even output dims, effective
    per-axis factors, the SCALED content bbox top-left pinned at {x, y}.
  * RENDERER — _explicit_offset routes scale into offsets + scaledDims meta;
    _build_graph inserts the lanczos scale filter for scaled clips only.
  * ABSENT = 1.0 BYTE-IDENTICAL — no scale key (or scale: 1.0) probes no dims,
    returns the pre-scale offsets, and emits the byte-identical filter graph.
  * LINT MATRIX — plan_lint_motion: bounds error outside PLACEMENT_SCALE,
    type errors, SAFE_BOX warn against the SCALED content box.
"""
import math
import unittest
from unittest import mock

from _common import *  # noqa: F401,F403

from graphics import graphics_stage as gs
from graphics import stage_placement as sp
from producer_config import PLACEMENT_SCALE

# A synthetic rendered-content footprint (x0, y0, x1, y1) on the comp canvas.
_CONTENT = (200, 855, 880, 1055)
_DIMS = (1080, 1920)


def _entry(**over) -> dict:
    base = {"outStart": 4.0, "outEnd": 6.0, "kind": "stat-card",
            "anchor": "free-band",
            "spec": {"value": "TEST", "label": "PLACEMENT"},
            "reason": "test"}
    base.update(over)
    return base


class ScaleGeometryTests(unittest.TestCase):
    """scale_geometry — the exported pure math."""

    def test_even_dims_and_pin(self) -> None:
        geo = sp.scale_geometry(_CONTENT, (60, 300), _DIMS, 1.3)
        self.assertEqual((geo["w"], geo["h"]), (1404, 2496))     # 1.3x, even
        self.assertEqual(geo["placed"][:2], (60, 300))           # pin holds
        cw, ch = _CONTENT[2] - _CONTENT[0], _CONTENT[3] - _CONTENT[1]
        self.assertAlmostEqual(geo["placed"][2] - 60, cw * 1.3, delta=1)
        self.assertAlmostEqual(geo["placed"][3] - 300, ch * 1.3, delta=1)

    def test_odd_products_round_to_even(self) -> None:
        for scale in (0.33, 0.5, 0.77, 1.01, 1.49):
            geo = sp.scale_geometry(_CONTENT, (0, 0), _DIMS, scale)
            self.assertEqual(geo["w"] % 2, 0, f"scale {scale}: w {geo['w']}")
            self.assertEqual(geo["h"] % 2, 0, f"scale {scale}: h {geo['h']}")
            self.assertAlmostEqual(geo["w"], _DIMS[0] * scale, delta=1)
            self.assertAlmostEqual(geo["h"], _DIMS[1] * scale, delta=1)

    def test_pin_uses_effective_factors(self) -> None:
        # 0.33 rounds the canvas to 356x634 — sx != sy != 0.33; the pin must
        # still land exactly (the bbox terms use the EFFECTIVE factors).
        geo = sp.scale_geometry(_CONTENT, (100, 500), _DIMS, 0.33)
        self.assertEqual(geo["placed"][:2], (100, 500))

    def test_wide_canvas(self) -> None:
        geo = sp.scale_geometry((300, 200, 900, 500), (60, 300),
                                (1920, 1080), 1.5)
        self.assertEqual((geo["w"], geo["h"]), (2880, 1620))
        self.assertEqual(geo["placed"], (60, 300, 60 + 900, 300 + 450))


class ScaleValidationTests(unittest.TestCase):
    """_placement_scale — fail loud, never clamp."""

    def test_absent_is_one(self) -> None:
        self.assertEqual(sp._placement_scale(_entry(placement={"x": 1, "y": 2})), 1.0)

    def test_band_edges_accepted(self) -> None:
        for ok in (PLACEMENT_SCALE["min"], 0.5, 1.0, 1.3, PLACEMENT_SCALE["max"]):
            e = _entry(placement={"x": 1, "y": 2, "scale": ok})
            self.assertEqual(sp._placement_scale(e), float(ok))

    def test_out_of_band_raises(self) -> None:
        for bad in (0.24, 0.0, -1.0, 1.51, 5.0):
            e = _entry(placement={"x": 1, "y": 2, "scale": bad})
            with self.assertRaisesRegex(ValueError, "outside"):
                sp._placement_scale(e)

    def test_non_numbers_raise(self) -> None:
        for bad in ("1.3", True, float("nan"), float("inf"), [1.3]):
            e = _entry(placement={"x": 1, "y": 2, "scale": bad})
            with self.assertRaises(ValueError, msg=f"accepted {bad!r}"):
                sp._placement_scale(e)


class ScaledOffsetTests(unittest.TestCase):
    """_explicit_offset with scale — offsets pin the SCALED bbox; meta carries it."""

    def test_scaled_offset_and_meta(self) -> None:
        entry = _entry(placement={"x": 60, "y": 300, "scale": 1.3})
        with mock.patch.object(sp, "_content_bbox", return_value=_CONTENT), \
             mock.patch.object(sp, "_clip_dims", return_value=_DIMS):
            x, y, meta = sp.resolve_placement(entry, "fake.mov", "base.mp4")
        self.assertEqual(meta["scale"], 1.3)
        self.assertEqual(meta["scaledDims"], [1404, 2496])
        self.assertEqual(meta["placedBBox"][:2], [60, 300])
        self.assertEqual((x, y), (60 - round(_CONTENT[0] * 1.3),
                                  300 - round(_CONTENT[1] * 1.3)))

    def test_absent_scale_probes_no_dims_and_matches_prescale(self) -> None:
        entry = _entry(placement={"x": 60, "y": 300})
        with mock.patch.object(sp, "_content_bbox", return_value=_CONTENT), \
             mock.patch.object(sp, "_clip_dims",
                               side_effect=AssertionError("dims probed")):
            x, y, meta = sp.resolve_placement(entry, "fake.mov", "base.mp4")
        self.assertEqual((x, y), (60 - _CONTENT[0], 300 - _CONTENT[1]))
        self.assertNotIn("scale", meta)
        self.assertNotIn("scaledDims", meta)

    def test_explicit_one_is_the_absent_path(self) -> None:
        entry = _entry(placement={"x": 60, "y": 300, "scale": 1.0})
        with mock.patch.object(sp, "_content_bbox", return_value=_CONTENT), \
             mock.patch.object(sp, "_clip_dims",
                               side_effect=AssertionError("dims probed")):
            x, y, meta = sp.resolve_placement(entry, "fake.mov", "base.mp4")
        self.assertEqual((x, y), (60 - _CONTENT[0], 300 - _CONTENT[1]))
        self.assertNotIn("scaledDims", meta)


class ScaledGraphTests(unittest.TestCase):
    """_build_graph — scale filter for scaled clips; absent = byte-identical."""

    def test_scaled_clip_gets_lanczos_scale(self) -> None:
        clips = [{"path": "c.mov", "outStart": 2.0, "outEnd": 4.0,
                  "anchor": "free-band", "x": -200, "y": -812,
                  "scaleDims": [1404, 2496]}]
        graph, _ = gs._build_graph(clips)
        self.assertIn("[1:v]scale=1404:2496:flags=lanczos,"
                      "setpts=PTS-STARTPTS+2.0000/TB[ov0]", graph)

    def test_absent_scale_graph_is_byte_identical(self) -> None:
        clips = [{"path": "c.mov", "outStart": 2.0, "outEnd": 4.0,
                  "anchor": "free-band", "x": 0, "y": 0}]
        graph, final = gs._build_graph(clips)
        self.assertEqual(graph,
                         "[1:v]setpts=PTS-STARTPTS+2.0000/TB[ov0];"
                         "[0:v][ov0]overlay=enable='between(t,2.0000,4.0000)'"
                         ":format=auto[gc0]")
        self.assertEqual(final, "[gc0]")


class ScaleLintTests(unittest.TestCase):
    """plan_lint_motion — scale bounds + the SCALED-box SAFE_BOX warn."""

    def _report(self, g: dict, mode: str = "short") -> "pl.Report":
        rep = pl.Report()
        plm._check_placement("graphicsTrack[0]", g, mode, rep)
        return rep

    def test_valid_scale_is_clean(self) -> None:
        rep = self._report(_entry(placement={"x": 200, "y": 400, "scale": 1.3}))
        self.assertEqual((rep.errors, rep.warnings), ([], []))

    def test_out_of_band_scale_errors(self) -> None:
        for bad in (0.2, 1.6, 0.0, -1):
            rep = self._report(_entry(placement={"x": 200, "y": 400, "scale": bad}))
            self.assertTrue(any("placement.scale" in e and "outside" in e
                                for e in rep.errors), f"{bad!r}: {rep.errors}")

    def test_non_number_scale_errors(self) -> None:
        for bad in ("1.3", True, float("nan")):
            rep = self._report(_entry(placement={"x": 200, "y": 400, "scale": bad}))
            self.assertTrue(any("finite number" in e for e in rep.errors),
                            f"{bad!r}: {rep.errors}")

    def test_safe_box_uses_the_scaled_content_box(self) -> None:
        # contentBBox 400x300; pin (500, 400): unscaled right edge = 900 ≤ 930
        # (clean); at 1.2x the box reaches 980 > 930 → the RIGHT warn fires
        # even though the pin itself never moved.
        g = dict(_entry(placement={"x": 500, "y": 400}),
                 contentBBox=[0, 0, 400, 300])
        self.assertEqual(self._report(g).warnings, [])
        g_scaled = dict(g, placement={"x": 500, "y": 400, "scale": 1.2})
        warns = self._report(g_scaled).warnings
        self.assertTrue(any("SAFE_BOX right edge" in w for w in warns), warns)

    def test_scaled_box_bottom_edge(self) -> None:
        g = dict(_entry(placement={"x": 200, "y": 1200, "scale": 1.5}),
                 contentBBox=[0, 0, 400, 300])   # 300*1.5=450 → 1650 > 1400
        warns = self._report(g).warnings
        self.assertTrue(any("SAFE_BOX bottom edge" in w for w in warns), warns)
        shrunk = dict(g, placement={"x": 200, "y": 1200, "scale": 0.5})
        self.assertEqual(self._report(shrunk).warnings, [])   # 1350 ≤ 1400

    def test_no_content_box_degenerates_to_the_point(self) -> None:
        rep = self._report(_entry(placement={"x": 200, "y": 400, "scale": 1.5}))
        self.assertEqual((rep.errors, rep.warnings), ([], []))

    def test_safe_box_scale_check_is_shorts_only(self) -> None:
        g = dict(_entry(placement={"x": 1500, "y": 900, "scale": 1.5}),
                 contentBBox=[0, 0, 800, 600])
        rep = self._report(g, mode="longform")
        self.assertEqual((rep.errors, rep.warnings), ([], []))

    def test_wired_into_full_plan_lint(self) -> None:
        plan = good_plan()
        plan["graphicsTrack"] = [_entry(placement={"x": 200, "y": 400,
                                                   "scale": 2.0})]
        errors = pl.lint(plan, MANIFEST).errors
        self.assertTrue(any("placement.scale" in e for e in errors), errors)
        plan["graphicsTrack"] = [_entry(placement={"x": 200, "y": 400,
                                                   "scale": 1.4})]
        self.assertEqual(pl.lint(plan, MANIFEST).errors, [])


class RefitIgnoresScaleTests(unittest.TestCase):
    """scale rides placement — SPATIAL; a cutTrack refit remaps TIME only."""

    def test_scaled_placement_survives_a_refit_shift(self) -> None:
        from edit.plan_refit import refit_plan

        pin = {"x": 120, "y": 380, "scale": 1.25}
        old = {"cutTrack": [{"sourceId": "raw", "start": 10.0, "end": 50.0}],
               "target": {"mode": "longform"},
               "graphicsTrack": [_entry(outStart=25.0, outEnd=30.0,
                                        placement=dict(pin))]}
        new = {"cutTrack": [{"sourceId": "raw", "start": 10.0, "end": 25.0},
                            {"sourceId": "raw", "start": 30.0, "end": 50.0}],
               "target": {"mode": "longform"},
               "graphicsTrack": [_entry(outStart=25.0, outEnd=30.0,
                                        placement=dict(pin))]}
        plan, _report = refit_plan(old, new)
        self.assertEqual(plan["graphicsTrack"][0]["placement"], pin)


if __name__ == "__main__":
    unittest.main(verbosity=2)
