#!/usr/bin/env python3
"""stage_placement — one graphicsTrack entry's overlay offset resolution.

Split from :mod:`graphics.graphics_stage` (300-line logic ceiling): this
module owns HOW one rendered comp lands on the delivery canvas — the
operator's explicit ``placement`` pin (wins outright, fails loud), the
registered full-canvas rail path, the own-screen full-frame path, and the
Placement v2 anchor resolution with its loudly-declared v1 environment
fallback. Compositing orchestration stays in ``graphics_stage``; the
fail-closed geometry semantics (typed :class:`NoLegalRegion` propagation vs
environment fallback) are UNCHANGED by the split.
"""

from __future__ import annotations

import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # run-by-path: producer pkg root on sys.path

from planner.occupancy import NoLegalRegion
from planner.graphics_anchors import (_clip_dims, _content_bbox,
                                      resolve_offset, resolve_offset_v2,
                                      scale_geometry, valid_face_bbox)
from graphics.delivery_geometry import own_screen_meta as _own_screen_meta
from graphics.placement_verify import declare_env_fallback
from motion.recompose import requires_recompose
from producer_config import PLACEMENT_SCALE


def emit(**fields) -> None:
    """One NDJSON status line on stdout (matches the sibling render stages)."""
    print(json.dumps(fields), flush=True)


def _placement_xy(entry: dict) -> tuple[float, float]:
    """Validate + unpack an entry's explicit ``placement`` — fail loud, never guess.

    Contract: ``placement = {"x": px, "y": px}`` in COMP-CANVAS px (the comp's
    authored 1080x1920 / 1920x1080 canvas). ``fit_delivery_geometry`` scales
    this authored geometry when delivery is a higher same-aspect resolution.
    own-screen takeovers are full-frame and never placed.
    """
    p = entry["placement"]
    if entry.get("anchor", "free-band") == "own-screen":
        raise ValueError("own-screen takeovers are full-frame — placement is illegal")
    if not isinstance(p, dict):
        raise ValueError(f"placement must be an object {{x, y}}; got {p!r}")
    for name in ("x", "y"):
        v = p.get(name)
        if isinstance(v, bool) or not isinstance(v, (int, float)) \
                or not math.isfinite(float(v)):
            raise ValueError(f"placement.{name} must be a finite number; got {v!r}")
    return float(p["x"]), float(p["y"])


def _placement_scale(entry: dict) -> float:
    """Validated ``placement.scale`` (1.0 when absent) — fail loud, never clamp.

    Contract: an optional uniform scale on the rendered comp clip, applied about
    the placement point (the SCALED content bbox top-left stays pinned at
    {x, y}). Bounds are ``PLACEMENT_SCALE`` — the raster-quality band: comps
    raster at their authored canvas, so downscaling stays crisp while upscaling
    interpolates (soft); ≤1.5 keeps that softness invisible at delivery res.
    own-screen is already unplaceable (``_placement_xy``), so it is unscalable.
    """
    s = entry["placement"].get("scale")
    if s is None:
        return 1.0
    if isinstance(s, bool) or not isinstance(s, (int, float)) \
            or not math.isfinite(float(s)):
        raise ValueError(f"placement.scale must be a finite number; got {s!r}")
    lo, hi = PLACEMENT_SCALE["min"], PLACEMENT_SCALE["max"]
    if not lo <= float(s) <= hi:
        raise ValueError(f"placement.scale {float(s):g} outside [{lo},{hi}]")
    return float(s)


def _explicit_offset(entry: dict, mov_path: str) -> tuple[int, int, dict]:
    """Overlay ``(dx, dy)`` pinning the comp's rendered CONTENT top-left at the
    entry's explicit ``placement`` point (comp-canvas px). The operator's drag
    WINS over every anchor heuristic; measurement failure raises (an explicit
    pin must never silently fall back to an anchor guess). An optional
    ``placement.scale`` resizes the clip uniformly about the pin (the scaled
    content top-left stays at {x, y}); absent = the untouched 1.0 path — no
    dims probe, byte-identical offsets and filter graph."""
    x, y = _placement_xy(entry)
    scale = _placement_scale(entry)
    content = _content_bbox(mov_path)
    meta = {"anchor": entry.get("anchor", "free-band"),
            "region": "explicit-placement", "fallback": False,
            "placement": [x, y], "contentBBox": list(content)}
    if scale == 1.0:
        dx, dy = int(round(x - content[0])), int(round(y - content[1]))
        meta["placedBBox"] = [content[0] + dx, content[1] + dy,
                              content[2] + dx, content[3] + dy]
        return dx, dy, meta
    geo = scale_geometry(content, (x, y), _clip_dims(mov_path), scale)
    meta.update(scale=scale, scaledDims=[geo["w"], geo["h"]],
                placedBBox=list(geo["placed"]))
    return geo["dx"], geo["dy"], meta


def _fixed_overlay_offset(entry: dict, mov_path: str) -> tuple[int, int, dict]:
    """Keep a full-canvas edge rail at its authored origin."""
    content = _content_bbox(mov_path)
    meta = {"anchor": entry.get("anchor", "beside-face"),
            "region": "fixed-canvas", "fallback": False,
            "contentBBox": list(content), "placedBBox": list(content)}
    return 0, 0, meta


def _fallback_offset(entry: dict, video_in: str) -> tuple[int, int]:
    """Use delivery-aware v1 geometry when the delivery probe still works."""
    try:
        return resolve_offset(entry, _clip_dims(video_in))
    except (RuntimeError, OSError, ValueError):
        return resolve_offset(entry)


def resolve_placement(entry: dict, mov_path: str, video_in: str,
                      band_y_offset_px: float = 0.0) -> tuple[int, int, dict]:
    """Resolve one entry's overlay offset — explicit placement, else anchors.

    PRECEDENCE: an explicit ``entry.placement`` {x, y} wins outright (see
    ``_explicit_offset``) and never falls back. Otherwise the anchor path is
    UNTOUCHED: Placement v2 measures the frame's free space + the clip's own
    footprint and places it into the emptiest legal region (the fix for
    graphics-on-the-face). If measurement can't run (no cv2, no face + no bbox
    hint, ffmpeg probe fail) it degrades to the v1 deviation nudge and SAYS SO
    — never a silent mis-place.
    """
    anchor = entry.get("anchor", "free-band")
    if anchor == "own-screen" and entry.get("placement") is None:
        return _own_screen_meta(_clip_dims(mov_path), _clip_dims(video_in))
    if entry.get("placement") is not None:
        return _explicit_offset(entry, mov_path)
    if requires_recompose(entry):
        return _fixed_overlay_offset(entry, mov_path)
    try:
        x, y, meta = resolve_offset_v2(entry, mov_path, video_in,
                                       band_y_offset_px)
        return x, y, meta
    except NoLegalRegion:
        # GEOMETRY failure: fail closed (geometry contract v3 #1); the typed
        # evidence routes back into planning via the NDJSON error stream.
        raise
    except (RuntimeError, ValueError, OSError, ImportError, KeyError) as exc:
        if anchor == "free-band" and valid_face_bbox(
                entry.get("faceBBoxNorm")):
            raise RuntimeError(
                "face-aware free-band placement could not be measured; "
                "refusing the authored origin because it may cover the face: "
                f"{type(exc).__name__}: {exc}") from exc
        # ENVIRONMENT failure (no cv2, probe fail, no face + no hint): keep
        # the v1 deviation nudge, declared LOUDLY through gate policy.
        x, y = _fallback_offset(entry, video_in)
        declare_env_fallback(emit, entry, exc)
        return x, y, {"anchor": entry.get("anchor", "free-band"),
                      "region": "v1-fallback", "fallback": True,
                      "reason": str(exc)[:200]}
