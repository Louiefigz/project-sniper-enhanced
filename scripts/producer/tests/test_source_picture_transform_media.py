"""Actual tiny raw source/float bridge tests, not a qualified creator transform."""
from __future__ import annotations

import json
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

from _source_picture_transform_fixture import held_test_file
from _source_picture_transform_media import RampRun
from color.source_picture_transform_reference import limited_ycbcr_to_linear, require_unit_gamut


def _expected(values: list[tuple[int, int, int]]) -> tuple[float, ...]:
    """Independent scalar uniform-patch oracle, in actual GBR planar byte order."""
    result = []
    for value in values:
        red, green, blue = limited_ycbcr_to_linear(value)
        result.extend([green] * 32 + [blue] * 32 + [red] * 32)
    return tuple(result)


def _clock(value: dict) -> tuple:
    """Compare all observed frame times exactly, including nonzero source PTS."""
    streams = value["streams"]
    if len(streams) != 1 or streams[0]["codec_type"] != "video":
        raise AssertionError("TEST expected one native picture stream")
    stream = streams[0]
    base = Fraction(stream["time_base"])
    times = tuple(Fraction(row["pts"]) * base for row in value["frames"])
    return stream["width"], stream["height"], Fraction(stream["r_frame_rate"]), times


class SourcePictureTransformMediaTests(unittest.TestCase):
    """All actual processes are tiny, owned and bounded by the original clock."""

    @classmethod
    def setUpClass(cls) -> None:
        """Retain even failed diagnostics in a new private TEST-only root."""
        cls.root = Path(tempfile.mkdtemp(prefix="sniper-picture-transform-", dir="/private/tmp"))
        print(f"TEST picture transform root: {cls.root}", flush=True)
        cls.runner = RampRun(cls.root)
        cls.metrics = []

    @classmethod
    def tearDownClass(cls) -> None:
        """Keep exact residuals and ownership-checked process evidence, not approval."""
        (cls.root / "TEST-ramp-metrics.json").write_text(json.dumps(cls.metrics, indent=2) + "\n")
        cls.runner.finish()

    def test_actual_uniform_neutral_and_chroma_ramps_match_scalar_at_three_rates(self) -> None:
        """RGB float comparison tolerance is separate from zero-tolerance gamut."""
        values = [(16, 128, 128), (32, 128, 128), (100, 128, 128), (128, 128, 128),
                  (180, 128, 128), (235, 128, 128), (100, 110, 140), (160, 140, 110)]
        for rate in ("24", "24000/1001", "30000/1001"):
            self._positive_rate(rate, values)

    def _positive_rate(self, rate: str, values: list[tuple[int, int, int]]) -> None:
        """Run both fixed fragments and compare complete native clocks/inputs."""
        name = rate.replace("/", "-")
        source = self.runner.source(name, values, rate)
        held = held_test_file(source)
        plan = self.runner.compile(rate, len(values))
        linear = self.runner.convert(source, plan.measurement_filter, name + "-linear")
        actual = self.runner.float_pixels(linear, name + "-linear")
        expected = _expected(values)
        self.assertEqual(len(actual), len(expected))
        residual = max(abs(left - right) for left, right in zip(actual, expected, strict=True))
        self.metrics.append({"name": name, "maximumScalarAbsoluteResidual": residual,
            "scalarComparisonTolerance": 3e-6, "gamutTolerance": 0,
            "actualMinimum": min(actual), "actualMaximum": max(actual)})
        self.assertLessEqual(residual, 3e-6)
        for position in range(0, len(actual), 3):
            require_unit_gamut(actual[position:position + 3])
        destination = self.runner.convert(linear, plan.destination_filter, name + "-bt709")
        target = self.runner.raw_pixels(destination, name + "-bt709")
        original = (self.root / (name + ".yuv")).read_bytes()
        self.assertEqual(len(target), len(original))
        code_error = max(abs(a - b) for a, b in zip(target, original, strict=True))
        self.assertLessEqual(code_error, 1)
        self.metrics[-1]["maximumDestinationCodeError"] = code_error
        source_clock = _clock(self.runner.metadata(source))
        self.assertEqual(source_clock, _clock(self.runner.metadata(linear)))
        self.assertEqual(source_clock, _clock(self.runner.metadata(destination)))
        self.assertEqual(len(source_clock[-1]), len(values))
        self.assertGreater(source_clock[-1][0], 0)
        self.assertEqual(held_test_file(source), held)

    def test_actual_extended_negative_and_superwhite_are_measured_then_rejected(self) -> None:
        """A legal-range clamp or label-only conversion cannot pass this oracle."""
        values = [(0, 128, 128), (255, 128, 128), (100, 16, 240)]
        source = self.runner.source("extended", values, "30000/1001")
        plan = self.runner.compile("30000/1001", len(values))
        linear = self.runner.convert(source, plan.measurement_filter, "extended-linear")
        actual = self.runner.float_pixels(linear, "extended-linear")
        expected = _expected(values)
        residual = max(abs(left - right) for left, right in zip(actual, expected, strict=True))
        self.assertLessEqual(residual, 3e-6)
        self.assertLess(min(actual), -0.001)
        self.assertGreater(max(actual), 1.001)
        for frame in range(len(values)):
            pixels = actual[frame * 96:(frame + 1) * 96]
            with self.assertRaisesRegex(ValueError, "outside"):
                require_unit_gamut((pixels[0], pixels[32], pixels[64]))
        self.metrics.append({"name": "extended-rejected", "maximumScalarAbsoluteResidual": residual,
            "actualMinimum": min(actual), "actualMaximum": max(actual),
            "destinationExecuted": False, "gamutTolerance": 0})

    def test_actual_one_frame_nonzero_origin_survives_float_bridge(self) -> None:
        """The compiler must not introduce a duration/FPS/final-frame convention."""
        for rate in ("24", "30000/1001"):
            name = "single-" + rate.replace("/", "-")
            source = self.runner.source(name, [(100, 128, 128)], rate)
            plan = self.runner.compile(rate, 1)
            linear = self.runner.convert(source, plan.measurement_filter, name + "-linear")
            before, after = _clock(self.runner.metadata(source)), _clock(self.runner.metadata(linear))
            self.assertEqual(before, after)
            self.assertEqual(len(after[-1]), 1)
            self.assertGreater(after[-1][0], 0)
