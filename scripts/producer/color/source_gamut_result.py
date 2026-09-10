"""Closed supplied-float reductions, never native gamut or transform authority.

The expected SourceRecordValidation is itself constructible record evidence.
This parser binds arithmetic and the original record digest, not a decoder,
source file, transform, toolchain, process settlement or retained deadline.
Only a separate future owned native producer/readback could prove those facts.
"""
from __future__ import annotations

import json
import math
import struct
from fractions import Fraction

from color.grade_contract import SourceBinding, closed, integer, parse_source_binding
from color.grade_observation_geometry import SourceObservationMetadata, parse_source_metadata
from color.grade_observation_profile import V2, frame_budget
from color.grade_source_class import ObservedStream, SourceRecordValidation
from color.source_picture_transform_contract import sha256

RESULT_KIND = "source-gamut-float-record-validation"
RESULT_SCOPE = "supplied-framed-float-bytes-not-native-or-gamut-qualification"
_FIXED = {"schemaVersion": 1, "kind": RESULT_KIND, "scope": RESULT_SCOPE,
          "nativeExecutionProved": False, "gamutQualified": False,
          "transformApplicable": False, "gradeApplicable": False,
          "deliveryApproved": False}
_COUNTS = {"finiteCount", "nanCount", "positiveInfinityCount",
           "negativeInfinityCount", "belowZeroCount", "aboveOneCount"}
_RESULT_KEYS = set(_FIXED) | {"binding", "originalRecordsSha256", "joinedRecordsSha256",
    "frameCount", "pixelCount", "payloadBytes", "channels", "sampleRangeValid"}
_CLOCK_LIMIT = 2 ** 53 - 1


def _expected(value: SourceRecordValidation, binding: dict) -> int:
    """Recheck bounded original metadata; a Python instance is not provenance."""
    if type(value) is not SourceRecordValidation:
        raise ValueError("gamut reduction needs original source record validation")
    source, stream = value.source, value.stream
    parsed = parse_source_binding(binding)
    if type(source) is not SourceBinding or type(stream) is not ObservedStream \
            or any(type(getattr(source, key)) is not type(item) or getattr(source, key) != item
                   for key, item in vars(parsed).items()):
        raise ValueError("gamut reduction source binding differs")
    count = integer(value.decoded_record_count, 1, V2.max_frames)
    if count != source.frame_count or value.validator_policy != "sniper-private-grade-frame-records-v3":
        raise ValueError("gamut reduction original record coverage/profile differs")
    flags = {"record_validation_only": True, "decoded_frame_flags_available": False,
             "decoder_execution_proved": False, "grade_applicable": False, "delivery_approved": False}
    if any(getattr(value, key) is not expected for key, expected in flags.items()):
        raise ValueError("gamut reduction original records imply unsupported authority")
    frame_budget(stream.width, stream.height, count, V2)
    integer(stream.index, 0, 63)
    integer(stream.first_pts, -_CLOCK_LIMIT, _CLOCK_LIMIT)
    integer(stream.step_ticks, 1, _CLOCK_LIMIT)
    integer(stream.first_pts + count * stream.step_ticks, -_CLOCK_LIMIT, _CLOCK_LIMIT)
    if type(stream.time_base) is not Fraction \
            or not 1 <= stream.time_base.numerator <= 999_999_999 \
            or not 1 <= stream.time_base.denominator <= 999_999_999 \
            or 1 / (source.fps * stream.time_base) != stream.step_ticks:
        raise ValueError("gamut reduction original frame clock differs")
    if type(stream.source_metadata) is not SourceObservationMetadata:
        raise ValueError("gamut reduction needs explicit original V2 metadata")
    parse_source_metadata(stream.source_metadata.record())
    sha256(value.records_sha256)
    return count * stream.width * stream.height


def _float32(value: object) -> float:
    """Extrema must be exact finite float32 values, without rounding or epsilon."""
    if type(value) not in (int, float):
        raise ValueError("gamut reduction extremum must be a finite float32 number")
    try:
        number = float(value)
        exact = struct.unpack("<f", struct.pack("<f", number))[0]
    except (OverflowError, struct.error) as error:
        raise ValueError("gamut reduction extremum exceeds float32") from error
    if not math.isfinite(number) or number != exact or value != exact:
        raise ValueError("gamut reduction extremum is not exact finite float32")
    return number


def _extrema(row: dict) -> None:
    """Cross-check endpoint signs with the counted finite categories."""
    finite = row["finiteCount"]
    if finite == 0:
        if row["minimum"] is not None or row["maximum"] is not None:
            raise ValueError("gamut reduction empty finite set needs null extrema")
        return
    low, high = _float32(row["minimum"]), _float32(row["maximum"])
    below, above = row["belowZeroCount"], row["aboveOneCount"]
    if low > high or (finite == 1 and low != high) \
            or (low < 0) != (below > 0) or (high > 1) != (above > 0) \
            or (high < 0) != (below == finite) or (low > 1) != (above == finite):
        raise ValueError("gamut reduction extrema and category counts disagree")


def _channel(value: object, pixels: int) -> bool:
    """Every supplied pixel has one value in each channel; infinities are separate."""
    row = closed(value, _COUNTS | {"minimum", "maximum"}, "gamut reduction channel")
    for key in _COUNTS:
        integer(row[key], 0, pixels)
    total = sum(row[key] for key in ("finiteCount", "nanCount",
                                    "positiveInfinityCount", "negativeInfinityCount"))
    outside = row["belowZeroCount"] + row["aboveOneCount"]
    if total != pixels or outside > row["finiteCount"]:
        raise ValueError("gamut reduction channel sample coverage differs")
    _extrema(row)
    return row["finiteCount"] == pixels and outside == 0


def validate_gamut_reduction(value: object, expected: SourceRecordValidation) -> dict:
    """Return detached validated records only, never an executable grade receipt."""
    row = closed(value, _RESULT_KEYS, "gamut reduction result")
    if any(type(row[key]) is not type(wanted) or row[key] != wanted
           for key, wanted in _FIXED.items()):
        raise ValueError("gamut reduction result schema/scope or authority differs")
    pixels = _expected(expected, row["binding"])
    if sha256(row["originalRecordsSha256"]) != expected.records_sha256:
        raise ValueError("gamut reduction original record digest differs")
    sha256(row["joinedRecordsSha256"])
    sizes = {"frameCount": expected.decoded_record_count,
             "pixelCount": pixels, "payloadBytes": pixels * 12}
    if any(type(row[key]) is not int or row[key] != count for key, count in sizes.items()):
        raise ValueError("gamut reduction frame/pixel/byte coverage differs")
    channels = closed(row["channels"], {"r", "g", "b"}, "gamut reduction channels")
    valid = [_channel(channels[key], pixels) for key in ("g", "b", "r")]
    if type(row["sampleRangeValid"]) is not bool or row["sampleRangeValid"] != all(valid):
        raise ValueError("gamut reduction range verdict differs from supplied counts")
    # All closed fields are bounded above. Unlike canonical integer clocks,
    # finite float32 extrema can legitimately exceed the JS safe-integer range.
    return json.loads(json.dumps(row, ensure_ascii=True, allow_nan=False))
