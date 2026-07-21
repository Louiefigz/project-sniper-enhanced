"""Timing receipt completeness and failure regressions."""
from __future__ import annotations

import unittest

from _common import pl  # noqa: F401
from headless.quality_timing import (
    REQUIRED_STAGES,
    QualityTimingError,
    TimingRecorder,
)


class _Clock:
    def __init__(self, values: list[int]):
        self._values = iter(values)

    def __call__(self) -> int:
        return next(self._values)


class QualityTimingTests(unittest.TestCase):
    def test_complete_receipt_preserves_required_order_and_skips(self) -> None:
        clock = _Clock(list(range(100, 200)))
        observed = []
        timer = TimingRecorder(clock, observed.append)
        for name in REQUIRED_STAGES:
            if name in {"model_queue", "resource_wait"}:
                timer.skip(name, "not separately observable")
            else:
                self.assertEqual(timer.measure(name, lambda: "ok"), "ok")
        receipt = timer.receipt()
        self.assertEqual(
            tuple(span.name for span in receipt.spans), REQUIRED_STAGES)
        self.assertEqual(len(observed), len(REQUIRED_STAGES))
        self.assertEqual(len(receipt.digest), 64)
        self.assertGreater(receipt.total_duration_ns, 0)

    def test_failure_is_persisted_before_original_exception_escapes(self) -> None:
        observed = []
        timer = TimingRecorder(_Clock([1, 2, 5]), observed.append)

        def fail() -> None:
            raise ValueError("bad stage")

        with self.assertRaisesRegex(ValueError, "bad stage"):
            timer.measure("admission_import", fail)
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0].status, "failed")
        self.assertEqual(observed[0].detail, "ValueError")
        self.assertEqual(observed[0].duration_ns, 3)

    def test_duplicate_missing_and_invalid_clock_fail_closed(self) -> None:
        timer = TimingRecorder(_Clock([1, 2, 3, 4]))
        timer.skip("admission_import", "test")
        with self.assertRaisesRegex(QualityTimingError, "duplicate"):
            timer.skip("admission_import", "again")
        with self.assertRaisesRegex(QualityTimingError, "incomplete"):
            timer.receipt()
        with self.assertRaises(QualityTimingError):
            TimingRecorder(lambda: -1)

    def test_out_of_order_stage_is_rejected_without_running_operation(self) -> None:
        called = []
        timer = TimingRecorder(_Clock([10]))
        with self.assertRaisesRegex(QualityTimingError, "out of order"):
            timer.measure("repair", lambda: called.append(True))
        self.assertEqual(called, [])

    def test_clock_before_start_and_cross_span_regression_are_rejected(self) -> None:
        before_start = TimingRecorder(_Clock([100, 99]))
        with self.assertRaisesRegex(QualityTimingError, "predates"):
            before_start.skip("admission_import", "test")

        called = []
        regressed = TimingRecorder(_Clock([10, 11, 12, 11]))
        regressed.measure("admission_import", lambda: None)
        with self.assertRaisesRegex(QualityTimingError, "chronology"):
            regressed.measure("repair", lambda: called.append(True))
        self.assertEqual(called, [])

    def test_zero_total_duration_is_valid_and_all_stages_are_exact(self) -> None:
        timer = TimingRecorder(_Clock([7] * (len(REQUIRED_STAGES) + 1)))
        for name in REQUIRED_STAGES:
            timer.skip(name, "instant")
        receipt = timer.receipt()
        self.assertEqual(receipt.total_duration_ns, 0)
        self.assertEqual(
            tuple(span.name for span in receipt.spans), REQUIRED_STAGES)


if __name__ == "__main__":
    unittest.main(verbosity=2)
