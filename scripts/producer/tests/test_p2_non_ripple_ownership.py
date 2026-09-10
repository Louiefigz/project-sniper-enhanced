"""Ambiguous output-ownership guard for P2 non-ripple repair."""
from __future__ import annotations

import unittest

from edit.exact_timing import FrameRange, PositiveRational, SampleRange
from edit.non_ripple import enumerate_non_ripple
from edit.non_ripple_contracts import CompiledCutSegment, RepairContext
from tests.test_p2_non_ripple import _context


class NonRippleOwnershipTests(unittest.TestCase):
    def test_duplicate_output_owners_fail_instead_of_claiming_complete(
            self) -> None:
        context = _context(180)
        segments = tuple(
            CompiledCutSegment(
                f"complete-{index}", 1, "raw", 48_000,
                SampleRange(40_000, 60_000), frames,
                PositiveRational(1, 1))
            for index, frames in enumerate((
                FrameRange(100, 120), FrameRange(200, 220)))
        )
        result = enumerate_non_ripple(RepairContext(**{
            **context.__dict__,
            "segments": segments,
            "silences": (),
        }))
        self.assertEqual(result.status, "NON_RIPPLE_IMPOSSIBLE")
        self.assertEqual(
            result.ripple_impact["blockingReason"],
            "TARGET_HAS_MULTIPLE_OUTPUT_OWNERS")


if __name__ == "__main__":
    unittest.main(verbosity=2)
