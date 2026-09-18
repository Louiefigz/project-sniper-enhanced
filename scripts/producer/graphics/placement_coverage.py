"""Exact, validated coverage partitions for post-composite placement checks."""
from __future__ import annotations

import math
from dataclasses import dataclass


OCCLUSION_REASONS = {
    "broll": "brollTrack replaces the frames in the window — no face to clear",
    "cards": "hook-card overlay occupies the window — card occupancy is unmodeled",
}


@dataclass(frozen=True)
class PlacementSpan:
    """One half-open interval, with an exemption reason only when covered."""

    start: float
    end: float
    reason: str | None = None


def _bounds(value: object, label: str) -> tuple[float, float]:
    """Reject malformed intervals instead of converting them to probe skips."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{label} must have exactly two numeric bounds")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in value):
        raise ValueError(f"{label} bounds must be numbers, not booleans or strings")
    start, end = float(value[0]), float(value[1])
    if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
        raise ValueError(f"{label} needs finite, nonnegative, increasing bounds")
    return start, end


def _windows(occlusions: dict | None) -> list[PlacementSpan]:
    """Validate all recognized occlusion rows before any measurement runs."""
    if occlusions is None:
        return []
    if not isinstance(occlusions, dict):
        raise ValueError("placement occlusions must be an object")
    windows: list[PlacementSpan] = []
    for key, reason in OCCLUSION_REASONS.items():
        rows = occlusions.get(key, [])
        if not isinstance(rows, list):
            raise ValueError(f"placement {key} occlusions must be a list")
        windows.extend(PlacementSpan(*_bounds(row, key), reason) for row in rows)
    return windows


def _partition(bounds: tuple[float, float],
               windows: list[PlacementSpan]) -> list[PlacementSpan]:
    """Union coverage without dropping positive gaps or double-counting spans."""
    start, end = bounds
    if start == end:
        return [PlacementSpan(start, end)]
    overlapping = [w for w in windows if w.start < end and w.end > start]
    edges = {start, end}
    for window in overlapping:
        edges.update((max(start, window.start), min(end, window.end)))
    ordered = sorted(edges)
    result: list[PlacementSpan] = []
    for left, right in zip(ordered, ordered[1:]):
        reason = next((w.reason for w in overlapping
                       if w.start <= left and w.end >= right), None)
        if result and result[-1].reason == reason:
            result[-1] = PlacementSpan(result[-1].start, right, reason)
            continue
        result.append(PlacementSpan(left, right, reason))
    return result


def _rendered_window(window: PlacementSpan) -> PlacementSpan:
    """Match the current compositor's b-roll/card decimal precision."""
    precision = 6 if window.reason == OCCLUSION_REASONS["broll"] else 4
    return PlacementSpan(float(f"{window.start:.{precision}f}"),
                         float(f"{window.end:.{precision}f}"), window.reason)


def placement_spans(clip: dict, occlusions: dict | None,
                    rendered: bool = False) -> list[PlacementSpan]:
    """Partition a graphic into exact exempt and still-unverified intervals.

    Args:
        clip: Graphic record carrying output bounds and optional PiP-hole data.
        occlusions: Recognized b-roll/title-card windows; inputs remain unchanged.
        rendered: Match the current FFmpeg overlay boundary serialization.

    Returns:
        Ordered, nonoverlapping spans covering the entire graphic duration.
    """
    bounds = _bounds([clip.get("outStart"), clip.get("outEnd")], "graphic")
    windows = _windows(occlusions)
    if clip.get("pipHole"):
        return [PlacementSpan(*bounds, "pip_hole comp — the footage face lives "
                              "inside the transparent hole; face clearance is inapplicable")]
    if rendered:
        bounds = tuple(float(f"{value:.4f}") for value in bounds)
        windows = [_rendered_window(window) for window in windows]
    return _partition(bounds, windows)
