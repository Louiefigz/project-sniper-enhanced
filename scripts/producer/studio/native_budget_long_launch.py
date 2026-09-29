"""A Long launch's by-name waits: the mixed-forecast deferral and the latest start its refusals name.

Split from ``native_budget_launch`` (MASTER-PLAN §5, at M-059) with the function text unchanged.
``native_budget_launch.admit_launch`` calls ``_long_deferral`` once the forecast admits a Long launch
and names ``long_latest_start`` in each Long refusal; later Long-area edits to either land here.
This module never imports ``native_budget_launch`` at run time (the launch type is for annotations only).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from studio.native_budget_forecast import service_allowance
from studio.production.formats import clip_deadlines, long_latest_starts, output_format

if TYPE_CHECKING:
    from studio.native_budget_launch import LaunchRequest


def _long_deferral(record: dict, launch: LaunchRequest, elapsed: float, facts: object | None = None) -> str | None:
    """A Long launch waits while holding a slot now would make a committed Short newly miss (never preempted)."""
    clip = record['clips'][launch.clip_id]
    if output_format(clip) != 'long':
        return None
    from studio.production.mixed_forecast import long_launch_refusal
    inputs = facts.mixed_inputs(record, elapsed) if facts is not None else None
    refusal = long_launch_refusal(record, launch, elapsed, inputs)
    return f'{refusal} {long_latest_start(record, clip, launch)}' if refusal else None


def long_latest_start(record: dict, clip: dict, launch: LaunchRequest) -> str:
    """A refused Long launch's latest start (``formats.long_latest_starts``, queue excluded) and its grant end."""
    members = launch.following_members if launch.route == 'preview' else launch.family_members
    starts = long_latest_starts(clip_deadlines(record, clip), launch.output_seconds, launch.family_work, members)
    service = service_allowance(clip, launch.route, launch.service_seconds)
    starts['latestPreviewStart'] -= service
    starts['latestFinalStart'] -= service
    key = 'latestPreviewStart' if launch.route == 'preview' else 'latestFinalStart'
    minute = (starts[key] - clip['output']['authorizedElapsed']) / 60
    return (f'Its latest {launch.route} start is {starts[key]:.0f}s (minute {minute:.1f} of this Long\'s own clock, '
            f'queue excluded; {starts["previewBasis"]}); its grant ends at {starts["grantEnd"]:.0f}s and is never '
            'extended.')
