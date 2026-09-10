"""Own-screen versus rail applicability; no media or whole-QC approval.

Pc8XlW placed nateherk-bullet-bars on the complete native canvas, as authored.
Its registered free-band geometry must not override that explicit presentation.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from audit.audit_checks import FAIL, PASS
from audit.audit_placements import check_eye_trace
from motion.recompose import requires_recompose
from planner.eye_trace import placement_row
from producer_config import MOTION


def _graphic(kind: str = "nateherk-bullet-bars") -> dict:
    """Actual failed row's identity and clock; TEST-only placement inputs."""
    return {"kind": kind, "anchor": "own-screen", "outStart": 13.546866666666666,
            "outEnd": 18.7187, "spec": {}}


def _row(graphic: dict) -> dict:
    """The ordinary placement writer's measured native full-canvas shape."""
    meta = {"region": "full-frame", "placedBBox": [0, 0, 1920, 1080]}
    return placement_row(graphic, meta, (1920, 1080))


def _check(graphic: dict, row: dict) -> list:
    """Invoke the real audit over isolated TEST sidecar bytes, not media."""
    plan = {"target": {"mode": "longform", "treatment": "produced"},
            "graphicsTrack": [graphic]}
    with tempfile.TemporaryDirectory() as temporary:
        Path(temporary, "graphics_placements.json").write_text(json.dumps([row]))
        return check_eye_trace(plan, temporary)


class PlacementApplicabilityTests(unittest.TestCase):
    def test_explicit_own_screen_overrides_registered_rail_geometry(self) -> None:
        for kind in MOTION["recompose"]["geometry"]:
            graphic = _graphic(kind)
            self.assertFalse(requires_recompose(graphic))
            result = _check(graphic, _row(graphic))
            self.assertEqual([(item.name, item.status) for item in result], [("eye_trace", PASS)])

    def test_own_screen_still_requires_exact_full_canvas_and_valid_measurements(self) -> None:
        graphic = _graphic()
        mutations = ({"placedBBox": [0, 0, 720, 1080]}, {"placedBBox": [1, 0, 1920, 1080]},
            {"placedBBox": None}, {"placedBBox": [0, 0, float("nan"), 1080]},
            {"canvas": None}, {"canvas": [3840, 2160]})
        for mutation in mutations:
            result = _check(graphic, {**_row(graphic), **mutation})
            self.assertEqual([item.status for item in result], [FAIL])

    def test_full_canvas_is_not_accepted_for_implicit_or_explicit_free_band_rail(self) -> None:
        for anchor in (None, "free-band", "beside-face"):
            graphic = _graphic()
            graphic.pop("anchor")
            if anchor is not None:
                graphic["anchor"] = anchor
            self.assertTrue(requires_recompose(graphic))
            result = _check(graphic, _row(graphic))
            self.assertEqual([item.status for item in result], [FAIL])
            self.assertIn("registered edge band", result[0].measured)

    def test_fixed_left_and_right_rail_band_checks_remain_active(self) -> None:
        for side, bbox in (("left", [1, 20, 600, 800]), ("right", [1320, 20, 1918, 800])):
            graphic = {**_graphic("glass-rail"), "anchor": "free-band", "spec": {"side": side}}
            good = {**_row(graphic), "placedBBox": bbox, "region": "fixed-canvas"}
            self.assertEqual([item.status for item in _check(graphic, good)], [PASS])
            escaped = {**good, "placedBBox": [0, 20, 1920, 800]}
            self.assertEqual([item.status for item in _check(graphic, escaped)], [FAIL])

    @unittest.skipUnless(os.environ.get("SNIPER_TEST_EYE_TRACE_RETAINED"), "explicit retained metadata path only")
    def test_actual_retained_plan_and_placements_without_rewriting_failed_report(self) -> None:
        directory = Path(os.environ["SNIPER_TEST_EYE_TRACE_RETAINED"])
        paths = [directory / name for name in ("edit_plan.json", "graphics_placements.json", "audit_report.json")]
        before = [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
        plan, placements, report = [json.loads(path.read_text()) for path in paths]
        self.assertEqual(len(plan["graphicsTrack"]), 8)
        self.assertEqual(plan["graphicsTrack"][1]["kind"], "nateherk-bullet-bars")
        self.assertEqual(placements[1]["placedBBox"], [0, 0, 1920, 1080])
        self.assertTrue(all(item["anchor"] == "own-screen" for item in plan["graphicsTrack"]))
        original_plan = copy.deepcopy(plan)
        self.assertEqual([(item.name, item.status) for item in check_eye_trace(plan, str(directory))],
                         [("eye_trace", PASS)])
        self.assertEqual(plan, original_plan)
        self.assertEqual(report["overall"], "fail")
        self.assertTrue(any(item["name"] == "eye_trace" and item["status"] == FAIL for item in report["checks"]))
        self.assertEqual([hashlib.sha256(path.read_bytes()).hexdigest() for path in paths], before)


if __name__ == "__main__":
    unittest.main()
