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
    if abs(authored[0] / authored[1] - delivery[0] / delivery[1]) > 0.002:
        return offset[0], offset[1], meta
    if meta.get("anchor") in FACE_ANCHORS \
            and meta.get("region") != "explicit-placement":
        raise ValueError(
            "face-relative overlay canvas differs from delivery; placement must "
            "be resolved with a delivery-sized footprint")
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
