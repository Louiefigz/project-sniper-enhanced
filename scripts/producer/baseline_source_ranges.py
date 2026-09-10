#!/usr/bin/env python3
"""Exact half-open source-frame selection for current baseline preparation."""
from __future__ import annotations

import hashlib
import json
import math
import re
from fractions import Fraction
from pathlib import Path

from edit.exact_timing import FrameRange, TimingContractError

_RANGE_LIST = re.compile(
    r"(?:0|[1-9][0-9]*):(?:[1-9][0-9]*)"
    r"(?:,(?:0|[1-9][0-9]*):(?:[1-9][0-9]*))*\Z"
)


def parse_source_frame_ranges(value: str | None) -> tuple[FrameRange, ...] | None:
    """Parse canonical comma-separated half-open ``START:END`` ranges."""
    if value is None:
        return None
    if not _RANGE_LIST.fullmatch(value):
        raise RuntimeError(
            "source frame ranges must be canonical half-open START:END pairs")
    try:
        ranges = tuple(
            FrameRange(*(int(term) for term in token.split(":")))
            for token in value.split(",")
        )
    except TimingContractError as exc:
        raise RuntimeError("source frame ranges must be nonempty") from exc
    _require_ordered(ranges)
    return ranges


def _require_ordered(ranges: tuple[FrameRange, ...]) -> None:
    for previous, current in zip(ranges, ranges[1:]):
        if current.start_frame < previous.end_frame_exclusive:
            raise RuntimeError(
                "source frame ranges must be ordered and non-overlapping")


def frame_seconds(frame: int, rate: tuple[int, int]) -> float:
    """Convert an integer source-frame boundary on an exact rational clock."""
    return float(Fraction(frame * rate[1], rate[0]))


def cut_track(
    source_id: str,
    ranges: tuple[FrameRange, ...],
    rate: tuple[int, int],
) -> list[dict]:
    """Project exact frame boundaries into compatibility plan seconds."""
    return [{
        "sourceId": source_id,
        "start": frame_seconds(item.start_frame, rate),
        "end": frame_seconds(item.end_frame_exclusive, rate),
        "speed": 1.0,
    } for item in ranges]


def source_entry(source: dict, entries: list[dict]) -> dict:
    """Resolve the one admitted source-set entry backing the manifest source."""
    matches = [
        entry for entry in entries
        if entry.get("lane") == "source"
        and entry.get("sha256") == source.get("sourceSha256")
    ]
    if len(matches) != 1:
        raise RuntimeError("baseline source lacks one admitted frame authority")
    return matches[0]


def source_frame_count(project: Path, entry: dict) -> int:
    """Read exact declared frames from the already-verified admission receipt."""
    relative = entry.get("admissionReceiptPath")
    if not isinstance(relative, str):
        raise RuntimeError("baseline source frame authority is malformed")
    lexical = project / relative
    if lexical.is_symlink() or not lexical.is_file():
        raise RuntimeError("baseline source frame authority is unavailable")
    path = lexical.resolve(strict=True)
    try:
        path.relative_to(project)
    except ValueError as exc:
        raise RuntimeError(
            "baseline source frame authority escapes project") from exc
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != entry.get(
            "admissionReceiptSha256"):
        raise RuntimeError("baseline source frame authority hash changed")
    receipt = json.loads(payload)
    facts = ((receipt.get("decoded") or {}).get("facts") or {})
    frames = facts.get("declaredFrames")
    if type(frames) is not int or frames < 1:
        raise RuntimeError("baseline source frame authority lacks declared frames")
    return frames


def validate_source_rate(source: dict, rate: tuple[int, int]) -> None:
    """Require the exact baseline clock to match the admitted CFR metadata."""
    declared = source.get("frameRate")
    expected = Fraction(rate[0], rate[1])
    if declared is not None:
        try:
            observed = Fraction(declared)
        except (TypeError, ValueError, ZeroDivisionError) as exc:
            raise RuntimeError(
                "baseline exact frame rate is malformed") from exc
        if source.get("vfr") is not False or observed != expected:
            raise RuntimeError("baseline FPS does not match admitted CFR source")
        return
    value = source.get("fps")
    exact = float(expected)
    if (
        source.get("vfr") is not False
        or isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) != round(exact, 3)
    ):
        raise RuntimeError("baseline FPS does not match admitted CFR source")


def selected_ranges(
    requested: tuple[FrameRange, ...] | None,
    expected_frames: int,
    available_frames: int,
) -> tuple[FrameRange, ...]:
    """Validate ordering, source bounds, and exact selected-frame total."""
    ranges = requested
    if ranges is None:
        ranges = (FrameRange(0, expected_frames),)
    if (
        not isinstance(ranges, tuple)
        or not ranges
        or any(not isinstance(item, FrameRange) for item in ranges)
    ):
        raise RuntimeError("baseline source frame ranges are malformed")
    _require_ordered(ranges)
    if ranges[-1].end_frame_exclusive > available_frames:
        raise RuntimeError("source frame range exceeds admitted source bounds")
    if sum(item.length for item in ranges) != expected_frames:
        raise RuntimeError("source frame ranges must total baseline frame count")
    return ranges
