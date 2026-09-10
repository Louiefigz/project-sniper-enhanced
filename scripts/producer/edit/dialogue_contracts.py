"""Closed parsing and semantic checks for sample-native dialogue authority."""
from __future__ import annotations

import re
from fractions import Fraction

from edit.exact_timing import (
    PositiveRational, ProjectClock, SampleRange, TimingContractError)

_HASH = re.compile(r"^[0-9a-f]{64}$")
_STABLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
_SAFE_MAX = 9_007_199_254_740_991
_ROLES = {"primary", "j-cut-handle", "l-cut-handle"}
_ROLE_ORDER = {"primary": 0, "j-cut-handle": 1, "l-cut-handle": 2}
SEGMENT_KEYS = {
    "dialogueSegmentId", "cutSegmentId", "elementVersion", "sourceId",
    "sourceSampleRate", "sourceSampleRange", "outputSampleRange", "speed",
    "role", "seamSample", "coveredByCutSegmentId",
}
SEGMENT_REQUIRED = SEGMENT_KEYS - {"seamSample", "coveredByCutSegmentId"}
TRACK_KEYS = {
    "schemaVersion", "kind", "sourceSnapshotSetHash",
    "pictureTimelineMapHash", "projectFps", "projectSampleRate",
    "totalOutputFrames", "totalOutputSamples", "maxAbsoluteSpeedDeviation",
    "segments",
}
MAP_KEYS = (TRACK_KEYS - {"segments", "kind"}) | {
    "kind", "dialogueTrackHash", "entries",
}


class DialogueAuthorityError(ValueError):
    """Dialogue authority is malformed, ambiguous, or inconsistent."""


def object_value(value: object, label: str) -> dict:
    """Require one plain JSON object."""
    if not isinstance(value, dict):
        raise DialogueAuthorityError(f"{label} must be an object")
    return value


def exact_keys(row: dict, allowed: set[str],
               required: set[str], label: str) -> None:
    """Reject missing and unknown object fields."""
    extras = set(row) - allowed
    missing = required - set(row)
    if extras or missing:
        raise DialogueAuthorityError(
            f"{label} fields are not closed: "
            f"extras={sorted(extras)}, missing={sorted(missing)}")


def safe_integer(value: object, label: str, minimum: int = 0) -> int:
    """Require a cross-language JSON-safe integer."""
    if type(value) is not int or not minimum <= value <= _SAFE_MAX:
        raise DialogueAuthorityError(
            f"{label} must be a safe integer >= {minimum}")
    return value


def sha256(value: object, label: str) -> str:
    """Require a lowercase SHA-256."""
    if not isinstance(value, str) or _HASH.fullmatch(value) is None:
        raise DialogueAuthorityError(f"{label} must be a lowercase SHA-256")
    return value


def stable_id(value: object, label: str) -> str:
    """Require the shared stable-ID grammar."""
    if not isinstance(value, str) or _STABLE_ID.fullmatch(value) is None:
        raise DialogueAuthorityError(f"{label} must be a stable ID")
    return value


def rational(value: object, label: str) -> PositiveRational:
    """Require canonical ``PositiveRationalV1`` input."""
    try:
        return PositiveRational.from_value(value)
    except (TimingContractError, ValueError) as exc:
        raise DialogueAuthorityError(
            f"{label} must be a canonical PositiveRationalV1") from exc


def sample_range(value: object, label: str) -> SampleRange:
    """Require one non-empty, half-open safe-integer sample range."""
    row = object_value(value, label)
    required = {"startSample", "endSampleExclusive"}
    exact_keys(row, required, required, label)
    try:
        return SampleRange(
            safe_integer(row["startSample"], f"{label}.startSample"),
            safe_integer(
                row["endSampleExclusive"],
                f"{label}.endSampleExclusive", 1),
        )
    except TimingContractError as exc:
        raise DialogueAuthorityError(f"{label} must be non-empty") from exc


def parse_segment(value: object, label: str, compiled: bool = False) -> dict:
    """Parse a track segment or compiled map entry."""
    row = object_value(value, label)
    allowed = set(SEGMENT_KEYS)
    required = set(SEGMENT_REQUIRED)
    if compiled:
        allowed |= {"normalizedSourceSampleRange", "effectiveSpeed"}
        required |= {"normalizedSourceSampleRange", "effectiveSpeed"}
    exact_keys(row, allowed, required, label)
    role = row["role"]
    if role not in _ROLES:
        raise DialogueAuthorityError(f"{label}.role is unsupported")
    _check_handle_fields(row, role, label)
    parsed = _base_segment(row, label)
    if compiled:
        parsed["normalizedSourceSampleRange"] = sample_range(
            row["normalizedSourceSampleRange"],
            f"{label}.normalizedSourceSampleRange").to_dict()
    parsed["outputSampleRange"] = sample_range(
        row["outputSampleRange"], f"{label}.outputSampleRange").to_dict()
    parsed["speed"] = rational(row["speed"], f"{label}.speed").to_dict()
    if compiled:
        parsed["effectiveSpeed"] = rational(
            row["effectiveSpeed"], f"{label}.effectiveSpeed").to_dict()
    parsed["role"] = role
    if role != "primary":
        parsed["seamSample"] = safe_integer(
            row["seamSample"], f"{label}.seamSample")
        parsed["coveredByCutSegmentId"] = stable_id(
            row["coveredByCutSegmentId"],
            f"{label}.coveredByCutSegmentId")
    return parsed


def _check_handle_fields(row: dict, role: str, label: str) -> None:
    handle_fields = {"seamSample", "coveredByCutSegmentId"}
    if role == "primary" and handle_fields & set(row):
        raise DialogueAuthorityError(f"{label} primary cannot carry handle fields")
    if role != "primary" and not handle_fields <= set(row):
        raise DialogueAuthorityError(f"{label} handle fields are required")


def _base_segment(row: dict, label: str) -> dict:
    return {
        "dialogueSegmentId": stable_id(
            row["dialogueSegmentId"], f"{label}.dialogueSegmentId"),
        "cutSegmentId": stable_id(
            row["cutSegmentId"], f"{label}.cutSegmentId"),
        "elementVersion": safe_integer(
            row["elementVersion"], f"{label}.elementVersion", 1),
        "sourceId": stable_id(row["sourceId"], f"{label}.sourceId"),
        "sourceSampleRate": safe_integer(
            row["sourceSampleRate"], f"{label}.sourceSampleRate", 1),
        "sourceSampleRange": sample_range(
            row["sourceSampleRange"], f"{label}.sourceSampleRange").to_dict(),
    }


def segment_sort_key(row: dict) -> tuple[int, int, str]:
    """Return the sole canonical dialogue-segment order."""
    return (row["outputSampleRange"]["startSample"],
            _ROLE_ORDER[row["role"]], row["dialogueSegmentId"])


def _handle_checks(row: dict, primaries: dict[str, dict]) -> None:
    own = primaries.get(row["cutSegmentId"])
    covered = primaries.get(row["coveredByCutSegmentId"])
    if own is None or covered is None or own is covered:
        raise DialogueAuthorityError(
            "each L/J handle must bind distinct owned and covering primaries")
    shared = ("elementVersion", "sourceId", "sourceSampleRate", "speed")
    if any(row[key] != own[key] for key in shared):
        raise DialogueAuthorityError(
            "an L/J handle must share source/version/speed with its primary")
    source = row["sourceSampleRange"]
    own_source = own["sourceSampleRange"]
    output = row["outputSampleRange"]
    own_output = own["outputSampleRange"]
    covered_output = covered["outputSampleRange"]
    seam = row["seamSample"]
    if row["role"] == "j-cut-handle":
        valid = (output["endSampleExclusive"] == seam
                 == own_output["startSample"]
                 == covered_output["endSampleExclusive"]
                 and output["startSample"]
                 >= covered_output["startSample"]
                 and source["endSampleExclusive"] == own_source["startSample"])
    else:
        valid = (output["startSample"] == seam
                 == own_output["endSampleExclusive"]
                 == covered_output["startSample"]
                 and output["endSampleExclusive"]
                 <= covered_output["endSampleExclusive"]
                 and source["startSample"] == own_source["endSampleExclusive"])
    if not valid:
        raise DialogueAuthorityError(
            "L/J handle boundaries do not share the declared seam")


def validate_segments(rows: list[dict], total_samples: int) -> None:
    """Prove ordering, identity, primary non-overlap, and handle topology."""
    if not rows:
        raise DialogueAuthorityError("dialogue segments must be non-empty")
    if rows != sorted(rows, key=segment_sort_key):
        raise DialogueAuthorityError("dialogue segments are not canonically ordered")
    ids = [row["dialogueSegmentId"] for row in rows]
    if len(set(ids)) != len(ids):
        raise DialogueAuthorityError("dialogue segment IDs must be unique")
    if any(row["outputSampleRange"]["endSampleExclusive"] > total_samples
           for row in rows):
        raise DialogueAuthorityError("dialogue segment exceeds program samples")
    primary_rows = [row for row in rows if row["role"] == "primary"]
    primaries = {row["cutSegmentId"]: row for row in primary_rows}
    if len(primaries) != len(primary_rows):
        raise DialogueAuthorityError("cut segments require one primary dialogue span")
    ordered = sorted(primary_rows, key=segment_sort_key)
    if any(left["outputSampleRange"]["endSampleExclusive"]
           > right["outputSampleRange"]["startSample"]
           for left, right in zip(ordered, ordered[1:])):
        raise DialogueAuthorityError("primary dialogue spans cannot overlap")
    handles = [(row["cutSegmentId"], row["role"]) for row in rows
               if row["role"] != "primary"]
    if len(handles) != len(set(handles)):
        raise DialogueAuthorityError("a cut segment cannot repeat one handle role")
    for row in rows:
        if row["role"] != "primary":
            _handle_checks(row, primaries)


def parse_header(row: dict, kind: str) -> tuple[dict, ProjectClock]:
    """Parse the exact project clock and common authority bindings."""
    if row["schemaVersion"] != 1 or row["kind"] != kind:
        raise DialogueAuthorityError(f"{kind} version/kind is unsupported")
    fps = rational(row["projectFps"], f"{kind}.projectFps")
    sample_rate = safe_integer(
        row["projectSampleRate"], f"{kind}.projectSampleRate", 1)
    clock = ProjectClock(fps, sample_rate)
    frames = safe_integer(
        row["totalOutputFrames"], f"{kind}.totalOutputFrames", 1)
    samples = safe_integer(
        row["totalOutputSamples"], f"{kind}.totalOutputSamples", 1)
    if clock.sample_at_frame(frames) != samples:
        raise DialogueAuthorityError(
            "total output samples do not equal exact B(total frames)")
    parsed = {
        "schemaVersion": 1, "kind": kind,
        "sourceSnapshotSetHash": sha256(
            row["sourceSnapshotSetHash"], f"{kind}.sourceSnapshotSetHash"),
        "pictureTimelineMapHash": sha256(
            row["pictureTimelineMapHash"], f"{kind}.pictureTimelineMapHash"),
        "projectFps": fps.to_dict(), "projectSampleRate": sample_rate,
        "totalOutputFrames": frames, "totalOutputSamples": samples,
        "maxAbsoluteSpeedDeviation": rational(
            row["maxAbsoluteSpeedDeviation"],
            f"{kind}.maxAbsoluteSpeedDeviation").to_dict(),
    }
    return parsed, clock


def derive_mapping(row: dict, clock: ProjectClock,
                   tolerance: PositiveRational) -> tuple[SampleRange, PositiveRational]:
    """Derive normalized bounds/effective speed and enforce tolerance."""
    source = row["sourceSampleRange"]
    try:
        normalized = SampleRange(
            clock.normalize_source_sample(
                source["startSample"], row["sourceSampleRate"]),
            clock.normalize_source_sample(
                source["endSampleExclusive"], row["sourceSampleRate"]))
    except TimingContractError as exc:
        raise DialogueAuthorityError(
            "source span collapses on the project sample clock") from exc
    output = row["outputSampleRange"]
    effective = Fraction(
        normalized.length,
        output["endSampleExclusive"] - output["startSample"])
    if abs(effective - rational(row["speed"], "speed").fraction) \
            > tolerance.fraction:
        raise DialogueAuthorityError(
            "effective dialogue speed exceeds the frozen tolerance")
    return normalized, PositiveRational(
        effective.numerator, effective.denominator)


def parse_dialogue_track(value: object) -> dict:
    """Parse and return canonical ``DialogueTrackV1`` authority."""
    row = object_value(value, "DialogueTrackV1")
    exact_keys(row, TRACK_KEYS, TRACK_KEYS, "DialogueTrackV1")
    parsed, clock = parse_header(row, "dialogue-track")
    value_rows = row["segments"]
    if not isinstance(value_rows, list):
        raise DialogueAuthorityError("DialogueTrackV1.segments must be an array")
    segments = [parse_segment(item, f"segments[{index}]")
                for index, item in enumerate(value_rows)]
    validate_segments(segments, parsed["totalOutputSamples"])
    tolerance = rational(
        parsed["maxAbsoluteSpeedDeviation"], "maximum speed deviation")
    for segment in segments:
        derive_mapping(segment, clock, tolerance)
    return {**parsed, "segments": segments}
