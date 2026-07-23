"""Fail-closed placement core (contract v3 item #3, render-time half).

The region-is-None branch of ``resolve_offset_v2`` raises a typed
``NoLegalRegion`` (the v1 seed nudge is gone); ``stage_placement.resolve_placement``
PROPAGATES geometry failures while environment failures keep the v1 fallback
but emit a loud WARN-severity NDJSON row declared through the gate-policy
vocabulary.
"""
import contextlib
import io
import json
import unittest
from unittest import mock

from _common import *  # noqa: F401,F403

import gate_policy
from graphics import stage_placement as sp
from planner import free_space as freespace
from planner import occupancy as occ
from planner.occupancy import NoLegalRegion


def _entry(**over) -> dict:
    base = {"outStart": 4.0, "outEnd": 6.0, "kind": "chip-row",
            "anchor": "headroom", "faceBBoxNorm": [0.14, 0.26, 0.6, 0.36],
            "spec": {"items": ["a"]}, "reason": "test"}
    base.update(over)
    return base


def _tight_map() -> "freespace.FreeMap":
    """A map whose bands cannot hold a 900x600 comp (tight mid-frame face)."""
    return occ.build_map((150.0, 500.0, 650.0, 700.0), set(), (1080, 1920),
                         occ.OccupancyExtras(hair_top=400.0))


class NoLegalRegionRaiseTests(unittest.TestCase):
    """resolve_offset_v2: nothing fits → typed raise, never the seed nudge."""

    def test_region_none_raises_typed_evidence(self) -> None:
        fmap = _tight_map()
        with mock.patch.object(freespace, "build_free_map",
                               return_value=fmap), \
             mock.patch.object(ga, "_content_bbox",
                               return_value=(60, 300, 960, 900)), \
             mock.patch.object(ga, "resolve_offset",
                               side_effect=AssertionError("seed nudge used")):
            with self.assertRaises(NoLegalRegion) as caught:
                ga.resolve_offset_v2(_entry(), "comp.mov", "base.mp4")
        exc = caught.exception
        self.assertTrue(str(exc).startswith("NoLegalRegion: "), str(exc))
        self.assertAlmostEqual(exc.evidence["faceWidthFrac"], 650 / 1080,
                               places=3)
        self.assertEqual(exc.evidence["contentDims"], [900, 600])
        self.assertEqual(exc.evidence["anchor"], "headroom")
        self.assertTrue(exc.evidence["regionsTried"])
        self.assertEqual(exc.evidence["window"], [4.0, 6.0])

    def test_fitting_region_still_places_normally(self) -> None:
        fmap = occ.build_map((400.0, 300.0, 280.0, 300.0), set(),
                             (1080, 1920), occ.OccupancyExtras(hair_top=250.0))
        with mock.patch.object(freespace, "build_free_map",
                               return_value=fmap), \
             mock.patch.object(ga, "_content_bbox",
                               return_value=(200, 855, 880, 1055)):
            x, y, meta = ga.resolve_offset_v2(_entry(), "comp.mov", "base.mp4")
        self.assertIsNotNone(meta["region"])
        self.assertNotEqual(meta["region"], "v1-deviation")


class PlacementFailClosedTests(unittest.TestCase):
    """stage_placement.resolve_placement: geometry propagates, environment is loud."""

    def test_no_legal_region_propagates(self) -> None:
        failure = NoLegalRegion({"anchor": "headroom", "contentDims": [900, 600]})
        with mock.patch.object(sp, "resolve_offset_v2", side_effect=failure), \
             mock.patch.object(sp, "resolve_offset",
                               side_effect=AssertionError("fallback used")):
            with self.assertRaises(NoLegalRegion):
                sp.resolve_placement(_entry(), "comp.mov", "base.mp4")

    def test_environment_failure_falls_back_with_loud_warn_row(self) -> None:
        buf = io.StringIO()
        with mock.patch.object(sp, "resolve_offset_v2",
                               side_effect=ImportError("No module named cv2")), \
             mock.patch.object(sp, "resolve_offset", return_value=(3, 4)), \
             contextlib.redirect_stdout(buf):
            x, y, meta = sp.resolve_placement(_entry(), "comp.mov", "base.mp4")
        self.assertEqual((x, y), (3, 4))
        self.assertEqual(meta["region"], "v1-fallback")
        rows = [json.loads(line) for line in buf.getvalue().splitlines()]
        fallback = [r for r in rows if r.get("status") == "placement_fallback"]
        self.assertEqual(len(fallback), 1)
        row = fallback[0]
        self.assertEqual(row["severity"], "WARN")
        self.assertEqual(row["gate"], "placement_environment")
        self.assertEqual(row["region"], "v1-fallback")
        self.assertEqual(row["lane"], "graphics")
        self.assertIn("cv2", row["evidence"])

    def test_environment_gate_is_registered_as_advisory(self) -> None:
        verdict = gate_policy.Verdict("placement_environment", "WARN",
                                      "v1-fallback: probe failed",
                                      lane="graphics")
        self.assertEqual(gate_policy.resolve(verdict, {"mode": "short"}),
                         "advise")


if __name__ == "__main__":
    unittest.main(verbosity=2)
