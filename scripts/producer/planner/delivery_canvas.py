#!/usr/bin/env python3
"""Resolve the pixel canvas the render pipeline will actually deliver."""

from __future__ import annotations

import math

from producer_config import CANVAS_BY_ASPECT, MODES


def delivery_strategy(plan: dict) -> str:
    """Return the effective reframe strategy for a plan."""
    mode = (plan.get("target") or {}).get("mode")
    if mode not in MODES:
        raise ValueError(f"unknown target mode {mode!r}")
    reframe = plan.get("reframe") or {}
    return str(reframe.get("strategy", MODES[mode]["reframe_default"]))


def canonical_canvas(plan: dict) -> tuple[int, int]:
    """Return the configured mode canvas."""
    mode = (plan.get("target") or {}).get("mode")
    if mode not in MODES:
        raise ValueError(f"unknown target mode {mode!r}")
    aspect = MODES[mode]["aspect"]
    canvas = CANVAS_BY_ASPECT[aspect]
    return int(canvas["width"]), int(canvas["height"])


def canvas_aspect(canvas: tuple) -> str:
    """Match a positive canvas to a configured aspect, or fail closed."""
    if len(canvas) != 2:
        raise ValueError(f"canvas must be (width, height), got {canvas!r}")
    width, height = (float(value) for value in canvas)
    if not all(math.isfinite(value) and value > 0 for value in (width, height)):
        raise ValueError(f"canvas dimensions must be positive and finite: {canvas!r}")
    ratio = width / height
    candidates = {
        name: abs(ratio - row["width"] / row["height"])
        for name, row in CANVAS_BY_ASPECT.items()
    }
    aspect = min(candidates, key=candidates.get)
    if candidates[aspect] > 0.01:
        raise ValueError(f"unsupported delivery aspect for canvas {canvas!r}")
    return aspect


def _source_canvas(source: dict) -> tuple[int, int]:
    """Manifest source resolution adjusted for display rotation."""
    resolution = source.get("resolution")
    valid = (
        isinstance(resolution, (list, tuple))
        and len(resolution) == 2
        and all(isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(float(value))
                and float(value) > 0 for value in resolution)
    )
    if not valid:
        raise ValueError(
            f"source {source.get('id')!r} has no valid resolution")
    width, height = int(resolution[0]), int(resolution[1])
    rotation = int(float(source.get("rotation", 0) or 0)) % 360
    return (height, width) if rotation in (90, 270) else (width, height)


def resolve_delivery_canvas(plan: dict, manifest: dict) -> tuple[int, int]:
    """Return canonical reframed pixels or the native stage-1 source profile."""
    if delivery_strategy(plan) != "none":
        return canonical_canvas(plan)
    from compile_timeline import compile_plan

    timeline = compile_plan(plan)
    if not timeline.segments:
        raise ValueError("plan compiles to zero segments")
    first_id = timeline.segments[0].source_id
    source = next(
        (row for row in manifest.get("sources", [])
         if row.get("id") == first_id),
        None,
    )
    if source is None:
        raise ValueError(f"source {first_id!r} is missing from manifest")
    return _source_canvas(source)
