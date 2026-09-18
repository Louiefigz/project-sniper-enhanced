#!/usr/bin/env python3
"""comp_measure_rules — the comp-size gate's geometry verdict rules (v3 #2).

Split from :mod:`graphics.comp_measure` (300-line logic ceiling): this module
owns the PER-CLASS geometry checks a measured comp bbox is judged against —
own-screen delivery-aspect match, SAFE_BOX fit for the free-space-placed
class (the LL-035 class), and on-canvas containment for explicit placements.
Render/measure orchestration (cache probe, budget, CLI) stays in
``comp_measure``. The gate identity and its FAIL default are registered HERE
because every verdict this module builds carries them.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # run-by-path: producer pkg root on sys.path

import gate_policy
from gate_policy import Verdict
from planner.graphics_anchors import _clip_dims, scale_geometry
from producer_config import CANVAS_BY_ASPECT, COMP_MEASURE, MODES, SAFE_BOX

GATE = "comp_size"
gate_policy.register_gate(GATE, "FAIL")

# stage_placement's own-screen delivery-aspect tolerance — mirrored so the
# lint's predicate IS the composite's predicate.
_ASPECT_TOL = 0.002


@dataclass(frozen=True)
class _EntryCtx:
    """Per-entry verdict context (tag for evidence, plan mode for routing)."""

    tag: str
    mode: Optional[str]


def _delivery_canvas(mode: Optional[str]) -> tuple:
    """(width, height) of the mode's delivery canvas (9:16 when unknown)."""
    aspect = MODES.get(mode or "", {}).get("aspect", "9:16")
    canvas = CANVAS_BY_ASPECT[aspect]
    return canvas["width"], canvas["height"]


def _ownscreen_verdicts(ctx: _EntryCtx, dims: tuple) -> list:
    """Own-screen takeover: comp canvas must match the delivery aspect.

    Mirrors the ``stage_placement.resolve_placement`` render-time raise (same
    0.002 tolerance) so the mismatch fails at lint instead of mid-composite.
    """
    video_w, video_h = _delivery_canvas(ctx.mode)
    if abs(dims[0] / dims[1] - video_w / video_h) <= _ASPECT_TOL:
        return []
    return [Verdict(GATE, "FAIL", (
        f"{ctx.tag}: own-screen comp {dims[0]}x{dims[1]} does not match the "
        f"{video_w}x{video_h} delivery aspect — the composite will refuse it"),
        lane="graphics", mode=ctx.mode)]


def _free_verdicts(ctx: _EntryCtx, bbox: tuple, dims: tuple) -> list:
    """SAFE_BOX fit check for the free-space-placed class (the LL-035 class).

    Content that cannot fit the SAFE_BOX-clamped legal area under ANY
    translation is unplaceable — FAIL with the measured numbers. Designed
    full-bleed treatments (>= ``full_bleed_frac`` of the canvas in BOTH
    dimensions) are exempt; SAFE_BOX applies to 9:16-authored comps only.
    """
    width, height = dims
    content_w = bbox[2] - bbox[0] + 1
    content_h = bbox[3] - bbox[1] + 1
    frac = COMP_MEASURE["full_bleed_frac"]
    if content_w >= width * frac and content_h >= height * frac:
        return []
    nine16 = CANVAS_BY_ASPECT["9:16"]
    if (width, height) != (nine16["width"], nine16["height"]):
        return []
    legal_w = width - SAFE_BOX["left"] - SAFE_BOX["right"]
    legal_h = height - SAFE_BOX["top"] - SAFE_BOX["bottom"]
    if content_w <= legal_w and content_h <= legal_h:
        return []
    return [Verdict(GATE, "FAIL", (
        f"{ctx.tag}: measured content {content_w}x{content_h}px (bbox "
        f"{list(bbox)}) cannot fit the SAFE_BOX legal area {legal_w}x{legal_h}px "
        f"of the {width}x{height} canvas — no legal placement exists "
        "(LL-035 class)"), lane="graphics", mode=ctx.mode)]


def _placed_verdicts(entry: dict, bbox: tuple, path: str,
                     ctx: _EntryCtx) -> list:
    """Explicit-placement class: the pinned content must stay on the canvas.

    Uses the SAME math as ``stage_placement._explicit_offset`` (content
    top-left pinned at {x, y}; ``scale_geometry`` for a scaled pin) with the
    MEASURED bbox. SAFE_BOX taste stays ``plan_lint_motion``'s WARN — this
    gate fails only when pixels would leave the delivery canvas entirely.
    """
    pin = entry["placement"]
    x, y = float(pin["x"]), float(pin["y"])
    scale = float(pin.get("scale") or 1.0)
    if scale == 1.0:
        dx, dy = x - bbox[0], y - bbox[1]
        placed = (bbox[0] + dx, bbox[1] + dy, bbox[2] + dx, bbox[3] + dy)
    else:
        placed = scale_geometry(bbox, (x, y), _clip_dims(path), scale)["placed"]
    video_w, video_h = _delivery_canvas(ctx.mode)
    inside = (placed[0] >= 0 and placed[1] >= 0
              and placed[2] <= video_w and placed[3] <= video_h)
    if inside:
        return []
    return [Verdict(GATE, "FAIL", (
        f"{ctx.tag}: placed content bbox "
        f"[{placed[0]:.0f}, {placed[1]:.0f}, {placed[2]:.0f}, {placed[3]:.0f}] "
        f"exceeds the {video_w}x{video_h} delivery canvas — pixels would be "
        "clipped off-screen (LL-035 class)"), lane="graphics", mode=ctx.mode)]
