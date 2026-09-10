"""Cross-runtime canonical JSON and plan-hash numeric-domain regressions."""
from __future__ import annotations

import unittest

from cross_runtime_canonical_json import (
    CrossRuntimeCanonicalJsonError,
    canonical_compact_json,
    canonical_json,
)
from fingerprints import plan_content_hash


class CrossRuntimeCanonicalJsonTests(unittest.TestCase):
    """Match ECMAScript formatting without accepting lossy integers."""

    def test_ecmascript_number_thresholds(self) -> None:
        values = {
            "tiny": 1e-7,
            "fixedFloor": 1e-6,
            "ordinary": 0.00001234,
            "negative": -2.5,
            "minimumSubnormal": 5e-324,
        }
        self.assertEqual(
            canonical_json(values),
            '{"fixedFloor": 0.000001, "minimumSubnormal": 5e-324, '
            '"negative": -2.5, "ordinary": 0.00001234, "tiny": 1e-7}',
        )

    def test_utf16_key_order_and_lone_surrogate(self) -> None:
        value = {"\ue000": "bmp", "😀": "astral", "lone": "\ud800"}
        self.assertEqual(
            canonical_json(value),
            '{"lone": "\\ud800", "😀": "astral", "\ue000": "bmp"}',
        )

    def test_negative_zero_and_integral_float_collapse(self) -> None:
        self.assertEqual(canonical_json([-0.0, 30.0, 30]), "[0, 30, 30]")
        self.assertEqual(
            canonical_compact_json({"tiny": 1e-7, "zero": -0.0}),
            '{"tiny":1e-7,"zero":0}',
        )

    def test_nonfinite_and_unsafe_integer_fail_closed(self) -> None:
        values = (
            float("nan"), float("inf"), 9_007_199_254_740_992,
            float(9_007_199_254_740_992),
        )
        for value in values:
            with self.subTest(value=value):
                with self.assertRaises(CrossRuntimeCanonicalJsonError):
                    canonical_json({"value": value})

    def test_plan_hash_uses_cross_runtime_numbers(self) -> None:
        self.assertEqual(
            plan_content_hash({"x": 1e-7}),
            "4edc61b9f1a875cc21382a6e2224f7ca85f7d32e1747caf5071276ce760035c1",
        )


if __name__ == "__main__":
    unittest.main()
