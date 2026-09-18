"""Covered-clock TEST geometry only; no rendered or creative evidence."""
from __future__ import annotations

import copy
import unittest

from guided_caption_layout_v2 import inspect_covered_layout
from test_guided_caption_layout import fixture, observation


def covered() -> dict:
    """Preserve the full 9325-frame clock and a nonzero original graphic order."""
    value = fixture()
    value.update(schemaVersion=2, coverage={"startFrame": 0, "endFrameExclusive": 750})
    value["graphics"][0]["order"] = 2
    return value


def inspect(value: dict, observed: tuple | None = None) -> dict:
    """Read explicitly fake geometry through the pure boundary."""
    return inspect_covered_layout(value, lambda *_: observed, lambda: None)


class CoveredLayoutTests(unittest.TestCase):
    def test_opening_retains_full_cue_and_animation_with_original_order(self) -> None:
        value = covered()
        before = copy.deepcopy(value)
        result = inspect(value, observation(value))
        self.assertEqual(result["state"], "screened-no-overlap")
        self.assertEqual(result["clock"]["totalFrames"], 9325)
        self.assertEqual(result["coverage"]["endFrameExclusive"], 750)
        self.assertEqual(result["graphics"][0]["order"], 2)
        self.assertEqual(result["graphics"][0]["intersections"][0]["endFrameExclusive"], 750)
        self.assertEqual(value, before)
        self.assertFalse(result["qcPassed"] or result["creativeApproved"] or result["deliveryApproved"])

    def test_body_uses_full_coverage_not_opening_relabel(self) -> None:
        value = covered()
        first = inspect(value, observation(value))
        value["coverage"]["endFrameExclusive"] = 9325
        final = inspect(value, observation(value))
        self.assertNotEqual(first["inputHash"], final["inputHash"])
        self.assertEqual(final["graphics"][0]["intersections"][0]["endFrameExclusive"], 793)

    def test_exact_endpoint_gap_does_not_require_observation(self) -> None:
        value = covered()
        value["cues"][0].update(startFrame=750, endFrameExclusive=866)
        value["declarations"] = []
        result = inspect_covered_layout(value, lambda *_: self.fail("genuine gap"), lambda: None)
        self.assertEqual(result["state"], "not-applicable")

    def test_no_graphics_still_binds_full_caption_projection(self) -> None:
        value = covered()
        value["graphics"], value["declarations"] = [], []
        result = inspect(value)
        self.assertEqual(result["graphics"], [])
        self.assertEqual(result["state"], "not-applicable")
        value["captionProjectionHash"] = None
        with self.assertRaises(ValueError):
            inspect(value)

    def test_known_footline_collision_and_missing_observation_never_pass(self) -> None:
        value = covered()
        self.assertEqual(inspect(value)["state"], "unqualified")
        actual_shaped = observation(value, [[100, 100, 900, 300], [300, 700, 900, 755]])
        self.assertEqual(inspect(value, actual_shaped)["state"], "envelope-conflict")

    def test_wrong_local_frame_count_or_clock_never_pass(self) -> None:
        value = covered()
        for field, replacement in (("framesObserved", 68), ("endFrameExclusive", 750)):
            returned = observation(value)
            returned[1][field] = replacement
            self.assertEqual(inspect(value, returned)["state"], "unqualified")
        returned = observation(value)
        returned[1]["binding"]["frameRate"] = "30/1"
        self.assertEqual(inspect(value, returned)["state"], "unqualified")

    def test_noncontiguous_orders_allowed_but_reordering_and_duplicate_reject(self) -> None:
        value = covered()
        row = copy.deepcopy(value["graphics"][0])
        row.update(graphicId="TEST-other", order=7, startFrame=700, endFrameExclusive=740)
        row["binding"]["graphicId"] = "TEST-other"
        value["graphics"].append(row)
        value["cues"], value["declarations"] = [], []
        self.assertEqual([row["order"] for row in inspect(value)["graphics"]], [2, 7])
        value["graphics"].reverse()
        with self.assertRaises(ValueError):
            inspect(value)
        value["graphics"][0]["order"] = 2
        with self.assertRaises(ValueError):
            inspect(value)

    def test_malformed_coverage_and_outside_occurrence_reject(self) -> None:
        for coverage in ({"startFrame": True, "endFrameExclusive": 750},
                         {"startFrame": 0, "endFrameExclusive": 0},
                         {"startFrame": 0, "endFrameExclusive": 9326},
                         {"startFrame": 793, "endFrameExclusive": 900}):
            value = covered()
            value["coverage"] = coverage
            with self.assertRaises(ValueError):
                inspect(value)

    def test_final_observation_or_input_mutation_rejects(self) -> None:
        value, calls = covered(), []
        def changed(*_args: object) -> tuple:
            result = observation(value)
            if calls:
                result[1]["roles"][0]["bounds"][0] += 1
            calls.append(True)
            return result
        self.assertEqual(inspect_covered_layout(value, changed, lambda: None)["state"], "unqualified")
        def expired() -> None:
            raise RuntimeError("original deadline")
        with self.assertRaises(RuntimeError):
            inspect_covered_layout(value, changed, expired)
