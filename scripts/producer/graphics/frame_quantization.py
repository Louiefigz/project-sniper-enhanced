"""Shared positive-time frame quantization for graphics media."""
from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction


def rounded_frame_index(seconds: float, fps: float) -> int:
    """Match HyperFrames/JavaScript half-up rounding at positive frame ties."""
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("frame time must be finite and non-negative")
    if not math.isfinite(fps) or fps <= 0:
        raise ValueError("frame rate must be finite and positive")
    frames = Decimal(str(seconds)) * Decimal(str(fps))
    return int(frames.to_integral_value(rounding=ROUND_HALF_UP))


def placement_frame_span(start: float, end: float, fps: float) -> int:
    """Return the positive ``[round(start*fps), round(end*fps))`` span."""
    first = rounded_frame_index(start, fps)
    last = rounded_frame_index(end, fps)
    if last <= first:
        raise ValueError("graphic window must occupy at least one timeline frame")
    return last - first


def quantized_window_end(start: float, frame_count: int, fps: float) -> float:
    """Represent ``start + frame_count/fps`` without crossing a round tie."""
    target = rounded_frame_index(start, fps) + frame_count
    end = start + frame_count / fps
    for _attempt in range(8):
        actual = rounded_frame_index(end, fps)
        if actual == target:
            return end
        end = math.nextafter(end, math.inf if actual < target else 0.0)
    raise RuntimeError("cannot represent an exact graphics timeline endpoint")


def hyperframes_duration(frame_count: int, fps: float) -> float:
    """Duration whose HyperFrames ``ceil(duration * fps)`` is frame_count.

    The one-ULP inward bias prevents a floating-point quotient just above the
    upper edge from producing an extra frame. It is far below media timestamp
    precision and preserves the logical duration of ``frame_count / fps``.
    """
    if type(frame_count) is not int or frame_count <= 0:
        raise ValueError("graphic frame count must be a positive integer")
    if not math.isfinite(fps) or fps <= 0:
        raise ValueError("frame rate must be finite and positive")
    duration = math.nextafter(frame_count / fps, 0.0)
    if math.ceil(duration * fps) != frame_count:
        raise RuntimeError("cannot represent an exact HyperFrames frame duration")
    return duration


def require_graphic_frame_clock(value: object, actual: tuple[object, int]) -> tuple[str, int]:
    """Require an explicit rational clock equal to the held/observed full base."""
    if type(value) is not tuple or len(value) != 2:
        raise ValueError("exact graphic frame clock must be a rate/frame-count pair")
    token, frames = value
    if type(token) is not str or not token or type(frames) is not int or not 0 < frames < 2**53:
        raise ValueError("exact graphic frame clock is malformed")
    try:
        rate = Fraction(token)
        matches = rate > 0 and math.isfinite(float(rate)) and rate == Fraction(actual[0])
    except (ValueError, TypeError, ZeroDivisionError, OverflowError) as error:
        raise ValueError("exact graphic frame clock has an invalid rate") from error
    if not matches or type(actual[1]) is not int or frames != actual[1]:
        raise ValueError("exact graphic frame clock differs from the actual held base")
    return str(rate), frames


def bind_graphic_frame_windows(rows: list[dict], clock: tuple[str, int]) -> list[dict]:
    """Copy existing clip/plan rows with the same approved half-up endpoint map."""
    rate, frames = require_graphic_frame_clock(clock, clock)
    return [_bind_graphic_window(row, (float(Fraction(rate)), frames)) for row in rows]


def _bind_graphic_window(row: dict, clock: tuple[float, int]) -> dict:
    """Reject empty/outside windows instead of hiding a requested graphic."""
    fps, total = clock
    values = row.get("outStart"), row.get("outEnd")
    if any(type(value) not in (int, float) for value in values):
        raise ValueError("exact graphic frame window requires numeric plan times")
    start, end = (rounded_frame_index(value, fps) for value in values)
    if end <= start or end > total:
        raise ValueError("exact graphic frame window is empty or outside the held base")
    expected = {"startFrame": start, "endFrameExclusive": end}
    if any(key in row and (type(row[key]) is not int or row[key] != value) for key, value in expected.items()):
        raise ValueError("exact graphic frame window contradicts its plan times")
    return {**row, **expected}
