#!/usr/bin/env python3
"""free_space_sample — cv2 frame-sampling + pixel measurement for free_space.

The OpenCV leaf primitives behind free_space's map + verify: sampling a window's
frames, per-cell edge (busy-background) detection, and the median-background
hair-top measurement. Split out of free_space.py so its geometry/scoring core
stays PURE (no cv2) and under the logic-line budget; free_space imports these
lazily (only build_free_map / verify_placement touch a real video). Run with the
venv python.
"""

from __future__ import annotations

import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from producer_config import CANVAS, FREE_SPACE  # noqa: E402
from planner.free_space import Grid  # noqa: E402


def busy_cells(frame, grid: Grid, cfg: dict = FREE_SPACE) -> set:
    """Grid cells whose Canny-edge density is text/UI/detail-like (busy set)."""
    import cv2
    h, w = frame.shape[:2]
    target_w = cfg["edge_downscale_w"]
    scale = target_w / float(w) if w > target_w else 1.0
    small = cv2.resize(frame, (int(w * scale), int(h * scale))) if scale < 1.0 else frame
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, cfg["canny_lo"], cfg["canny_hi"])
    gh, gw = edges.shape[0] // grid.rows, edges.shape[1] // grid.cols
    busy: set = set()
    if gh == 0 or gw == 0:
        return busy
    for r in range(grid.rows):
        for c in range(grid.cols):
            cell = edges[r * gh:(r + 1) * gh, c * gw:(c + 1) * gw]
            if cell.size and int((cell > 0).sum()) / cell.size >= cfg["cell_edge_frac"]:
                busy.add((r, c))
    return busy


def measure_hair_top(frames: list, face_cx: float, face_top: float,
                     exclude: tuple | None = None) -> float | None:
    """True hair top (px) via median-background subtraction, or None if unmeasurable.

    The median of the sampled frames is the STATIC room ("plate") — the head moves
    across the window, the room doesn't. Per frame ``|frame - plate|`` lights up the
    moving person (hair included, even dark hair on a dark background); the topmost
    row with enough person-pixels in a band above the face is that frame's hair top,
    and the median across frames rides out head drift. Returns ``None`` when the head
    barely moves / is hooded / detection was too sparse (caller falls back to the
    40% guess). Technique from the sibling video-editor ``face-frame.py``.

    ``exclude`` zeroes a rect in the person-mask — used by ``verify_placement`` on a
    COMPOSITE so the just-placed graphic (itself moving content above the face)
    isn't mistaken for hair (the general form of the sibling ``--verify`` y-floor).
    """
    import cv2
    import numpy as np
    cfg = FREE_SPACE
    if len(frames) < 3:
        return None
    plate = np.median(np.stack([f.astype(np.float32) for f in frames]), axis=0)
    h_img, w_img = frames[0].shape[:2]
    x0 = max(0, int(face_cx - cfg["hair_search_half_w"]))
    x1 = min(w_img, int(face_cx + cfg["hair_search_half_w"]))
    y0 = max(0, int(face_top - cfg["hair_search_up"]))
    y1 = min(h_img, int(face_top))
    if y1 - y0 < 4 or x1 - x0 < 4:
        return None
    kernel = np.ones((5, 5), np.uint8)
    tops: list = []
    for f in frames:
        diff = np.abs(f.astype(np.float32) - plate).mean(axis=2)
        mask = cv2.morphologyEx((diff > cfg["hair_diff_thresh"]).astype(np.uint8),
                                cv2.MORPH_OPEN, kernel)
        if exclude is not None:
            gx0, gy0, gx1, gy1 = (int(v) for v in exclude)
            mask[max(0, gy0):max(0, gy1), max(0, gx0):max(0, gx1)] = 0
        rows = np.where(mask[y0:y1, x0:x1].sum(axis=1) > cfg["hair_row_min_px"])[0]
        if len(rows):
            tops.append(y0 + int(rows[0]))
    if len(tops) < len(frames) / 2:
        return None
    return float(statistics.median(tops))


def sample_window(video_path: str, out_start: float, out_end: float) -> tuple:
    """Sample the window -> (frames, median face box px | None, majority-busy set)."""
    import cv2

    from motion.face_track import _load_cascade, _read_at, _sample_times
    from motion.visual_state import _largest_face
    from producer_config import FACE_TRACK

    cfg = FREE_SPACE
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {video_path}")
    det_cfg = {**FACE_TRACK, **cfg}
    grid = Grid.of((CANVAS["width"], CANVAS["height"]), cfg)
    frames: list = []
    boxes: list = []
    busy_counts: dict = {}
    try:
        cascade = _load_cascade()
        for t in _sample_times(out_start, out_end, cfg["samples_per_window"]):
            frame = _read_at(cap, t)
            if frame is None:
                continue
            frames.append(frame)
            box = _largest_face(frame, cascade, det_cfg)
            if box is not None:
                boxes.append(box)
            for cell in busy_cells(frame, grid, cfg):
                busy_counts[cell] = busy_counts.get(cell, 0) + 1
    finally:
        cap.release()
    face = None
    if boxes:
        face = tuple(statistics.median(b[i] for b in boxes) for i in range(4))
    # A cell counts as busy only if it read busy in the MAJORITY of samples
    # (a single flicker — a passing car, a hand — shouldn't condemn a region).
    thresh = max(1, len(frames) // 2) if frames else 1
    busy = {cell for cell, n in busy_counts.items() if n >= thresh}
    return frames, face, busy
