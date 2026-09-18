#!/usr/bin/env python3
"""Normalize full-canvas overlay geometry to the delivery resolution.

Hyperframes compositions author against a canonical canvas (for example,
1920x1080), while a source-preserving longform delivery can be 3840x2160.
FFmpeg's overlay filter never scales the overlay implicitly. This module keeps
the clip and every authored placement datum in one coordinate system.

Only same-aspect canvases are normalized. A non-explicit face anchor fails
closed because its chosen free-space region may already be expressed in
delivery pixels; multiplying that offset would silently double-scale it.
"""

from __future__ import annotations

import math

from planner.graphics_anchors import FACE_ANCHORS, _clip_dims, _content_bbox


def _scale_geometry(values: list, sx: float, sy: float) -> list:
    """Scale an xy pair or xyxy box from authored to delivery pixels."""
    factors = (sx, sy) if len(values) == 2 else (sx, sy, sx, sy)
    return [int(round(float(value) * factors[idx]))
            for idx, value in enumerate(values)]


def _scaled_dims(values: list, sx: float, sy: float) -> list[int]:
    """Scale video dimensions and retain ffmpeg's mod-2 requirement."""
    return [max(2, int(round(float(values[0]) * sx / 2.0)) * 2),
            max(2, int(round(float(values[1]) * sy / 2.0)) * 2)]


def _pixel_pair(value: object) -> tuple[int, int] | None:
    """Validate an internal width/height metadata pair."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    if any(isinstance(item, bool) or not isinstance(item, (int, float))
           or not math.isfinite(float(item)) or float(item) <= 0
           for item in value):
        return None
    return int(value[0]), int(value[1])


def _delivery_resolved(meta: dict, authored: tuple,
                       delivery: tuple) -> bool:
    """Whether automatic placement is proven to use delivery coordinates."""
    if _pixel_pair(meta.get("canvas")) != delivery:
        return False
    if _pixel_pair(meta.get("authoredCanvas")) != authored:
        return False
    scaled = _pixel_pair(meta.get("scaledDims"))
    return scaled is not None and scaled[0] <= delivery[0] \
        and scaled[1] <= delivery[1]


def own_screen_meta(comp_dims: tuple, video_dims: tuple) -> tuple:
    """Full-frame own-screen takeover geometry: ``(0, 0, meta)``.

    The comp must match the delivery aspect (0.002 tolerance — the same
    predicate ``comp_measure`` mirrors at plan time); a mismatch raises.
    """
    comp_w, comp_h = comp_dims
    video_w, video_h = video_dims
    if abs(comp_w / comp_h - video_w / video_h) > 0.002:
        raise ValueError(
            f"own-screen comp {comp_w}x{comp_h} does not match delivery "
            f"aspect {video_w}x{video_h}")
    meta = {"anchor": "own-screen", "region": "full-frame", "fallback": False,
            "contentBBox": [0, 0, comp_w, comp_h],
            "placedBBox": [0, 0, video_w, video_h],
            "canvas": [video_w, video_h]}
    if (comp_w, comp_h) != (video_w, video_h):
        meta["scaledDims"] = [video_w, video_h]
    return 0, 0, meta


def fit_delivery_geometry(mov_path: str, offset: tuple[int, int], meta: dict,
                          delivery: tuple[int, int]) -> tuple[int, int, dict]:
    """Scale a same-aspect full-canvas overlay and its placement geometry.

    Args:
        mov_path: Rendered composition path whose stream defines authored size.
        offset: Overlay x/y in authored-canvas pixels.
        meta: Placement metadata; explicit coordinates and bboxes share that
            authored coordinate system.
        delivery: Output video width/height.

    Returns:
        Delivery-space x, y, and copied placement metadata. Equal-size and
        different-aspect inputs are returned untouched.

    Raises:
        ValueError: If a face-relative automatic placement would need a fresh
            delivery-space fit rather than safe scalar normalization.
    """
    if meta.get("anchor") == "own-screen":
        return offset[0], offset[1], meta
    authored = _clip_dims(mov_path)
    if authored == delivery:
        return offset[0], offset[1], meta
    automatic_face = (
        (meta.get("anchor") in FACE_ANCHORS or meta.get("faceAware"))
        and meta.get("region") != "explicit-placement"
    )
    if automatic_face and _delivery_resolved(meta, authored, delivery):
        result = dict(meta)
        result["canvasScale"] = [
            delivery[0] / authored[0], delivery[1] / authored[1]]
        return offset[0], offset[1], result
    if automatic_face:
        raise ValueError(
            "face-relative overlay canvas differs from delivery; placement must "
            "be resolved with a delivery-sized footprint")
    if abs(authored[0] / authored[1] - delivery[0] / delivery[1]) > 0.002:
        return offset[0], offset[1], meta
    sx, sy = delivery[0] / authored[0], delivery[1] / authored[1]
    result = dict(meta)
    result.update(authoredCanvas=list(authored), canvas=list(delivery),
                  canvasScale=[sx, sy],
                  scaledDims=_scaled_dims(
                      result.get("scaledDims", list(authored)), sx, sy))
    for key in ("contentBBox", "placedBBox", "placement"):
        values = result.get(key)
        if isinstance(values, list) and len(values) in (2, 4):
            result[key] = _scale_geometry(values, sx, sy)
    return int(round(offset[0] * sx)), int(round(offset[1] * sy)), result


def fallback_placement_evidence(mov_path: str, offset: tuple[int, int],
                                meta: dict, canvas: tuple[int, int]) -> dict:
    """Measure landed alpha geometry when placement fell back to v1."""
    if meta.get("placedBBox"):
        return meta
    try:
        bbox = _content_bbox(mov_path)
        authored = _clip_dims(mov_path)
    except (RuntimeError, OSError, ImportError, ValueError):
        return meta
    if abs(authored[0] / authored[1] - canvas[0] / canvas[1]) > 0.002:
        return meta
    sx, sy = canvas[0] / authored[0], canvas[1] / authored[1]
    scaled = [bbox[0] * sx, bbox[1] * sy, bbox[2] * sx, bbox[3] * sy]
    x, y = offset
    result = dict(meta)
    result["contentBBox"] = [int(round(value)) for value in scaled]
    result["placedBBox"] = [int(round(scaled[0] + x)),
                            int(round(scaled[1] + y)),
                            int(round(scaled[2] + x)),
                            int(round(scaled[3] + y))]
    return result
