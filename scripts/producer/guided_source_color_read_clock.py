"""Borrow an original opening or wall-bound body clock for source evidence.

This adapter creates no clock, phase, work allowance or native authority. Body
reads must use their already-bound actual BodyExecutionClock: calling the base
OpeningExecutionClock.remaining directly would lose the body's wall watermark.
Exact types and instance fields reject custom callbacks and clock subclasses.
The entry holder separately retains the original cutoff and monotone watermark.
"""
from __future__ import annotations

import math

from guided_body_execution import BodyExecutionClock
from guided_opening_execution import OpeningExecutionClock


def source_color_read_clock_fields(clock: OpeningExecutionClock) -> tuple:
    """Return immutable clock identity, never a new or rounded deadline.

    Args:
        clock: The existing opening clock or already wall-bound body clock.

    Returns:
        Original object, cutoff and event-list identities plus body wall bound.
    """
    fields = {"end", "events"}
    if type(clock) is BodyExecutionClock:
        fields |= {"wall_deadline_ms", "previous_wall_ms"}
    elif type(clock) is not OpeningExecutionClock:
        raise RuntimeError("source-color read requires its exact original clock")
    if set(vars(clock)) != fields or type(clock.events) is not list \
            or type(clock.end) not in (int, float) or not math.isfinite(clock.end):
        raise RuntimeError("source-color read original clock fields changed")
    if type(clock) is OpeningExecutionClock:
        return id(clock), clock.end, id(clock.events)
    if type(clock.wall_deadline_ms) is not int or type(clock.previous_wall_ms) is not int \
            or not 0 <= clock.previous_wall_ms < clock.wall_deadline_ms:
        raise RuntimeError("source-color body read needs its original bound wall clock")
    return id(clock), clock.end, id(clock.events), clock.wall_deadline_ms


def source_color_read_wall(clock: OpeningExecutionClock) -> int | None:
    """Expose only the original body watermark for the entry's nondecrease check."""
    source_color_read_clock_fields(clock)
    return clock.previous_wall_ms if type(clock) is BodyExecutionClock else None


def advance_source_color_read_wall(clock: OpeningExecutionClock, previous: int | None) -> int | None:
    """Retain every actual sampled watermark before later filesystem work can run."""
    current = source_color_read_wall(clock)
    if previous is not None and (current is None or current < previous):
        raise RuntimeError("source-color read original body wall watermark moved backwards")
    return current


def source_color_read_remaining(clock: OpeningExecutionClock) -> float:
    """Use original class behavior, preserving BOTH body wall and monotonic time.

    Args:
        clock: The exact same clock supplied to the initial source read entry.

    Returns:
        Its current decreasing remainder; no additional allowance is created.
    """
    source_color_read_clock_fields(clock)
    if type(clock) is BodyExecutionClock:
        remaining = BodyExecutionClock.remaining(clock)
    else:
        remaining = OpeningExecutionClock.remaining(clock)
    source_color_read_clock_fields(clock)
    return remaining
