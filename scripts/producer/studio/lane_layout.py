"""Greedy interval-to-lane assignment for the Studio review timeline.

Track index is a TEMPORAL lane only (same-lane clips must not overlap in
time — Studio lint enforces it); paint order comes from the explicit z-index
each slot carries. Base footage owns track 0; sub-comp clips start at 1.
"""
from __future__ import annotations

from dataclasses import dataclass

from studio import StudioProjectError

FIRST_TRACK = 1
_Z_STEP = 10
_EPS = 1e-6


@dataclass(frozen=True)
class LaneSlot:
    """One clip's temporal lane and paint order."""

    track: int
    z_index: int


def z_for_track(track: int) -> int:
    """Deterministic paint order: later lanes stack above earlier ones."""
    return _Z_STEP * (track - FIRST_TRACK + 1)


def assign_lanes(windows: list[tuple[float, float]]) -> list[LaneSlot]:
    """Assign each ``(start, end)`` window the lowest non-overlapping lane.

    Windows are processed in start order (stable on ties) but the result is
    aligned to the input order, so callers can zip it with their entries.
    """
    for i, (start, end) in enumerate(windows):
        if not end > start:
            raise StudioProjectError(
                f"window[{i}]: non-positive span [{start}, {end}]")
    lane_ends: list[float] = []
    slots: list[LaneSlot | None] = [None] * len(windows)
    order = sorted(range(len(windows)), key=lambda i: (windows[i][0], i))
    for i in order:
        start, end = windows[i]
        lane = next((j for j, busy_until in enumerate(lane_ends)
                     if start >= busy_until - _EPS), None)
        if lane is None:
            lane = len(lane_ends)
            lane_ends.append(end)
        else:
            lane_ends[lane] = end
        track = FIRST_TRACK + lane
        slots[i] = LaneSlot(track=track, z_index=z_for_track(track))
    return [slot for slot in slots if slot is not None]
