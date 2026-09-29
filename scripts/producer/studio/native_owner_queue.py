"""Queue native owners in the host pool instead of failing on a busy slot.

An owner that refused immediately before (capacity_wait_seconds=0) gains the pool's
bounded queue allowance on top of its unchanged work deadline. The owner's single
monotonic clock (owner.started + owner.deadline) still bounds queue and work together,
so a queue can never consume the work allowance silently and nothing resets it.
Owners that already queue (Long, preview sections, inspections) keep their bounds.
Preview packaging is ffmpeg-only and uses the 'audio' class so it never waits behind
browser renders.
"""
from __future__ import annotations

from dataclasses import replace

from native_work_pool_policy import QUEUE_SECONDS
from studio.native_run_config import NativeRunConfig


def queued_owner(settings: NativeRunConfig, lane: str | None = None,
                 remaining: float | None = None) -> NativeRunConfig:
    """Give an immediate-refusal owner the bounded FIFO queue and optionally a class.

    Args:
        settings: The owner's existing configuration.
        lane: Pool class to use; defaults to the configured one.
        remaining: Seconds left in the caller's absolute budget, if one applies; the
            owner's combined queue-and-work deadline never exceeds it.

    Returns:
        Settings whose deadline covers QUEUE_SECONDS of waiting plus the original work.
    """
    lane = lane or settings.lane
    if not settings.capacity_wait_seconds:
        settings = replace(settings, deadline=settings.deadline + QUEUE_SECONDS,
                           capacity_wait_seconds=QUEUE_SECONDS, queue_work_seconds=settings.deadline)
    if remaining is not None:
        if not remaining > 0:
            raise RuntimeError('Native owner budget is exhausted before queueing')
        settings = replace(settings, deadline=min(settings.deadline, remaining),
                           capacity_wait_seconds=min(settings.capacity_wait_seconds, remaining))
    return replace(settings, lane=lane)


def pipeline_owner(settings: NativeRunConfig, label: str, remaining: float | None = None) -> NativeRunConfig:
    """Class and queue for one shared Short/Long pipeline owner phase (budget hook: remaining)."""
    from studio.native_preview_sections import section_phase
    section = section_phase(label)
    return queued_owner(settings, 'audio' if section and section[0] == 'package' else 'heavy', remaining)
