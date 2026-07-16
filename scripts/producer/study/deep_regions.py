#!/usr/bin/env python3
"""deep_regions — changed-region arithmetic for P3 (masks, bboxes, sweeps).

The FRAME.IO/assemble studies proved the primitives: a thresholded frame-diff
mask says WHERE pixels changed, connected components turn that into regions,
and a region whose bbox GROWS MONOTONICALLY frame-over-frame is a sweep (the
leading edge names the direction). Edge energy (mean gradient magnitude)
inside a bbox distinguishes a graphic ARRIVING (text/chrome adds edges) from
one LEAVING. All pure pixel arithmetic on grayscale numpy frames.
"""

from __future__ import annotations

import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from study.deep_config import DEEP  # noqa: E402


def diff_mask(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Boolean mask of pixels whose |a-b| exceeds the diff threshold."""
    return (np.abs(a.astype(np.int16) - b.astype(np.int16))
            > DEEP["diff_thresh"])


def coverage(mask: np.ndarray) -> float:
    """Fraction of the frame the mask covers."""
    return float(mask.mean())


def components_bbox(mask: np.ndarray) -> "tuple[list[float], float] | None":
    """Union bbox (normalised [x,y,w,h]) + coverage of significant components.

    Components smaller than ``min_component_frac`` of the frame are noise and
    dropped; None when nothing significant changed.
    """
    h, w = mask.shape[:2]
    min_area = max(1, int(DEEP["min_component_frac"] * w * h))
    n, _, stats, _ = cv2.connectedComponentsWithStats(
        mask.astype(np.uint8), connectivity=8)
    kept = [stats[i] for i in range(1, n)
            if stats[i, cv2.CC_STAT_AREA] >= min_area]
    if not kept:
        return None
    x0 = min(s[cv2.CC_STAT_LEFT] for s in kept)
    y0 = min(s[cv2.CC_STAT_TOP] for s in kept)
    x1 = max(s[cv2.CC_STAT_LEFT] + s[cv2.CC_STAT_WIDTH] for s in kept)
    y1 = max(s[cv2.CC_STAT_TOP] + s[cv2.CC_STAT_HEIGHT] for s in kept)
    area = sum(int(s[cv2.CC_STAT_AREA]) for s in kept)
    bbox = [round(x0 / w, 4), round(y0 / h, 4),
            round((x1 - x0) / w, 4), round((y1 - y0) / h, 4)]
    return bbox, round(area / float(w * h), 4)


def changed_region(before: np.ndarray,
                   after: np.ndarray) -> "tuple[list[float], float] | None":
    """(bbox_norm, coverage) of what changed between two settled frames."""
    return components_bbox(diff_mask(before, after))


def _boxes_touch(a: list, b: list, gap: float) -> bool:
    """Normalised bboxes overlap or sit within ``gap`` of each other."""
    return not (a[0] > b[0] + b[2] + gap or b[0] > a[0] + a[2] + gap
                or a[1] > b[1] + b[3] + gap or b[1] > a[1] + a[3] + gap)


def _merge_boxes(regions: list[dict], gap: float) -> list[dict]:
    """Union regions whose bboxes overlap/nearly touch (one graphic)."""
    merged: list[dict] = []
    for reg in sorted(regions, key=lambda r: -r["cov"]):
        home = next((m for m in merged
                     if _boxes_touch(m["bbox"], reg["bbox"], gap)), None)
        if home is None:
            merged.append(dict(reg))
            continue
        ax0 = min(home["bbox"][0], reg["bbox"][0])
        ay0 = min(home["bbox"][1], reg["bbox"][1])
        ax1 = max(home["bbox"][0] + home["bbox"][2],
                  reg["bbox"][0] + reg["bbox"][2])
        ay1 = max(home["bbox"][1] + home["bbox"][3],
                  reg["bbox"][1] + reg["bbox"][3])
        home["bbox"] = [round(ax0, 4), round(ay0, 4),
                        round(ax1 - ax0, 4), round(ay1 - ay0, 4)]
        home["cov"] = round(home["cov"] + reg["cov"], 4)
    return merged


def component_regions(mask: np.ndarray, max_k: int = 3,
                      merge_gap: float = 0.04) -> list[dict]:
    """SEPARATE changed regions of one mask: [{"bbox", "cov"}, ...].

    Where ``components_bbox`` unions everything (conflating e.g. a graphic
    exiting up top with a pop landing at the chest), this returns each
    significant component on its own, merging only boxes that overlap or
    nearly touch. Largest-first, capped at ``max_k``.
    """
    h, w = mask.shape[:2]
    min_area = max(1, int(DEEP["min_component_frac"] * w * h))
    n, _, stats, _ = cv2.connectedComponentsWithStats(
        mask.astype(np.uint8), connectivity=8)
    regions = []
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < min_area:
            continue
        x, y = stats[i, cv2.CC_STAT_LEFT], stats[i, cv2.CC_STAT_TOP]
        bw, bh = stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]
        regions.append({"bbox": [round(x / w, 4), round(y / h, 4),
                                 round(bw / w, 4), round(bh / h, 4)],
                        "cov": round(int(stats[i, cv2.CC_STAT_AREA])
                                     / float(w * h), 4)})
    merged = _merge_boxes(regions, merge_gap)
    merged.sort(key=lambda r: -r["cov"])
    return merged[:max_k]


def edge_energy(gray: np.ndarray, bbox_norm: "list[float] | None") -> float:
    """Mean Sobel gradient magnitude inside a normalised bbox (whole frame
    when bbox is None) — text/graphic chrome reads high."""
    h, w = gray.shape[:2]
    if bbox_norm is not None:
        x0, y0 = int(bbox_norm[0] * w), int(bbox_norm[1] * h)
        x1 = min(w, x0 + max(1, int(bbox_norm[2] * w)))
        y1 = min(h, y0 + max(1, int(bbox_norm[3] * h)))
        gray = gray[y0:y1, x0:x1]
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    return float(np.sqrt(gx * gx + gy * gy).mean())


def growth_trace(frames: "list[np.ndarray]") -> dict:
    """Per-frame changed-coverage + bbox vs the FIRST frame of a run window."""
    covs: list[float] = []
    boxes: "list[list[float] | None]" = []
    for f in frames:
        region = changed_region(frames[0], f)
        covs.append(0.0 if region is None else region[1])
        boxes.append(None if region is None else region[0])
    return {"coverages": covs, "bboxes": boxes}


def _is_monotonic(covs: "list[float]") -> bool:
    """Coverage never dips more than the tolerance below its running max."""
    peak = 0.0
    for c in covs:
        if c < peak - DEEP["sweep_dip_tol"]:
            return False
        peak = max(peak, c)
    return True


def _sweep_direction(first: "list[float]", last: "list[float]") -> str:
    """Leading-edge direction from the first vs last significant bbox."""
    fx0, fy0, fw, fh = first
    lx0, ly0, lw, lh = last
    moves = {
        "from-left": (lx0 + lw) - (fx0 + fw),
        "from-right": fx0 - lx0,
        "from-top": (ly0 + lh) - (fy0 + fh),
        "from-bottom": fy0 - ly0,
    }
    return max(moves, key=lambda k: moves[k])


def sweep_from_trace(trace: dict) -> "dict | None":
    """SWEEP verdict for a run window: direction + frames, or None.

    A sweep = the changed region grows monotonically to a significant final
    coverage OVER REAL FRAMES: the growth must span at least
    ``sweep_min_growth_frames`` and no single frame may contribute
    ``sweep_max_step_frac`` of the final coverage (a hard cut followed by
    drift is a STEP, not a sweep — the phantom-sweep failure mode).
    ``frames`` counts from first visible change until coverage settles at
    ``sweep_settle_frac`` of its final value.
    """
    covs, boxes = trace["coverages"], trace["bboxes"]
    final = covs[-1]
    if final < DEEP["sweep_min_cov"] or not _is_monotonic(covs):
        return None
    visible = [i for i, c in enumerate(covs) if c > 0.5 * DEEP["sweep_min_cov"]]
    first_boxes = [b for b in boxes if b is not None]
    if not visible or len(first_boxes) < 2:
        return None
    settle = next(i for i, c in enumerate(covs)
                  if c >= DEEP["sweep_settle_frac"] * final)
    frames = max(1, settle - visible[0] + 1)
    if frames < DEEP["sweep_min_growth_frames"]:
        return None
    steps = [covs[i] - covs[i - 1] for i in range(1, settle + 1)]
    if steps and max(steps) >= DEEP["sweep_max_step_frac"] * final:
        return None
    return {"direction": _sweep_direction(first_boxes[0], first_boxes[-1]),
            "frames": frames, "finalCoverage": round(final, 4),
            "bbox": boxes[-1]}
