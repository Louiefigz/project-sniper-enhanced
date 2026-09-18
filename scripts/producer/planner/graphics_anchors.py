#!/usr/bin/env python3
"""graphics_anchors — face-relative overlay offsets (R3/R4) for graphics_stage.

Split from graphics_stage.py (300-line logic budget) as a focused, testable unit:
faceBBoxNorm + anchor name → the ffmpeg ``overlay`` ``(dx, dy)`` px offset that
places a full-canvas alpha comp AROUND the face.

Two models live here:

* v1 ``resolve_offset`` / ``anchor_offset`` (DEVIATION nudge). A face-relative
  comp authored full-canvas for a NOMINALLY-framed centered head is translated by
  the actual face's DEVIATION from that nominal, so it tracks the face without the
  comp knowing its own content size. FLAW (operator-caught): a comp that authors
  its content at mid-frame (chip-row's ``top:855px``, the chin) barely moves when
  the face is near-nominal, so the graphic lands ON the face. Kept as the seed /
  last-resort fallback and for the unit-tested contract.

* v2 ``resolve_offset_v2`` (ABSOLUTE placement — Placement v2). It MEASURES the
  frame's free space (free_space.build_free_map), probes the graphic's OWN
  rendered content footprint (``_content_bbox`` on the alpha mov), and places that
  footprint into the emptiest LEGAL region the anchor prefers — falling back by
  score when the preferred region is occupied or can't hold the graphic. This is
  what graphics_stage uses; v1 is the fallback if measurement can't run.

  headroom     = above the face+hair (widgets / section markers, R3)
  chest        = below the chin      (floating assets, R4 → lower-third band)
  beside-face  = the emptier side, at face height (side panels, R4)
"""

from __future__ import annotations

import math
import os
import subprocess
import tempfile

from planner.occupancy import NoLegalRegion, no_legal_evidence
from planner.placement_solver import (
    choose_region as _choose_region,
    scale_footprint,
    solve_placement,
)
from producer_config import CANVAS, MOTION, SAFE_BOX

# The face-relative anchors this module handles (others → no offset).
FACE_ANCHORS = MOTION.get("face_anchors", ("headroom", "chest", "beside-face"))

# Nominal centered head [x, y, w, h] (0..1) the comps author against; deviations
# from it drive the translation, so a centered face gives ~0 offset.
_NOMINAL_FACE = (0.36, 0.24, 0.28, 0.30)
# beside-face pushes the overlay clear of the face edge by half a face width + a
# margin toward the emptier side.
_BESIDE_MARGIN_PX = 120
# Final guards so a pathological bbox can't fling the overlay off-canvas — the
# offset is capped to roughly the safe-box margins around center.
_OFFSET_CAP_X = SAFE_BOX["left"] + 160          # ~220px
_OFFSET_CAP_Y = SAFE_BOX["top"] + 70            # ~320px


def _face_px(bbox: list, canvas: tuple | None = None) -> dict:
    """faceBBoxNorm ``[x, y, w, h]`` → geometry on the requested canvas."""
    w_px, h_px = canvas or (CANVAS["width"], CANVAS["height"])
    x, y, w, h = (float(v) for v in bbox)
    return {"cx": (x + w / 2) * w_px, "cy": (y + h / 2) * h_px,
            "top": y * h_px, "bottom": (y + h) * h_px,
            "left": x * w_px, "right": (x + w) * w_px, "w": w * w_px}


def anchor_offset(anchor: str, bbox: list,
                  canvas: tuple | None = None) -> tuple[int, int]:
    """Overlay ``(dx, dy)`` px to place a full-canvas comp face-relative (R3/R4).

    The offset is the actual face's deviation from ``_NOMINAL_FACE`` at the
    anchor's reference point, so a comp authored for the nominal head follows the
    real one. Capped to keep the overlay on-canvas for a pathological bbox.
    """
    dims = canvas or (CANVAS["width"], CANVAS["height"])
    f, n = _face_px(bbox, dims), _face_px(_NOMINAL_FACE, dims)
    sx, sy = dims[0] / CANVAS["width"], dims[1] / CANVAS["height"]
    if anchor == "headroom":           # content lives above the face top
        dx, dy = f["cx"] - n["cx"], f["top"] - n["top"]
    elif anchor == "chest":            # content lives below the face bottom
        dx, dy = f["cx"] - n["cx"], f["bottom"] - n["bottom"]
    else:                              # beside-face: push to the emptier side
        side = 1 if (dims[0] - f["right"]) >= f["left"] else -1
        dx = (f["cx"] - n["cx"]) + side * (
            f["w"] / 2 + _BESIDE_MARGIN_PX * sx)
        dy = f["cy"] - n["cy"]
    dx = max(-_OFFSET_CAP_X * sx, min(_OFFSET_CAP_X * sx, dx))
    dy = max(-_OFFSET_CAP_Y * sy, min(_OFFSET_CAP_Y * sy, dy))
    return int(round(dx)), int(round(dy))


def valid_face_bbox(value: object) -> bool:
    """Whether ``value`` is a positive, in-bounds normalized xywh box."""
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return False
    if not all(isinstance(item, (int, float))
               and not isinstance(item, bool)
               and math.isfinite(float(item)) for item in value):
        return False
    x, y, width, height = (float(item) for item in value)
    return (x >= 0.0 and y >= 0.0 and width > 0.0 and height > 0.0
            and x + width <= 1.0 and y + height <= 1.0)


def resolve_offset(entry: dict,
                   canvas: tuple | None = None) -> tuple[int, int]:
    """``(dx, dy)`` for one graphicsTrack entry — 0 unless a face-relative anchor.

    Face-relative anchors REQUIRE a valid 4-number faceBBoxNorm ON THE ENTRY
    (render.py threads graphicsTrack entries verbatim, so the entry is the only
    carrier the compositor sees). Missing/invalid → raise, never silently render
    at (0,0) — a misplaced face graphic must fail loud.
    """
    anchor = entry.get("anchor", "free-band")
    if anchor not in FACE_ANCHORS:
        return 0, 0
    bbox = entry.get("faceBBoxNorm")
    if not valid_face_bbox(bbox):
        raise ValueError(
            f"anchor '{anchor}' requires a 4-number faceBBoxNorm (0..1) on the "
            f"entry; got {bbox!r}")
    return anchor_offset(anchor, bbox, canvas)


# --------------------------------------------------------------------------- #
# v2 — ABSOLUTE placement into measured free space (Placement v2).
# --------------------------------------------------------------------------- #
def _ffprobe_duration(mov_path: str) -> float:
    """Container duration (s) of a rendered overlay clip."""
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", mov_path],
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {mov_path}: {proc.stderr.strip()[-200:]}")
    return float(proc.stdout.strip())


def _clip_dims(path: str) -> tuple[int, int]:
    """(width, height) of a rendered overlay clip's video stream (ffprobe)."""
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-of", "csv=p=0", path],
        capture_output=True, text=True)
    parts = proc.stdout.strip().split(",")
    if proc.returncode != 0 or len(parts) < 2:
        raise RuntimeError(f"ffprobe dims failed on {path}: "
                           f"{proc.stderr.strip()[-200:]}")
    return int(parts[0]), int(parts[1])


def scale_geometry(content: tuple, point: tuple, dims: tuple,
                   scale: float) -> dict:
    """PURE geometry for a scaled explicit placement (placement.scale).

    The full-canvas clip ``dims`` is resized to the EVEN dims nearest
    ``dims * scale`` (yuv encoders/overlay want mod-2), so the EFFECTIVE
    per-axis factors (sx, sy) differ from ``scale`` by <1px worth — every bbox
    term uses them, keeping the pin exact under the rounding. Returns
    ``{"w", "h", "dx", "dy", "placed"}``: the scaled clip size, the overlay
    offset pinning the SCALED content bbox top-left at ``point``, and the
    resulting placed bbox on the delivery canvas.
    """
    (cw, ch), (x, y) = dims, point
    w = max(2, int(round(cw * scale / 2.0)) * 2)
    h = max(2, int(round(ch * scale / 2.0)) * 2)
    sx, sy = w / cw, h / ch
    scaled = (content[0] * sx, content[1] * sy, content[2] * sx, content[3] * sy)
    dx, dy = int(round(x - scaled[0])), int(round(y - scaled[1]))
    placed = (int(round(scaled[0])) + dx, int(round(scaled[1])) + dy,
              int(round(scaled[2])) + dx, int(round(scaled[3])) + dy)
    return {"w": w, "h": h, "dx": dx, "dy": dy, "placed": placed}


def _content_bbox(mov_path: str, alpha_thresh: int = 8) -> tuple[int, int, int, int]:
    """Nonzero-alpha bbox ``(x0, y0, x1, y1)`` px of the graphic's rendered content.

    The comps are full-canvas alpha clips (ProRes 4444); their VISIBLE content
    occupies only part of the canvas. We probe a few SETTLED frames in the last
    third of the clip (past any drift/fade-in) and UNION their alpha footprints,
    so the returned bbox is the graphic's true rendered extent — the thing that
    must land in free space, and the footprint the face-clearance check uses.

    ``alpha_thresh`` (0..255) counts a pixel as content; the low default keeps the
    soft drop-shadow in the footprint (conservative — the shadow clears the face
    too). Uses ffmpeg ``alphaextract`` + cv2 (venv python).
    """
    import cv2  # lazy: keeps the pure v1 path import-light

    duration = _ffprobe_duration(mov_path)
    box = None
    with tempfile.TemporaryDirectory(prefix="content-bbox-") as tmp:
        for frac in (0.72, 0.85, 0.95):
            t = max(0.0, duration * frac)
            png = os.path.join(tmp, f"a_{frac}.png")
            proc = subprocess.run(
                ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss",
                 f"{t:.4f}", "-i", mov_path, "-vf", "alphaextract",
                 "-frames:v", "1", png],
                capture_output=True, text=True)
            if proc.returncode != 0 or not os.path.exists(png):
                continue
            alpha = cv2.imread(png, cv2.IMREAD_GRAYSCALE)
            if alpha is None:
                continue
            ys, xs = (alpha > alpha_thresh).nonzero()
            if len(xs) == 0:
                continue
            b = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
            box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]),
                                         max(box[2], b[2]), max(box[3], b[3]))
    if box is None:
        raise RuntimeError(f"no nonzero-alpha content found in {mov_path}")
    return box


def _solution_meta(anchor: str, content: tuple, free_map,
                   result: tuple) -> dict:
    """Placement evidence for one solved geometry result."""
    solved, gaze = result
    region = free_map.region(solved.region)
    meta = {
        "anchor": anchor,
        "region": solved.region,
        "fallback": solved.fallback,
        "emptiness": round(region.emptiness, 3) if region else 1.0,
        "hairMeasured": free_map.hair_measured,
        "contentBBox": list(content),
        "placedBBox": list(solved.placed_bbox),
        "expandedFace": [int(v) for v in free_map.expanded_face],
        "faceAware": True,
    }
    if gaze:
        meta["gaze"] = [round(value, 4) for value in gaze]
    if solved.scaled_dims is not None:
        meta.update(scale=round(solved.scale, 4),
                    scaledDims=list(solved.scaled_dims))
    return meta


def resolve_offset_v2(entry: dict, mov_path: str, video_in: str,
                      band_y_offset_px: float = 0.0) -> tuple:
    """Absolute overlay ``(dx, dy)`` for a face-relative entry + its rendered clip.

    Measures the free space at the entry's window (seeded by the entry's
    ``faceBBoxNorm``), probes the clip's content footprint, and centers it into the
    emptiest legal region the anchor prefers — with the previous-shot gaze point
    (``eye_trace.gaze_xy``: planner ``gazeXY``, else the face center) as an
    ADDITIVE near-tie bias on the region ranking (LIAM move 4; never overrides
    fit/emptiness legality). Non-face anchors return ``(0, 0)`` (unchanged
    compositing). Returns ``(dx, dy, meta)`` where ``meta`` records the chosen
    region + fallback (+ the gaze read, when known) for the stage's status line.
    Raises on measurement failure so the caller can fall back to v1 loudly,
    never mis-place silently.
    """
    from planner.eye_trace import gaze_xy
    from planner.free_space import build_free_map

    anchor = entry.get("anchor", "free-band")
    bbox = entry.get("faceBBoxNorm")
    free_band_face_aware = anchor == "free-band" and valid_face_bbox(bbox)
    if anchor not in FACE_ANCHORS and not free_band_face_aware:
        return 0, 0, {"anchor": anchor, "region": None}
    out_start, out_end = float(entry["outStart"]), float(entry["outEnd"])
    free_map = build_free_map(video_in, (out_start, out_end),
                              bbox, band_y_offset_px)
    authored = _clip_dims(mov_path)
    delivery = (free_map.canvas_w, free_map.canvas_h)
    authored_content = _content_bbox(mov_path)
    content = scale_footprint(authored_content, authored, delivery)
    gaze = gaze_xy(entry)
    solved = solve_placement(
        free_map, anchor, content, (delivery, gaze))
    if solved is None:
        # Fail-closed core (geometry contract v3 #1): the v1 seed nudge here
        # was the silent mis-place path — a typed error now routes the anatomy
        # evidence to the brain for a re-plan instead.
        raise NoLegalRegion(no_legal_evidence(anchor, content, free_map,
                                              (out_start, out_end)))
    meta = _solution_meta(anchor, content, free_map, (solved, gaze))
    meta.update(canvas=list(delivery), authoredCanvas=list(authored))
    if authored != delivery:
        meta["authoredContentBBox"] = list(authored_content)
        meta.setdefault("scaledDims", list(delivery))
    return solved.dx, solved.dy, meta
