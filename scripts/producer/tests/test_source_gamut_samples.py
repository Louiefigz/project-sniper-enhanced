"""Independent scalar oracle for the measured vector shortcut; synthetic only."""
from __future__ import annotations

import math
import struct
import unittest
from unittest.mock import patch

import numpy as np

from color.source_gamut_samples import PlanarSamples, _accumulate, empty_channels

_BITS = (0, 0x80000000, 1, 0x80000001, 0x3f000000, 0x3f800000, 0x3f800001,
         0x7f7fffff, 0xff7fffff, 0x7f800000, 0xff800000, 0x7fc00001)


def scalar_channel(values: tuple[float, ...]) -> dict:
    """Classify original decoded float32 test values without any NumPy operation."""
    finite = [value for value in values if math.isfinite(value)]
    low, high = (min(finite), max(finite)) if finite else (None, None)
    return {"finiteCount": len(finite), "nanCount": sum(math.isnan(value) for value in values),
            "positiveInfinityCount": values.count(math.inf),
            "negativeInfinityCount": values.count(-math.inf),
            "belowZeroCount": sum(value < 0 for value in finite),
            "aboveOneCount": sum(value > 1 for value in finite),
            "minimum": 0.0 if low == 0 else low, "maximum": 0.0 if high == 0 else high}


class SourceGamutSamplesTests(unittest.TestCase):
    """Skipping redundant scans requires actual complete finite-mask evidence."""

    def test_mixed_planar_partitions_match_independent_scalar_oracle(self) -> None:
        """Mixed NaN/Inf/subnormal/endpoint bytes still count exactly in GBR order."""
        bits = _BITS + tuple(reversed(_BITS)) + _BITS[4:] + _BITS[:4]
        payload = struct.pack("<36I", *bits)
        values = struct.unpack("<36f", payload)
        expected = {key: scalar_channel(values[index * 12:(index + 1) * 12])
                    for index, key in enumerate(("g", "b", "r"))}
        for size in (1, 3, 4, 7, 16, 48, 65, len(payload)):
            channels = empty_channels()
            scanner = PlanarSamples(12, channels)
            for offset in range(0, len(payload), size):
                scanner.push(payload[offset:offset + size])
            scanner.finish()
            self.assertEqual(channels, expected)

    def test_all_finite_block_skips_only_redundant_nonfinite_scans(self) -> None:
        """Finite values outside unit range still need ordinary outlier accounting."""
        values = np.array([-2.0, -0.0, 0.0, 0.25, 1.0, 2.0], dtype="<f4")
        row = empty_channels()["g"]
        with patch.object(np, "isnan", side_effect=AssertionError("redundant NaN pass")), \
                patch.object(np, "isposinf", side_effect=AssertionError("redundant +Inf pass")), \
                patch.object(np, "isneginf", side_effect=AssertionError("redundant -Inf pass")):
            _accumulate(row, values)
        self.assertEqual(row, scalar_channel(tuple(map(float, values))))

    def test_finite_shortcut_never_erases_previous_nonfinite_observations(self) -> None:
        """Counters accumulate across mixed and all-finite chunks without resets."""
        values = (math.nan, math.inf, -math.inf, -0.0, 0.5, 1.0, 2.0)
        row = empty_channels()["r"]
        _accumulate(row, np.array(values[:3], dtype="<f4"))
        _accumulate(row, np.array(values[3:], dtype="<f4"))
        self.assertEqual(row, scalar_channel(values))
