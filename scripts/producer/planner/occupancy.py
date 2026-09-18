#!/usr/bin/env python3
"""occupancy — THE shared frame-occupancy predicate (geometry contract v3 #3).

One function decides what part of the delivery canvas is occupied: the
expanded face+hair box, the body column, and the aspect-aware caption band,
honoring the plan's
``captions.bandYOffsetPx`` up-shift). Both the PLAN-TIME feasibility lint
(:mod:`planner.geometry_feasibility`) and the RENDER-TIME placement authority
(``free_space.build_free_map`` → ``resolve_offset_v2``) consume
:func:`build_map`, so the lint's predicate IS the render's predicate by
construction — they can never drift.

Also home of :class:`NoLegalRegion`, the typed geometry failure that replaced
the v1 seed-nudge fallback (fail-closed core): raised by
``graphics_anchors.resolve_offset_v2`` when no candidate region can hold the
measured content, and recognized by the auto-edit worker's typed re-plan
route via the stable ``"NoLegalRegion: "`` message prefix.

An up-shifted band (``bandYOffsetPx`` > 0) is DISJOINT-ABOVE the default
band, not a subset of it — modeling offset 0 is NOT conservative. Every
occupancy consumer (render-time placement AND the plan-time lint) must
therefore pass the plan's real offset (:func:`plan_band_offset`); a caller
without plan context may only default to 0 when no captions are burned.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from producer_config import (CANVAS_BY_ASPECT, CAPTION_LAYOUT_BY_ASPECT,  # noqa: E402
                             FREE_SPACE)
from planner.delivery_canvas import canvas_aspect  # noqa: E402
from planner.free_space import (Grid, FreeMap, body_column,  # noqa: E402
                                build_occupancy, candidate_regions,
                                expand_face, score_regions)


class NoLegalRegion(RuntimeError):
    """No candidate region can hold the measured content — fail closed.

    Attributes:
        evidence: The anatomy-evidence payload (anchor, content dims, face
            width fraction, regions tried, canvas) the brain needs to swap
            forms pre-review. The message carries a compact JSON of it behind
            the stable ``"NoLegalRegion: "`` signature the worker routes on.
    """

    def __init__(self, evidence: dict) -> None:
        """Build the typed failure from its evidence payload.

        Args:
            evidence: JSON-safe finding payload (see :func:`no_legal_evidence`).
        """
        self.evidence = evidence
        super().__init__("NoLegalRegion: "
                         + json.dumps(evidence, sort_keys=True,
                                      separators=(",", ":")))


@dataclass(frozen=True)
class OccupancyExtras:
    """Optional occupancy refinements beyond the raw face box.

    Attributes:
        hair_top: Measured hair-top y (px), or ``None`` for the 40% guess.
        band_y_offset_px: The plan's ``captions.bandYOffsetPx`` up-shift.
    """

    hair_top: float | None = None
    band_y_offset_px: float = 0.0


def plan_band_offset(plan: dict) -> float:
    """The plan's ``captions.bandYOffsetPx`` up-shift as a float (0 absent).

    THE one accessor both render-time placement wiring and the plan-time
    lint use, so the two sides always read the same field the same way.
    """
    return float((plan.get("captions") or {}).get("bandYOffsetPx", 0) or 0)


def caption_band_rect(canvas: tuple, band_y_offset_px: float = 0.0) -> tuple:
    """The burned-caption occupancy rect ``(x0, y0, x1, y1)`` px.

    The configured aspect band is scaled to the actual delivery resolution,
    then shifted up by the equivalently scaled ``bandYOffsetPx``.

    Args:
        canvas: ``(width, height)`` of the delivery canvas.
        band_y_offset_px: The plan's ``captions.bandYOffsetPx`` (default 0).

    Returns:
        The band rect in canvas px.
    """
    aspect = canvas_aspect(canvas)
    base = CANVAS_BY_ASPECT[aspect]
    scale_y = float(canvas[1]) / float(base["height"])
    y0, y1 = CAPTION_LAYOUT_BY_ASPECT[aspect]["y_band"]
    shift = float(band_y_offset_px) * scale_y
    return (0.0, max(0.0, y0 * scale_y - shift), float(canvas[0]),
            max(0.0, y1 * scale_y - shift))


def occupied_rects(face_px: tuple, canvas: tuple,
                   extras: OccupancyExtras) -> list:
    """THE shared occupancy inputs: face+hair, body column, caption band.

    Args:
        face_px: Face box ``(x, y, w, h)`` px on the delivery canvas.
        canvas: ``(width, height)`` of the delivery canvas.
        extras: Hair-top measurement + caption band offset.

    Returns:
        ``[expanded_face, body_column, caption_band]`` rects (px). The
        expanded face is always first (callers read it back for regions).
    """
    expanded = expand_face(face_px, FREE_SPACE, hair_top=extras.hair_top)
    body = body_column(face_px, int(canvas[1]), FREE_SPACE)
    return [expanded, body, caption_band_rect(canvas, extras.band_y_offset_px)]


def build_map(face_px: tuple, busy_cells: set, canvas: tuple,
              extras: OccupancyExtras | None = None) -> FreeMap:
    """Assemble the scored free-space map from the SHARED occupancy predicate.

    The one map-assembly both the feasibility lint and render-time placement
    call (``free_space.build_free_map`` delegates here), so caption-band
    exclusion and the face/body model stay identical on both sides.

    Args:
        face_px: Face box ``(x, y, w, h)`` px on the delivery canvas.
        busy_cells: Busy-background grid cells (may be empty).
        canvas: ``(width, height)`` of the delivery canvas.
        extras: Optional hair-top + caption band offset refinements.

    Returns:
        The ranked :class:`~planner.free_space.FreeMap`.
    """
    extras = extras or OccupancyExtras()
    grid = Grid.of(canvas, FREE_SPACE)
    rects = occupied_rects(face_px, canvas, extras)
    occ = build_occupancy(grid, rects, busy_cells)
    regions = candidate_regions(face_px, rects[0], grid, FREE_SPACE)
    score_regions(regions, occ, grid)
    return FreeMap(grid.canvas_w, grid.canvas_h, face_px, rects[0], rects[1],
                   grid.cols, grid.rows, occ, regions,
                   hair_measured=extras.hair_top is not None)


def no_legal_evidence(anchor: str, content_bbox: tuple, free_map: FreeMap,
                      window: tuple) -> dict:
    """The compact anatomy-evidence payload for a no-legal-region finding.

    Shared by the render-time :class:`NoLegalRegion` raise and the plan-time
    lint's WARN verdict, so both sides report identical evidence shape. Kept
    compact (region names + emptiness only) so the full message survives the
    worker's error-tail truncation.

    Args:
        anchor: The entry's face-relative anchor name.
        content_bbox: Measured content bbox ``(x0, y0, x1, y1)`` px.
        free_map: The occupancy map the placement failed against.
        window: The entry's ``(outStart, outEnd)`` output window.

    Returns:
        JSON-safe evidence dict (anchor, contentDims, faceWidthFrac,
        expandedFace, regionsTried, canvas, window).
    """
    face = free_map.face
    return {
        "anchor": anchor,
        "contentDims": [int(content_bbox[2] - content_bbox[0]),
                        int(content_bbox[3] - content_bbox[1])],
        "canvas": [free_map.canvas_w, free_map.canvas_h],
        "faceWidthFrac": (round(face[2] / free_map.canvas_w, 4)
                          if face else None),
        "expandedFace": [int(v) for v in free_map.expanded_face],
        "regionsTried": [{"name": r.name,
                          "emptiness": round(r.emptiness, 3),
                          "size": [r.width, r.height]}
                         for r in free_map.regions],
        "window": [round(float(window[0]), 3), round(float(window[1]), 3)],
    }
