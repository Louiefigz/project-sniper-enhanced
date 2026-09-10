"""P2 exact rational delivery-frame and sample-clock contracts."""
from __future__ import annotations

import unittest

from edit.exact_timing import (
    FrameRange,
    PositiveRational,
    ProjectClock,
    SampleRange,
    SourceRetime,
    TimingContractError,
    source_span_frames,
    source_span_project_samples,
)


class PositiveRationalTests(unittest.TestCase):
    def test_decimal_and_exponent_tokens_reduce_exactly(self) -> None:
        self.assertEqual(
            PositiveRational.from_value("29.97002997002997002997002997"),
            PositiveRational(2997002997002997002997002997, 100000000000000000000000000))
        self.assertEqual(
            PositiveRational.from_value("1.25e0"),
            PositiveRational(5, 4))
        self.assertEqual(
            PositiveRational.from_value(
                {"numerator": "30000", "denominator": "1001"}),
            PositiveRational(30000, 1001))

    def test_binary_float_and_noncanonical_object_fail(self) -> None:
        for value in (
            29.97,
            {"numerator": "060", "denominator": "1"},
            {"numerator": "60", "denominator": "2"},
            {"numerator": 60, "denominator": 1},
            {"numerator": "1", "denominator": "1", "extra": "x"},
        ):
            with self.subTest(value=value):
                with self.assertRaises(TimingContractError):
                    PositiveRational.from_value(value)
        for token in (" 1.0", "+1", "01", "1_000", ".5"):
            with self.subTest(token=token):
                with self.assertRaises(TimingContractError):
                    PositiveRational.from_value(token)

    def test_boolean_and_float_integers_never_enter_exact_authority(self) -> None:
        constructors = (
            lambda: PositiveRational(True, 1),
            lambda: FrameRange(False, 1),
            lambda: SampleRange(0, 1.5),
            lambda: ProjectClock(PositiveRational(30, 1), True),
        )
        for constructor in constructors:
            with self.subTest(constructor=constructor):
                with self.assertRaises(TimingContractError):
                    constructor()


class ProjectClockTests(unittest.TestCase):
    RATES = (
        PositiveRational(24000, 1001),
        PositiveRational(24, 1),
        PositiveRational(25, 1),
        PositiveRational(30000, 1001),
        PositiveRational(30, 1),
        PositiveRational(50, 1),
        PositiveRational(60000, 1001),
        PositiveRational(60, 1),
    )

    def test_adjacent_frame_partitions_have_zero_gap_or_overlap(self) -> None:
        for fps in self.RATES:
            with self.subTest(fps=fps):
                clock = ProjectClock(fps, 48_000)
                previous = clock.samples_for_frames(FrameRange(0, 1))
                for frame in range(1, 1000):
                    current = clock.samples_for_frames(
                        FrameRange(frame, frame + 1))
                    self.assertEqual(
                        previous.end_sample_exclusive,
                        current.start_sample)
                    previous = current
                self.assertEqual(
                    previous.end_sample_exclusive,
                    clock.sample_at_frame(1000))

    def test_adjacent_44100_boundaries_share_one_normalized_point(self) -> None:
        clock = ProjectClock(PositiveRational(30000, 1001), 48_000)
        boundary = 123_457
        left_end = clock.normalize_source_sample(boundary, 44_100)
        right_start = clock.normalize_source_sample(boundary, 44_100)
        self.assertEqual(left_end, right_start)
        self.assertEqual(
            clock.normalize_source_sample(boundary + 1, 44_100),
            (boundary + 1) * 48_000 // 44_100)

    def test_sample_to_containing_frame_honors_floored_boundaries(self) -> None:
        for fps in self.RATES:
            with self.subTest(fps=fps):
                clock = ProjectClock(fps, 48_000)
                for frame in (0, 1, 2, 99, 1000):
                    start = clock.sample_at_frame(frame)
                    end = clock.sample_at_frame(frame + 1)
                    self.assertEqual(clock.containing_frame(start), frame)
                    self.assertEqual(clock.containing_frame(end - 1), frame)

    def test_source_retime_consumes_exact_absolute_ranges(self) -> None:
        clock = ProjectClock(PositiveRational(30000, 1001), 48_000)
        retime = SourceRetime(
            SampleRange(44_100, 88_200),
            FrameRange(300, 330),
            44_100,
            clock,
        )
        output = clock.samples_for_frames(FrameRange(300, 330))
        self.assertEqual(
            retime.output_sample_for_source(44_100),
            output.start_sample)
        self.assertEqual(
            retime.output_sample_for_source(88_200),
            output.end_sample_exclusive)
        receipt = retime.receipt(
            PositiveRational(1, 1), PositiveRational(1, 500))
        self.assertEqual(receipt["outputSampleRange"], output.to_dict())
        self.assertEqual(
            receipt["normalizedSourceSampleRange"],
            {"startSample": 48_000, "endSampleExclusive": 96_000})
        self.assertEqual(receipt["requestedSpeed"],
                         {"numerator": "1", "denominator": "1"})
        self.assertEqual(
            receipt["maxAbsoluteSpeedDeviation"],
            {"numerator": "1", "denominator": "500"})

    def test_retime_outside_frozen_speed_tolerance_fails(self) -> None:
        clock = ProjectClock(PositiveRational(30, 1), 48_000)
        retime = SourceRetime(
            SampleRange(0, 48_000), FrameRange(0, 60), 48_000, clock)
        with self.assertRaisesRegex(TimingContractError, "speed-deviation"):
            retime.receipt(
                PositiveRational(1, 1), PositiveRational(1, 100))

    def test_complete_speech_span_quantizes_conservatively(self) -> None:
        clock = ProjectClock(PositiveRational(24000, 1001), 48_000)
        frames = source_span_frames(
            4_410, 44_100, PositiveRational(1, 1), clock)
        self.assertEqual(frames, 3)
        self.assertEqual(source_span_project_samples(
            4_410, 44_100, PositiveRational(1, 1), clock), 4_800)


if __name__ == "__main__":
    unittest.main(verbosity=2)
