#!/usr/bin/env python3
"""Pure face-safe placement solver shared by render-time geometry paths."""

from __future__ import annotations

from dataclasses import dataclass

from planner.eye_trace import region_bias
from planner.free_space import place_content
from producer_config import FREE_SPACE, PLACEMENT_SCALE


@dataclass(frozen=True)
class PlacementSolution:
    """A legal landed footprint and optional uniform comp downscale."""

    region: str
    dx: int
    dy: int
    placed_bbox: tuple[int, int, int, int]
    scale: float = 1.0
    scaled_dims: tuple[int, int] | None = None
    fallback: bool = False


def scale_footprint(content: tuple, authored: tuple,
                    delivery: tuple) -> tuple:
    """Map an authored full-canvas content bbox into delivery pixels."""
    if any(value <= 0 for value in (*authored, *delivery)):
        raise ValueError(
            f"canvas dimensions must be positive: {authored} -> {delivery}")
    if len(content) != 4 or content[2] <= content[0] or content[3] <= content[1]:
        raise ValueError(f"content bbox must have positive area: {content!r}")
    if (content[0] < 0 or content[1] < 0
            or content[2] > authored[0] or content[3] > authored[1]):
        raise ValueError(
            f"content bbox {content!r} leaves authored canvas {authored!r}")
    source_aspect = authored[0] / authored[1]
    delivery_aspect = delivery[0] / delivery[1]
    if abs(source_aspect - delivery_aspect) > 0.002:
        raise ValueError(
            f"authored canvas {authored} does not match delivery {delivery}")
    sx, sy = delivery[0] / authored[0], delivery[1] / authored[1]
    return (content[0] * sx, content[1] * sy,
            content[2] * sx, content[3] * sy)


def _intersects(first: tuple, second: tuple) -> bool:
    """Whether two half-open xyxy rectangles overlap."""
    return (
        max(first[0], second[0]) < min(first[2], second[2])
        and max(first[1], second[1]) < min(first[3], second[3])
    )


def choose_region(free_map, anchor: str, content_bbox: tuple,
                  gaze: tuple | None = None):
    """Choose a full-size region using the established preference contract."""
    width = content_bbox[2] - content_bbox[0]
    height = content_bbox[3] - content_bbox[1]
    canvas = (free_map.canvas_w, free_map.canvas_h)

    def score(region) -> float:
        return region.score + region_bias(region.center, gaze, canvas)

    preferred = FREE_SPACE["anchor_region"].get(anchor)
    names = (
        ("left-of-face", "right-of-face")
        if preferred == "beside-face" else (preferred,)
    )
    legal = [
        region for region in free_map.regions
        if region.name in names
        and region.fits(width, height)
        and region.emptiness >= FREE_SPACE["prefer_emptiness"]
    ]
    if legal:
        return max(legal, key=score), False
    feasible = [
        region for region in free_map.regions
        if region.fits(width, height) and region.emptiness > 0.0
    ]
    if feasible:
        return max(feasible, key=score), True
    return None, True


def _scaled_geometry(content: tuple, dims: tuple,
                     scale: float) -> tuple[tuple, tuple]:
    """Return mod-2 clip dimensions and its correspondingly scaled bbox."""
    clip_w, clip_h = dims
    width = max(2, int(round(clip_w * scale / 2.0)) * 2)
    height = max(2, int(round(clip_h * scale / 2.0)) * 2)
    sx, sy = width / clip_w, height / clip_h
    bbox = (
        content[0] * sx, content[1] * sy,
        content[2] * sx, content[3] * sy,
    )
    return (width, height), bbox


def _max_scale(region, content: tuple, dims: tuple) -> tuple | None:
    """Largest exact mod-2 scale that fits a region's binding dimension."""
    minimum = float(PLACEMENT_SCALE["min"])

    def fits(scale: float) -> bool:
        _scaled_dims, bbox = _scaled_geometry(content, dims, scale)
        return region.fits(bbox[2] - bbox[0], bbox[3] - bbox[1])

    if fits(1.0):
        return 1.0, *_scaled_geometry(content, dims, 1.0)
    if not fits(minimum):
        return None
    low, high = minimum, 1.0
    for _index in range(24):
        middle = (low + high) / 2.0
        if fits(middle):
            low = middle
        else:
            high = middle
    return low, *_scaled_geometry(content, dims, low)


def _land(region, content: tuple, scale: float = 1.0,
          scaled: tuple | None = None) -> PlacementSolution:
    """Center one original/scaled content footprint in ``region``."""
    bbox = scaled or content
    dx, dy = place_content(bbox, region)
    placed = tuple(
        int(round(value + (dx if index % 2 == 0 else dy)))
        for index, value in enumerate(bbox)
    )
    return PlacementSolution(
        region.name, dx, dy, placed, scale,
        None, False,
    )


def solve_placement(free_map, anchor: str, content: tuple,
                    context: tuple[tuple, tuple | None]) -> PlacementSolution | None:
    """Resolve authored-clear, full-size, then scaled free-band placement."""
    dims, gaze = context
    if anchor == "free-band" and not _intersects(
            content, free_map.expanded_face):
        placed = tuple(int(round(value)) for value in content)
        return PlacementSolution("authored-clear", 0, 0, placed)
    region, fallback = choose_region(free_map, anchor, content, gaze)
    if region is not None:
        landed = _land(region, content)
        return PlacementSolution(
            landed.region, landed.dx, landed.dy, landed.placed_bbox,
            fallback=fallback,
        )
    if anchor != "free-band":
        return None
    canvas = (free_map.canvas_w, free_map.canvas_h)
    candidates: list[tuple[float, float, object, tuple]] = []
    for candidate in free_map.regions:
        if candidate.emptiness <= 0.0:
            continue
        scaled = _max_scale(candidate, content, dims)
        if scaled is None:
            continue
        score = candidate.score + region_bias(candidate.center, gaze, canvas)
        candidates.append((score, scaled[0], candidate, scaled))
    if not candidates:
        return None
    _score, scale, region, scaled = max(candidates, key=lambda row: row[:2])
    scaled_dims, scaled_bbox = scaled[1], scaled[2]
    landed = _land(region, content, scale, scaled_bbox)
    return PlacementSolution(
        landed.region, landed.dx, landed.dy, landed.placed_bbox,
        scale=scale, scaled_dims=scaled_dims, fallback=True,
    )
