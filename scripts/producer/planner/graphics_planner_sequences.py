"""Retired house-template planner entry points.

Kept as explicit migration errors for callers of older command APIs. Production
source selection lives in graphics.visual_source_policy and the upstream catalog.
"""
from __future__ import annotations


def _retired(*args: object, **kwargs: object) -> None:
    """Refuse old style selection instead of substituting another design."""
    raise ValueError("Legacy visual presets are retired; select the HyperFrames catalog in a native project")


sequence_beats = _retired
