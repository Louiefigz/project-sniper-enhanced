"""Adversarial tests for bounded Palmier keyframe readback."""
import unittest

from _common import *  # noqa: F401,F403
from palmier.keyframe_readback import compare_keyframe_rows, keyframe_map
from palmier.mcp_client import PalmierError


EXPECTED = [
    [0, 1.2345, -0.0864, "smooth"],
    [12, 1.2004, 0.0101, "smooth"],
]


class KeyframeRowComparisonTests(unittest.TestCase):
    def assert_rejected(self, found, pattern):
        with self.assertRaisesRegex(PalmierError, pattern):
            compare_keyframe_rows(found, EXPECTED)

    def test_exact_quantization_boundary_and_easing_omission_pass(self):
        found = [[0, 1.235, -0.086], [12, 1.2, 0.01]]
        evidence = compare_keyframe_rows(found, EXPECTED).as_dict()
        self.assertEqual(evidence, {
            "easing": "not_exposed",
            "numericQuantization": {
                "decimalPlaces": 3,
                "allowedMaxAbsDifference": 0.0005,
                "observedMaxAbsDifference": 0.0005,
                "status": "within_bound",
            },
        })

    def test_difference_beyond_boundary_fails(self):
        self.assert_rejected(
            [[0, 1.235001, -0.0864], [12, 1.2004, 0.0101]],
            "exceeds Palmier's 3-decimal quantization bound")

    def test_row_count_and_frame_order_drift_fail(self):
        self.assert_rejected([[0, 1.2345, -0.0864]], "row count differs")
        self.assert_rejected(
            [[12, 1.2004, 0.0101], [0, 1.2345, -0.0864]],
            "frame differs")

    def test_missing_or_extra_value_columns_fail(self):
        self.assert_rejected(
            [[0, 1.2345], [12, 1.2004, 0.0101]],
            "value column count differs")
        self.assert_rejected(
            [[0, 1.2345, -0.0864, 9.0], [12, 1.2004, 0.0101, 9.0]],
            "value column count differs")

    def test_boolean_nan_and_infinity_fail(self):
        invalid = [
            [[False, 1.2345, -0.0864], [12, 1.2004, 0.0101]],
            [[0, True, -0.0864], [12, 1.2004, 0.0101]],
            [[0, float("nan"), -0.0864], [12, 1.2004, 0.0101]],
            [[0, float("inf"), -0.0864], [12, 1.2004, 0.0101]],
            [[0, float("-inf"), -0.0864], [12, 1.2004, 0.0101]],
        ]
        for rows in invalid:
            with self.subTest(rows=rows):
                self.assert_rejected(rows, "not numeric|not finite")

    def test_unexpected_or_changed_easing_fails(self):
        without_easing = [[0, 1.0], [12, 1.1]]
        with self.assertRaisesRegex(PalmierError, "unexpected easing"):
            compare_keyframe_rows(
                [[0, 1.0, "smooth"], [12, 1.1, "smooth"]],
                without_easing)
        self.assert_rejected([
            [0, 1.2345, -0.0864, "linear"],
            [12, 1.2004, 0.0101, "linear"],
        ], "easing .* does not match")

    def test_inconsistent_easing_exposure_fails(self):
        self.assert_rejected([
            [0, 1.2345, -0.0864],
            [12, 1.2004, 0.0101, "smooth"],
        ], "inconsistent easing exposure")


class KeyframeMapTests(unittest.TestCase):
    def test_duplicate_property_fails(self):
        clip = {"keyframes": [
            {"property": "scale", "rows": [[0, 1.0]]},
            {"property": "scale", "rows": [[12, 1.1]]},
        ]}
        with self.assertRaisesRegex(PalmierError, "duplicate keyframe property"):
            keyframe_map(clip)

    def test_malformed_property_rows_fail(self):
        with self.assertRaisesRegex(PalmierError, "malformed keyframe rows"):
            keyframe_map({"keyframes": {"scale": "not-rows"}})


if __name__ == "__main__":
    unittest.main()
