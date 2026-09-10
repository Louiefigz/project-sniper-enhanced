#!/usr/bin/env python3
"""Decoded-video measurement and CLI seams for :mod:`planner.free_space`."""

from __future__ import annotations

import argparse
import json
import sys

from producer_config import FREE_SPACE, SAFE_BOX


def suggest_caption_band(free_map, cfg: dict = FREE_SPACE,
                         safe: dict = SAFE_BOX) -> tuple | None:
    """Recommend a lower caption band when the body occupies mid-frame."""
    body = free_map.body_col
    if body is None or body[1] > free_map.canvas_h * 0.5:
        return None
    lo_frac, hi_frac = cfg["caption_low_band"]
    y0 = int(free_map.canvas_h * lo_frac)
    y1 = min(int(free_map.canvas_h * hi_frac),
             free_map.canvas_h - safe["bottom"])
    return y0, y1


def build_free_map(video_path: str, window: tuple,
                   face_bbox_norm: list | None = None,
                   band_y_offset_px: float = 0.0):
    """Measure a delivery-sized free map for one output-time window."""
    from planner.free_space import norm_to_px
    from planner.free_space_sample import measure_hair_top, sample_window
    from planner.occupancy import OccupancyExtras, build_map

    out_start, out_end = float(window[0]), float(window[1])
    frames, face_px, busy, canvas = sample_window(
        video_path, out_start, out_end)
    if face_px is None and face_bbox_norm is not None:
        face_px = norm_to_px(face_bbox_norm, canvas[0], canvas[1])
    if face_px is None:
        raise RuntimeError("no face detected and no faceBBoxNorm hint supplied — "
                           "cannot build a face-relative free-space map")
    hair = measure_hair_top(
        frames, face_px[0] + face_px[2] / 2.0, face_px[1]) if frames else None
    extras = OccupancyExtras(hair_top=hair,
                             band_y_offset_px=band_y_offset_px)
    return build_map(face_px, busy, canvas, extras)


def assemble_free_map(face_px: tuple, busy_cells: set, canvas: tuple,
                      hair_top: float | None = None):
    """Assemble a map through the shared occupancy predicate."""
    from planner.occupancy import OccupancyExtras, build_map

    return build_map(face_px, busy_cells, canvas,
                     OccupancyExtras(hair_top=hair_top))


def verify_placement(render: str, out_start: float, out_end: float,
                     placed_bbox: tuple) -> tuple:
    """Re-measure a composite and require its graphic to clear face+hair."""
    from planner.free_space import expand_face
    from planner.free_space_sample import measure_hair_top, sample_window

    frames, face_px, _busy, _canvas = sample_window(
        render, out_start, out_end)
    if face_px is None:
        return False, {"ok": False, "reason": "no face detected in the render"}
    hair = measure_hair_top(
        frames, face_px[0] + face_px[2] / 2.0, face_px[1],
        exclude=placed_bbox) if frames else None
    ex0, ey0, ex1, ey1 = expand_face(face_px, hair_top=hair)
    px0, py0, px1, py1 = placed_bbox
    gap = FREE_SPACE["verify_min_gap_px"]
    ix = max(0.0, min(px1, ex1 + gap) - max(px0, ex0 - gap))
    iy = max(0.0, min(py1, ey1 + gap) - max(py0, ey0 - gap))
    intersection = ix * iy
    detail = {
        "ok": intersection == 0, "intersection": round(intersection, 1),
        "gapPx": round(ey0 - py1, 1), "hairMeasured": hair is not None,
        "expandedFace": [int(v) for v in (ex0, ey0, ex1, ey1)],
        "placedBBox": [int(v) for v in placed_bbox],
    }
    return intersection == 0, detail


def _run_verify(parser: argparse.ArgumentParser, args) -> None:
    """Execute CLI verification mode."""
    if not (args.window and args.placed_bbox):
        parser.error("--verify needs --window s,e and --placed-bbox x0,y0,x1,y1")
    start, end = (float(value) for value in args.window.split(","))
    placed = tuple(float(value) for value in args.placed_bbox.split(","))
    ok, detail = verify_placement(args.verify, start, end, placed)
    print(json.dumps(detail, indent=2))
    raise SystemExit(0 if ok else 1)


def _parser() -> argparse.ArgumentParser:
    """Build the standalone diagnostic CLI parser."""
    parser = argparse.ArgumentParser(description="Placement v2 free-space map")
    parser.add_argument("video", nargs="?")
    parser.add_argument("out_start", nargs="?", type=float)
    parser.add_argument("out_end", nargs="?", type=float)
    parser.add_argument("--face-bbox", default=None)
    parser.add_argument("--verify", metavar="RENDER", default=None)
    parser.add_argument("--window", default=None)
    parser.add_argument("--placed-bbox", default=None)
    return parser


def main() -> None:
    """Run the map/verification diagnostic CLI."""
    parser = _parser()
    args = parser.parse_args()
    try:
        if args.verify:
            _run_verify(parser, args)
            return
        if args.video is None or args.out_start is None or args.out_end is None:
            parser.error("give <video> <outStart> <outEnd>, or --verify RENDER")
        hint = ([float(value) for value in args.face_bbox.split(",")]
                if args.face_bbox else None)
        free_map = build_free_map(
            args.video, (args.out_start, args.out_end), hint)
        output = free_map.as_dict()
        output["suggestedCaptionBand"] = suggest_caption_band(free_map)
        print(json.dumps(output, indent=2))
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"error": str(exc)}))
        raise SystemExit(1) from exc
