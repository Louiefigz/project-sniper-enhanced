"""Synthetic closed reduction records only; no pixels, media, or native proof."""
from __future__ import annotations

import copy
import struct
import unittest
from dataclasses import replace

from _source_picture_transform_fixture import transform_fixture
from color.grade_source_class import SourceRecordValidation
from color.source_gamut_result import RESULT_KIND, RESULT_SCOPE, validate_gamut_reduction


def fixture() -> tuple[dict, SourceRecordValidation]:
    """Make exact record arithmetic with clearly synthetic joined-byte identity."""
    context, _ = transform_fixture()
    expected = context.observation.records
    pixels = expected.decoded_record_count * expected.stream.width * expected.stream.height
    channel = {"finiteCount": pixels, "nanCount": 0, "positiveInfinityCount": 0,
               "negativeInfinityCount": 0, "belowZeroCount": 0, "aboveOneCount": 0,
               "minimum": 0, "maximum": 1}
    return {"schemaVersion": 1, "kind": RESULT_KIND, "scope": RESULT_SCOPE,
            "binding": copy.deepcopy(context.authority["binding"]),
            "originalRecordsSha256": expected.records_sha256, "joinedRecordsSha256": "7" * 64,
            "frameCount": expected.decoded_record_count, "pixelCount": pixels,
            "payloadBytes": pixels * 12,
            "channels": {key: copy.deepcopy(channel) for key in ("r", "g", "b")},
            "sampleRangeValid": True, "nativeExecutionProved": False,
            "gamutQualified": False, "transformApplicable": False,
            "gradeApplicable": False, "deliveryApproved": False}, expected


class SourceGamutResultTests(unittest.TestCase):
    """Typed coverage, exact float endpoints, and no authority by record parsing."""

    def test_valid_result_is_detached_and_not_native_qualification(self) -> None:
        """Parsing may preserve a supplied range verdict, never grant authority."""
        row, expected = fixture()
        parsed = validate_gamut_reduction(row, expected)
        self.assertEqual(parsed, row)
        self.assertTrue(parsed["sampleRangeValid"])
        for key in ("nativeExecutionProved", "gamutQualified", "transformApplicable",
                    "gradeApplicable", "deliveryApproved"):
            self.assertIs(parsed[key], False)
        parsed["binding"]["sourceId"] = "TEST-mutated"
        parsed["channels"]["r"]["minimum"] = 99
        self.assertNotEqual(parsed, row)
        validate_gamut_reduction(row, expected)

    def test_closed_scopes_counts_and_flags_are_exact_types(self) -> None:
        """Truthy values, negative counts and a different authority scope reject."""
        changes = [("schemaVersion", True), ("scope", "native-gamut-qualified"),
                   ("extra", None), ("frameCount", 3.0), ("pixelCount", True),
                   ("payloadBytes", -1), ("sampleRangeValid", 1)]
        changes += [(key, 0) for key in ("nativeExecutionProved", "gamutQualified",
                     "transformApplicable", "gradeApplicable", "deliveryApproved")]
        for key, value in changes:
            row, expected = fixture()
            row[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_gamut_reduction(row, expected)

    def test_hashes_and_original_source_binding_cannot_be_swapped(self) -> None:
        """Different original bytes/history/counts require new record validation."""
        for key in ("originalRecordsSha256", "joinedRecordsSha256"):
            row, expected = fixture()
            row[key] = "A" * 64
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_gamut_reduction(row, expected)
        for key in fixture()[0]["binding"]:
            row, expected = fixture()
            row["binding"][key] = "changed"
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_gamut_reduction(row, expected)
        row, expected = fixture()
        row["originalRecordsSha256"] = "8" * 64
        with self.assertRaises(ValueError):
            validate_gamut_reduction(row, expected)

    def test_each_channel_has_complete_typed_sample_coverage(self) -> None:
        """No channel omission, channel alias or category under/overcount fits."""
        changes = [(key, True) for key in ("finiteCount", "nanCount", "positiveInfinityCount",
                   "negativeInfinityCount", "belowZeroCount", "aboveOneCount")]
        changes += [("finiteCount", 95), ("nanCount", 1), ("aboveOneCount", 97),
                    ("extra", 0), ("belowZeroCount", -1), ("nanCount", 0.0)]
        for key, value in changes:
            row, expected = fixture()
            row["channels"]["b"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate_gamut_reduction(row, expected)
        row, expected = fixture()
        row["channels"]["G"] = row["channels"].pop("g")
        with self.assertRaises(ValueError):
            validate_gamut_reduction(row, expected)

    def test_nonfinite_observation_completes_only_with_false_range_verdict(self) -> None:
        """Observing invalid values is useful evidence, not failure-hidden clipping."""
        row, expected = fixture()
        channel = row["channels"]["g"]
        channel.update(finiteCount=0, nanCount=32, positiveInfinityCount=32,
                       negativeInfinityCount=32, minimum=None, maximum=None)
        row["sampleRangeValid"] = False
        self.assertEqual(validate_gamut_reduction(row, expected), row)
        row["sampleRangeValid"] = True
        with self.assertRaises(ValueError):
            validate_gamut_reduction(row, expected)

    def test_empty_finite_set_requires_both_null_extrema_and_no_finite_outliers(self) -> None:
        """Infinities are not also counted as finite out-of-range samples."""
        for delta in ({"minimum": 0}, {"maximum": 0}, {"belowZeroCount": 1}):
            row, expected = fixture()
            row["sampleRangeValid"] = False
            row["channels"]["r"].update({"finiteCount": 0, "nanCount": 96,
                                        "minimum": None, "maximum": None, **delta})
            with self.subTest(delta=delta), self.assertRaises(ValueError):
                validate_gamut_reduction(row, expected)

    def test_float32_extrema_are_exact_without_gamut_epsilon(self) -> None:
        """One representable step beyond an endpoint invalidates the range verdict."""
        above_one = struct.unpack("<f", struct.pack("<I", 0x3f800001))[0]
        row, expected = fixture()
        row["channels"]["r"].update(aboveOneCount=1, maximum=above_one)
        row["sampleRangeValid"] = False
        self.assertEqual(validate_gamut_reduction(row, expected), row)
        for value in (0.1, float("nan"), float("inf"), 2 ** 128, (2 ** 60) + 1, True, None):
            row, expected = fixture()
            row["channels"]["r"]["maximum"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_gamut_reduction(row, expected)

    def test_largest_finite_float32_is_reported_without_canonical_clock_rounding(self) -> None:
        """Extreme measured values are diagnostics, not integer-valued media clocks."""
        row, expected = fixture()
        maximum = struct.unpack("<f", struct.pack("<I", 0x7f7fffff))[0]
        row["channels"]["r"].update(belowZeroCount=1, aboveOneCount=1,
                                    minimum=-maximum, maximum=maximum)
        row["sampleRangeValid"] = False
        self.assertEqual(validate_gamut_reduction(row, expected), row)

    def test_extrema_must_agree_with_finite_category_counts(self) -> None:
        """Valid aggregate sums do not conceal impossible observed extrema."""
        for delta in ({"minimum": -1}, {"maximum": 2}, {"minimum": 1, "maximum": 0},
                      {"belowZeroCount": 1}, {"aboveOneCount": 1},
                      {"minimum": -2, "maximum": -1, "belowZeroCount": 95},
                      {"minimum": 2, "maximum": 3, "aboveOneCount": 95},
                      {"finiteCount": 1, "nanCount": 95}):
            row, expected = fixture()
            row["sampleRangeValid"] = False
            row["channels"]["r"].update(delta)
            with self.subTest(delta=delta), self.assertRaises(ValueError):
                validate_gamut_reduction(row, expected)

    def test_expected_dataclass_equality_cannot_coerce_clock_or_source_types(self) -> None:
        """Constructible original records must retain exact integer/rational types."""
        row, expected = fixture()
        changes = [replace(expected, decoded_record_count=3.0),
                   replace(expected, source=replace(expected.source, frame_count=3.0)),
                   replace(expected, stream=replace(expected.stream, width=8.0)),
                   replace(expected, stream=replace(expected.stream, step_ticks=1001.0)),
                   replace(expected, stream=replace(expected.stream, first_pts=24000.0)),
                   replace(expected, stream=replace(expected.stream, time_base=0.5)),
                   replace(expected, stream=replace(expected.stream, source_metadata=None))]
        for changed in changes:
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                validate_gamut_reduction(row, changed)


if __name__ == "__main__":
    unittest.main()
