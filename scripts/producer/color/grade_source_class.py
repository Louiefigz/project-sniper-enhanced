"""Streaming validation of supplied decoded-frame records, NOT a media probe.

A future approved worker must create these strict records from every ORIGINAL
decoded frame, before scale/format/trim/speed. This module opens nothing and
cannot prove a decoder ran. Partial diagnostics and stream tags alone cannot
finish validation. No grade, plan, output tag or approval is written.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from fractions import Fraction

from color.grade_contract import (
    SourceBinding, closed, integer, parse_source_binding,
)
from color.grade_observation_geometry import SourceObservationMetadata, parse_source_metadata
from color.grade_observation_profile import (
    ObservationProfile, V1, V2, frame_budget, observation_declaration, observation_profile,
)
from cross_runtime_canonical_json import canonical_compact_json

_CLOCK_LIMIT = 2 ** 53 - 1
_COLOR = {"pixelFormat": "yuv420p", "range": "tv", "matrix": "bt709",
          "transfer": "bt709", "primaries": "bt709", "hdrSignaled": False}
_STREAM_KEYS = set(_COLOR) | {"videoStreamCount", "streamIndex", "fps", "timeBase",
                             "firstPts", "frameCount", "width", "height", "progressive"}
_FRAME_KEYS = set(_COLOR) | {"index", "streamIndex", "pts", "durationTicks", "width",
                            "height", "interlaced", "repeatPict", "corrupt", "decodeErrorFlags"}
ERROR_POLICY = "ffprobe-4.4.2-full-source-warning-empty-explode-v1"
_END_KEYS = {"source", "reachedEof", "decoderExitCode", "decoderErrorCount",
             "decoderWarningCount", "decoderErrorObservationPolicy"}


def _color(row: dict, profile: ObservationProfile = V1) -> None:
    """Missing, mixed, unknown, HDR and high-bit-depth facts are not converted."""
    expected_color = {**_COLOR, "transfer": profile.transfer}
    if any(type(row[key]) is not type(expected) or row[key] != expected
           for key, expected in expected_color.items()):
        raise ValueError("grade source has unsupported or changing decoded color metadata")


def _time_base(value: object) -> Fraction:
    """Require reduced exact rational ticks, with bounded parsing complexity."""
    if type(value) is not str or not re.fullmatch(r"[1-9][0-9]{0,8}/[1-9][0-9]{0,8}", value):
        raise ValueError("grade source timebase must be an explicit positive rational")
    numerator, denominator = map(int, value.split("/"))
    result = Fraction(numerator, denominator)
    if (numerator, denominator) != (result.numerator, result.denominator):
        raise ValueError("grade source timebase must be reduced")
    return result


@dataclass(frozen=True)
class ObservedStream:
    """Strict caller-supplied source clock/class, not trusted media authority."""

    index: int
    time_base: Fraction
    first_pts: int
    step_ticks: int
    width: int
    height: int
    source_metadata: SourceObservationMetadata | None = None


def _stream(value: object, binding: SourceBinding, profile: ObservationProfile = V1) -> ObservedStream:
    """Validate the reported class; every frame must independently match later."""
    row = closed(value, _STREAM_KEYS | ({"sourceMetadata"} if profile is V2 else set()), "grade observed stream")
    _color(row, profile)
    if type(row["videoStreamCount"]) is not int or row["videoStreamCount"] != 1 \
            or row["progressive"] is not True:
        raise ValueError("grade requires one progressive video stream")
    count = integer(row["frameCount"], 1, binding.frame_count)
    if count != binding.frame_count or row["fps"] != str(binding.fps):
        raise ValueError("grade observed source count/rate differs from its binding")
    base = _time_base(row["timeBase"])
    step = 1 / (binding.fps * base)
    if step.denominator != 1 or not 1 <= step <= _CLOCK_LIMIT:
        raise ValueError("grade initial class requires an exactly representable constant frame tick")
    width, height = integer(row["width"], 2, 8192), integer(row["height"], 2, 8192)
    if width % 2 or height % 2 or width * height > 33_177_600:
        raise ValueError("grade source dimensions are outside bounded 8-bit 4:2:0")
    if profile is V2:
        frame_budget(width, height, count, profile)
    origin = integer(row["firstPts"], -_CLOCK_LIMIT, _CLOCK_LIMIT)
    integer(origin + count * int(step), -_CLOCK_LIMIT, _CLOCK_LIMIT)
    metadata = parse_source_metadata(row["sourceMetadata"]) if profile is V2 else None
    return ObservedStream(integer(row["streamIndex"], 0, 63), base, origin, int(step), width, height, metadata)


@dataclass(frozen=True)
class SourceRecordValidation:
    """Validated supplied records only; external worker evidence remains required."""

    source: SourceBinding
    stream: ObservedStream
    decoded_record_count: int
    records_sha256: str
    validator_policy: str = field(default="sniper-private-grade-frame-records-v2", init=False)
    decoded_frame_flags_available: bool = field(default=False, init=False)
    record_validation_only: bool = field(default=True, init=False)
    decoder_execution_proved: bool = field(default=False, init=False)
    grade_applicable: bool = field(default=False, init=False)
    delivery_approved: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        """Distinguish v2 siting-bearing records without changing the v1 receipt."""
        if self.stream.source_metadata is not None:
            object.__setattr__(self, "validator_policy", "sniper-private-grade-frame-records-v3")


class SourceFrameValidator:
    """O(1)-memory, monotonic fail-closed consumer of a complete record stream.

    Record count is bounded, but this pure consumer does not own a wall timer.
    Its future caller must bound decode/IO/cleanup independently. An invalid
    record permanently poisons this instance; it cannot be skipped and resumed.
    """

    def __init__(self, binding: object, declaration: object, stream: object, profile: str | None = None) -> None:
        self._profile = observation_profile(profile)
        self._binding = parse_source_binding(binding)
        observation_declaration(declaration, self._binding, self._profile)
        self._stream = _stream(stream, self._binding, self._profile)
        self._count = 0
        self._state = "open"
        self._hash = hashlib.sha256()
        self._hash.update((canonical_compact_json(stream) + "\n").encode("utf8"))

    def _require_open(self) -> None:
        """No recovery from invalid observations or a completed record stream."""
        if self._state != "open":
            raise ValueError(f"grade frame validator is {self._state}")

    def add_frame(self, value: object) -> None:
        """Consume exactly the next frame, never a sampled or reordered subset."""
        self._require_open()
        self._state = "failed"
        extra = {"chromaLocation", "sampleAspectRatio"} if self._profile is V2 else set()
        row = closed(value, _FRAME_KEYS | extra, "grade decoded frame")
        _color(row, self._profile)
        if self._count >= self._binding.frame_count:
            raise ValueError("grade decoder supplied extra source frames")
        if integer(row["index"], 0, self._binding.frame_count - 1) != self._count:
            raise ValueError("grade decoded frames are missing, repeated or reordered")
        self._frame_shape(row)
        expected_pts = self._stream.first_pts + self._count * self._stream.step_ticks
        if integer(row["pts"], -_CLOCK_LIMIT, _CLOCK_LIMIT) != expected_pts \
                or integer(row["durationTicks"], 1, _CLOCK_LIMIT) != self._stream.step_ticks:
            raise ValueError("grade source is not the exact bound CFR clock")
        self._hash.update((canonical_compact_json(row) + "\n").encode("utf8"))
        self._count += 1
        self._state = "open"

    def _frame_shape(self, row: dict) -> None:
        """Validate decoded geometry and error/field facts before any conversion."""
        expected = {"streamIndex": self._stream.index, "width": self._stream.width,
                    "height": self._stream.height, "interlaced": False,
                    "repeatPict": 0, "corrupt": None, "decodeErrorFlags": None}
        if self._profile is V2:
            expected.update(chromaLocation=self._stream.source_metadata.decoded_chroma_location,
                            sampleAspectRatio=self._stream.source_metadata.decoded_sample_aspect_ratio)
        if any(type(row[key]) is not type(value) or row[key] != value
               for key, value in expected.items()):
            raise ValueError("grade source has changed geometry, field cadence or decode errors")

    def finish(self, value: object) -> SourceRecordValidation:
        """Require complete EOF/clean exit and unchanged current identities."""
        self._require_open()
        self._state = "failed"
        row = closed(value, _END_KEYS, "grade decoder terminal record")
        if row["reachedEof"] is not True or type(row["decoderExitCode"]) is not int \
                or row["decoderExitCode"] != 0 or type(row["decoderErrorCount"]) is not int \
                or row["decoderErrorCount"] != 0 or type(row["decoderWarningCount"]) is not int \
                or row["decoderWarningCount"] != 0 or row["decoderErrorObservationPolicy"] != ERROR_POLICY:
            raise ValueError("grade decoder did not finish cleanly at source EOF")
        if self._count != self._binding.frame_count:
            raise ValueError("grade complete-source decoded record coverage is missing")
        if parse_source_binding(row["source"]) != self._binding:
            raise ValueError("grade source or declaration/history identity changed during observation")
        self._hash.update((canonical_compact_json(row) + "\n").encode("utf8"))
        self._state = "finished"
        return SourceRecordValidation(self._binding, self._stream, self._count, self._hash.hexdigest())
