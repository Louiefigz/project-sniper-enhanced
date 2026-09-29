"""Output-time resolution for ordinary visual-plan application receipts."""
from __future__ import annotations

import math
from collections.abc import Callable


def cut_windows(plan: dict, error: Callable[[str], None]) \
        -> list[tuple[float, float]]:
    """Compile cut rows into concatenated output-second windows."""
    windows = []
    cursor = 0.0
    for index, row in enumerate(plan.get("cutTrack") or []):
        if not isinstance(row, dict):
            error(f"cutTrack[{index}] must be an object")
            continue
        try:
            start, end = float(row["start"]), float(row["end"])
            speed = float(row.get("speed", 1.0))
        except (KeyError, TypeError, ValueError):
            error(f"cutTrack[{index}] timing is invalid")
            continue
        if not all(math.isfinite(value) for value in (start, end, speed)) \
                or end <= start or speed <= 0:
            error(f"cutTrack[{index}] timing is invalid")
            continue
        duration = (end - start) / speed
        windows.append((cursor, cursor + duration))
        cursor += duration
    return windows


def row_window(lane: str, row: dict,
               cut_window: tuple[float, float] | None) \
        -> tuple[float, float] | None:
    """Resolve one supported ordinary row to output seconds."""
    if lane == "cutTrack":
        return cut_window
    if lane == "transitions":
        point = row.get("outTime")
        if isinstance(point, bool) or not isinstance(point, (int, float)):
            return None
        return float(point), float(point)
    start, end = row.get("outStart"), row.get("outEnd")
    if isinstance(start, bool) or isinstance(end, bool):
        return None
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        return None
    return float(start), float(end)


def timing_matches(lane: str, actual: tuple[float, float],
                   expected: tuple[float, float], tolerance: float) -> bool:
    """Check point, containing-cut, or exact-window timing by lane."""
    start, end = actual
    want_start, want_end = expected
    if not all(math.isfinite(value) for value in actual):
        return False
    if lane == "transitions":
        return want_start - tolerance <= start < want_end + tolerance
    if lane == "cutTrack":
        return start <= want_start + tolerance and end >= want_end - tolerance
    return abs(start - want_start) <= tolerance and abs(end - want_end) <= tolerance
