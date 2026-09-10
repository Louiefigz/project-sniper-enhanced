#!/usr/bin/env python3
"""free_space — absolute free-space map for graphics placement (Placement v2).

Placement v1 (graphics_anchors.anchor_offset) translated a full-canvas comp by
the face's DEVIATION from a nominal head. That fails when the comp authors its
content at mid-frame (chip-row's ``top:855px`` sits at the chin): a face near the
nominal position yields a ~0 nudge, so the graphic renders ON the face. The
operator caught exactly this — chips across the jaw.

This module fixes the ROOT CAUSE by MEASURING where the head, body and busy
background are, then exposing the emptiest LEGAL regions so a graphic can be
placed ABSOLUTELY into free space (R3: "the headroom IS the graphics canvas").

For a graphic's output time window it samples a handful of frames and fuses
three occupancy signals onto a grid over the decoded delivery canvas:

  * face + hair — the Haar face box (reused from face_track / visual_state). The
    hair top is MEASURED (``measure_hair_top``, median-background subtraction: the
    head moves, the room doesn't) so the exclusion box covers the real hair, not a
    guess; a 40%-of-face-height up-expansion is the FALLBACK when hair can't be
    measured (hat/hood, little motion). Sides expand 25% (ears). Graphics clear it.
  * body silhouette — a ``face_width * body_width_mult`` column from the chin to
    the frame bottom (shoulders / torso / gesturing hands).
  * busy background — per-cell Canny edge density (window, mirror, dense detail).

Candidate REGIONS (headroom band, left-of-face, right-of-face, lower-third) are
scored by emptiness x size and returned ranked with ABSOLUTE x/y bands, so the
anchor resolver picks the emptiest region that can actually hold the graphic.

``verify_placement`` re-measures a COMPOSITE render (detect face + hair in the
final frames) and asserts a graphic's placed bbox clears the face — the
independent post-composite check (mirrors the sibling video-editor ``--verify``).

The geometry + scoring (top of file) is PURE (no OpenCV) and unit-tested; the cv2
frame-sampling / hair-measurement primitives live in ``free_space_sample`` and are
imported lazily by ``build_free_map`` / ``verify_placement`` (run with venv python).

CLI:  free_space.py <video.mp4> <outStart> <outEnd> [--face-bbox x,y,w,h]
        prints the free map (face box, regions ranked, suggested caption band).
      free_space.py --verify <render.mp4> --window s,e --placed-bbox x0,y0,x1,y1
        re-measures the composite; exit 1 if the graphic intersects the face.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from producer_config import FREE_SPACE, SAFE_BOX  # noqa: E402


# =========================================================================== #
# Pure geometry + scoring (NO OpenCV) — unit-testable.
# =========================================================================== #
@dataclass(frozen=True)
class Grid:
    """The occupancy grid over the canvas — bundles the four recurring dims.

    (Keeps the geometry helpers at <=4 params, mirroring face_track's
    ``frame_size`` / visual_state's ``ZoneContext`` context objects.)
    """

    cols: int
    rows: int
    canvas_w: int
    canvas_h: int

    @property
    def canvas(self) -> tuple[int, int]:
        return self.canvas_w, self.canvas_h

    @classmethod
    def of(cls, canvas: tuple[int, int], cfg: dict = FREE_SPACE) -> "Grid":
        return cls(cfg["grid_cols"], cfg["grid_rows"], canvas[0], canvas[1])


@dataclass
class Region:
    """One candidate placement region in absolute canvas px.

    ``orient`` is the BINDING dimension for fit: ``"h"`` (horizontal band, a
    graphic must fit its HEIGHT) or ``"v"`` (vertical band, must fit its WIDTH).
    The other dimension is satisfied by centering (soft overflow is allowed —
    e.g. a wide chip-row's drop-shadow bleeding a little past a full-width band).
    """

    name: str
    x0: int
    y0: int
    x1: int
    y1: int
    orient: str
    emptiness: float = 0.0
    score: float = 0.0

    @property
    def width(self) -> int:
        return self.x1 - self.x0

    @property
    def height(self) -> int:
        return self.y1 - self.y0

    @property
    def center(self) -> tuple[float, float]:
        return (self.x0 + self.x1) / 2.0, (self.y0 + self.y1) / 2.0

    def fits(self, content_w: float, content_h: float) -> bool:
        """Can this region hold content of the given size in its binding dim?"""
        if self.orient == "h":
            return self.height >= content_h
        return self.width >= content_w

    def as_dict(self) -> dict:
        return {"name": self.name, "x0": self.x0, "y0": self.y0, "x1": self.x1,
                "y1": self.y1, "orient": self.orient,
                "emptiness": round(self.emptiness, 4), "score": round(self.score, 4)}


@dataclass
class FreeMap:
    """The measured free-space map for one graphic window (absolute canvas px)."""

    canvas_w: int
    canvas_h: int
    face: tuple | None                 # (x, y, w, h) px, or None
    expanded_face: tuple               # (x0, y0, x1, y1) px (face + hair margin)
    body_col: tuple | None             # (x0, y0, x1, y1) px, or None
    grid_cols: int
    grid_rows: int
    occupancy: list = field(default_factory=list)   # rows x cols bool
    regions: list = field(default_factory=list)      # ranked list[Region]
    hair_measured: bool = False        # True: expanded-face top is a real hair top

    def region(self, name: str) -> Region | None:
        return next((r for r in self.regions if r.name == name), None)

    def as_dict(self) -> dict:
        return {"canvas": [self.canvas_w, self.canvas_h],
                "face": list(self.face) if self.face else None,
                "expandedFace": [int(v) for v in self.expanded_face],
                "hairMeasured": self.hair_measured,
                "bodyColumn": [int(v) for v in self.body_col] if self.body_col else None,
                "grid": [self.grid_cols, self.grid_rows],
                "regions": [r.as_dict() for r in self.regions]}


def norm_to_px(bbox_norm: list, canvas_w: int, canvas_h: int) -> tuple:
    """faceBBoxNorm ``[x, y, w, h]`` (0..1) -> pixel ``(x, y, w, h)``."""
    x, y, w, h = (float(v) for v in bbox_norm)
    return (x * canvas_w, y * canvas_h, w * canvas_w, h * canvas_h)


def expand_face(face_px: tuple, cfg: dict = FREE_SPACE,
                hair_top: float | None = None) -> tuple:
    """Face box -> "face + hair" exclusion box ``(x0, y0, x1, y1)`` px.

    The TOP is the MEASURED ``hair_top`` when supplied (clamped to [0, face_top]);
    otherwise it falls back to a ``face_expand_up`` x face-height guess (the hair
    sits above the Haar box). Sides always grow by ``face_expand_side`` x face
    width (ears / side hair). The bottom is the chin (body silhouette handles below).
    """
    x, y, w, h = face_px
    side = cfg["face_expand_side"] * w
    if hair_top is not None:
        top = min(max(float(hair_top), 0.0), y)         # measured hair top
    else:
        top = y - cfg["face_expand_up"] * h             # 40% fallback guess
    return (x - side, top, x + w + side, y + h)


def body_column(face_px: tuple, canvas_h: int, cfg: dict = FREE_SPACE) -> tuple:
    """Torso/hands column below the chin ``(x0, y0, x1, y1)`` px.

    A column ``face_width * body_width_mult`` wide, centered on the face, from the
    chin to the frame bottom — the speaker's shoulders, torso and gesturing hands.
    """
    x, y, w, h = face_px
    half = (w * cfg["body_width_mult"]) / 2.0
    cx = x + w / 2.0
    return (cx - half, y + h, cx + half, float(canvas_h))


def _rect_cells(rect: tuple, grid: Grid):
    """Yield ``(r, c)`` grid cells a pixel rect overlaps (clamped to the grid)."""
    x0, y0, x1, y1 = rect
    cw, ch = grid.canvas_w / grid.cols, grid.canvas_h / grid.rows
    c0 = max(0, int(x0 // cw))
    c1 = min(grid.cols - 1, int((x1 - 1e-6) // cw))
    r0 = max(0, int(y0 // ch))
    r1 = min(grid.rows - 1, int((y1 - 1e-6) // ch))
    for r in range(r0, r1 + 1):
        for c in range(c0, c1 + 1):
            yield r, c


def build_occupancy(grid: Grid, rects: list, busy_cells: set) -> list:
    """Grid of booleans: a cell is occupied by any rect OR flagged busy."""
    occ = [[False] * grid.cols for _ in range(grid.rows)]
    for r, c in busy_cells:
        if 0 <= r < grid.rows and 0 <= c < grid.cols:
            occ[r][c] = True
    for rect in rects:
        if rect is None:
            continue
        for r, c in _rect_cells(rect, grid):
            occ[r][c] = True
    return occ


def region_emptiness(region: Region, occupancy: list, grid: Grid) -> float:
    """Fraction of a region's grid cells that are NOT occupied (1.0 = fully free)."""
    cells = list(_rect_cells((region.x0, region.y0, region.x1, region.y1), grid))
    if not cells:
        return 0.0
    free = sum(1 for r, c in cells if not occupancy[r][c])
    return free / len(cells)


def candidate_regions(face_px: tuple, expanded: tuple, grid: Grid,
                      cfg: dict = FREE_SPACE) -> list:
    """Build the (unscored) candidate regions around the face, legal-bounded.

    All regions are clamped inside SAFE_BOX on the sides + bottom; the headroom
    band's top uses the smaller ``headroom_top_inset`` (the headliner margin).
    A region below ``min_band_px`` in its binding dimension is dropped.
    """
    canvas_w, canvas_h = grid.canvas
    sl, sr = SAFE_BOX["left"], canvas_w - SAFE_BOX["right"]
    sb = canvas_h - SAFE_BOX["bottom"]
    top = cfg["headroom_top_inset"]
    min_band = cfg["min_band_px"]
    ex0, ey0, ex1, ey1 = expanded          # ey1 == chin (face bottom)
    fx, fy, fw, fh = face_px
    face_top, face_bot = int(fy), int(fy + fh)
    out: list[Region] = []
    if int(ey0) - top >= min_band:          # headroom: above the hair
        out.append(Region("headroom", sl, top, sr, int(ey0), "h"))
    if sb - int(ey1) >= min_band:           # lower-third: below the chin
        out.append(Region("lower-third", sl, int(ey1), sr, sb, "h"))
    if int(ex0) - sl >= min_band:           # left of the head, at face height
        out.append(Region("left-of-face", sl, face_top, int(ex0), face_bot, "v"))
    if sr - int(ex1) >= min_band:           # right of the head, at face height
        out.append(Region("right-of-face", int(ex1), face_top, sr, face_bot, "v"))
    return out


def score_regions(regions: list, occupancy: list, grid: Grid) -> list:
    """Set each region's emptiness + score (emptiness x sqrt(area)) and sort desc.

    ``sqrt(area)`` keeps a very empty small region from beating a nearly-as-empty
    large one, without letting raw area dominate emptiness.
    """
    max_area = float(grid.canvas_w * grid.canvas_h)
    for r in regions:
        r.emptiness = region_emptiness(r, occupancy, grid)
        area_frac = (r.width * r.height) / max_area
        r.score = round(r.emptiness * (area_frac ** 0.5), 6)
    regions.sort(key=lambda x: x.score, reverse=True)
    return regions


def _clamp_center(target: float, half: float, lo: float, hi: float) -> float:
    """Center a span of half-width ``half`` inside [lo, hi], else use the midpoint.

    When the span is wider than [lo, hi] it can't be contained, so it is centered
    on the box midpoint (symmetric overflow) — the best available for e.g. a
    drop-shadow footprint wider than a full-width band.
    """
    if hi - lo >= 2 * half:
        return min(max(target, lo + half), hi - half)
    return (lo + hi) / 2.0


def place_content(content_bbox: tuple, region: Region) -> tuple:
    """Offset ``(dx, dy)`` to center a content bbox into ``region``.

    ``content_bbox`` is the graphic's rendered footprint ``(x0, y0, x1, y1)`` px
    (see graphics_anchors._content_bbox). The offset moves the footprint's center
    to the region center, clamped so the binding dimension stays inside the region
    (the region is already legal-bounded, so this is the SAFE_BOX clamp). Returns
    ``(dx, dy)`` rounded to int.
    """
    cx0, cy0, cx1, cy1 = content_bbox
    ccx, ccy = (cx0 + cx1) / 2.0, (cy0 + cy1) / 2.0
    hw, hh = (cx1 - cx0) / 2.0, (cy1 - cy0) / 2.0
    rcx, rcy = region.center
    tx = _clamp_center(rcx, hw, region.x0, region.x1)
    ty = _clamp_center(rcy, hh, region.y0, region.y1)
    return int(round(tx - ccx)), int(round(ty - ccy))


from planner.free_space_runtime import (assemble_free_map, build_free_map, main,
                                        suggest_caption_band, verify_placement)

if __name__ == "__main__":
    main()
