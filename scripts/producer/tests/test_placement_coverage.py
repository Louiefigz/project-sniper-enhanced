"""Adversarial coverage tests for partially occluded face-aware graphics."""
from __future__ import annotations

import copy
import unittest
from unittest import mock

from _common import *  # noqa: F401,F403
from graphics import placement_verify as pv
from planner import verified_frame_sampling


def _clip(**changes: object) -> dict:
    """Create one automatic face-aware graphic with a ten-second hold."""
    clip = {"path": "card.mov", "outStart": 4.0, "outEnd": 14.0,
            "anchor": "headroom", "placedBBox": [100, 100, 300, 200]}
    return {**clip, **changes}


class PlacementCoverageTests(unittest.TestCase):
    """Every uncovered span is checked, even after another span fails/skips."""

    def setUp(self) -> None:
        """Use an explicit 30 fps index for pure mocked geometry tests."""
        patcher = mock.patch.object(verified_frame_sampling, "frame_timestamps",
                                    return_value=tuple(i / 30 for i in range(601)))
        self.addCleanup(patcher.stop)
        patcher.start()

    def _verify(self, windows: dict, **changes: object) -> tuple:
        """Run a successful mocked probe and return its spans and evidence."""
        rows: list[dict] = []
        ctx = pv.VerifyContext("FAIL", windows,
                               emit=lambda **fields: rows.append(fields))
        with mock.patch.object(pv, "verify_placement",
                               return_value=(True, {"ok": True})) as probe:
            count = pv.run_verify([_clip(**changes)], "final.mp4", ctx)
        self.assertEqual(count, 1)
        return [call.args[1:3] for call in probe.call_args_list], rows

    def test_partial_middle_occlusion_checks_both_remaining_spans(self) -> None:
        spans, rows = self._verify({"broll": [[8.0, 9.0]]})
        self.assertEqual(spans, [(4.0, 8.0), (9.0, 14.0)])
        self.assertEqual([(r["outStart"], r["outEnd"]) for r in rows
                          if r["status"] == "placement_verified"], spans)
        skips = [r for r in rows if r["status"] == "placement_verify_skip"]
        self.assertEqual([(r["outStart"], r["outEnd"]) for r in skips],
                         [(8.0, 9.0)])

    def test_interval_union_and_boundary_cases(self) -> None:
        cases = [
            ({}, [(4.0, 14.0)]),
            ({"broll": [[13, 15]]}, [(4.0, 13.0)]),
            ({"cards": [[3, 5]]}, [(5.0, 14.0)]),
            ({"broll": [[2, 4], [14, 18]]}, [(4.0, 14.0)]),
            ({"broll": [[3, 15]]}, []),
            ({"broll": [[9, 14], [8, 10], [8, 10]]}, [(4.0, 8.0)]),
            ({"broll": [[4, 9]], "cards": [[9, 14]]}, []),
            ({"broll": [[5, 6]], "cards": [[10, 12]]},
             [(4.0, 5.0), (6.0, 10.0), (12.0, 14.0)]),
            ({"broll": [[4, 8], [8 + 1 / 30, 14]]},
             []),
        ]
        for windows, expected in cases:
            with self.subTest(windows=windows):
                spans, _rows = self._verify(windows)
                self.assertEqual(spans, expected)

    def test_second_span_collision_still_blocks(self) -> None:
        self._mixed_outcomes((True, {"ok": True}))

    def test_first_span_environment_error_does_not_hide_later_collision(self) -> None:
        self._mixed_outcomes(ImportError("cv2 unavailable for this probe"))

    def _mixed_outcomes(self, first: object) -> None:
        """Ensure one result never terminates checks for remaining intervals."""
        ctx = pv.VerifyContext("FAIL", {"broll": [[8, 9]]})
        outcomes = [first, (False, {"ok": False, "intersection": 20})]
        with mock.patch.object(pv, "verify_placement", side_effect=outcomes) as probe:
            with self.assertRaisesRegex(RuntimeError, "NoLegalRegion"):
                pv.run_verify([_clip()], "final.mp4", ctx)
        self.assertEqual(probe.call_count, 2)

    def test_first_span_collision_does_not_skip_later_probe(self) -> None:
        ctx = pv.VerifyContext("FAIL", {"broll": [[8, 9]]})
        results = [(False, {"ok": False}), (True, {"ok": True})]
        with mock.patch.object(pv, "verify_placement", side_effect=results) as probe:
            with self.assertRaisesRegex(RuntimeError, "NoLegalRegion"):
                pv.run_verify([_clip()], "final.mp4", ctx)
        self.assertEqual(probe.call_count, 2)

    def test_invalid_windows_never_become_environment_skips(self) -> None:
        invalid = [[8, 8], [9, 8], [-1, 9], [True, 9], ["8", 9],
                   [8, float("nan")], [float("-inf"), 9], [8, float("inf")],
                   [8], None, {"start": 8, "end": 9}]
        for window in invalid:
            with self.subTest(window=window):
                ctx = pv.VerifyContext("FAIL", {"broll": [window]})
                with mock.patch.object(pv, "verify_placement") as probe:
                    with self.assertRaises(ValueError):
                        pv.run_verify([_clip()], "final.mp4", ctx)
                probe.assert_not_called()

    def test_invalid_clip_bounds_fail_before_measurement(self) -> None:
        for changes in ({"outEnd": 4}, {"outStart": -1},
                        {"outEnd": float("nan")}, {"outStart": True}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    self._verify({}, **changes)

    def test_inputs_are_unchanged(self) -> None:
        windows = {"broll": [[9, 14], [4, 7]], "cards": [[6, 10]]}
        before = copy.deepcopy(windows)
        self._verify(windows)
        self.assertEqual(windows, before)

    def test_bbox_is_resolved_once_for_all_uncovered_spans(self) -> None:
        with mock.patch.object(pv, "_placed_bbox", return_value=(1, 2, 3, 4)) as bbox:
            self._verify({"broll": [[8, 9]]})
        bbox.assert_called_once()

    def test_operator_pin_and_uncalibrated_hits_stay_warn(self) -> None:
        for severity, placed in (("WARN", False), ("FAIL", True)):
            rows: list[dict] = []
            ctx = pv.VerifyContext(severity, {"broll": [[8, 9]]},
                                   emit=lambda **fields: rows.append(fields))
            with mock.patch.object(pv, "verify_placement",
                                   return_value=(False, {"ok": False})) as probe:
                pv.run_verify([_clip(placed=placed)], "final.mp4", ctx)
            self.assertEqual(probe.call_count, 2)
            hits = [r for r in rows if r["status"] == "placement_verify_hit"]
            self.assertEqual([r["severity"] for r in hits], ["WARN", "WARN"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
