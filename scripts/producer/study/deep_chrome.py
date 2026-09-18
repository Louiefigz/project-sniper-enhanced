#!/usr/bin/env python3
"""deep_chrome — CHROME-REGION channel: designed panels/rails/takeovers.

The module rail-in conflation (one 19-frame "pan" swallowing a lower-third
fade-OUT + a rail sweep-IN + a face glide) is separated by REGION: designed
chrome is a connected cluster of FLAT blocks (low texture std) carrying glyph
edges, and each cluster gets its OWN timeline inside the run window:

* IN  — flat-in-END clusters that changed vs the start frame; the per-frame
        MATCH-TO-END coverage inside the cluster bbox gives arrival start,
        duration, easing and (for monotonic >=5-frame growth) the sweep
        direction.
* OUT — flat-in-START clusters that changed; their DIVERGENCE-FROM-START
        trace gives the departure start. A cluster that only starts changing
        once an IN cluster's arrival reaches it was merely covered — no
        event; one that diverges >= ``chrome_out_lead_frames`` earlier left
        on its own (the lower-third fading before the rail lands).

All pure pixel arithmetic on the decoded run window; thresholds in
deep_config (chrome_*).
"""

from __future__ import annotations

import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from study.deep_config import DEEP  # noqa: E402
from study.deep_easing import classify_motion  # noqa: E402
from study.deep_regions import (  # noqa: E402
    _sweep_direction, components_bbox, edge_energy)


def _block_std(gray: np.ndarray, block: int) -> np.ndarray:
    """Per-block pixel std (grid array)."""
    h, w = gray.shape[:2]
    gh, gw = h // block, w // block
    view = gray[:gh * block, :gw * block].astype(np.float32)
    view = view.reshape(gh, block, gw, block).transpose(0, 2, 1, 3)
    return view.reshape(gh, gw, block * block).std(axis=2)


def _block_delta(a: np.ndarray, b: np.ndarray, block: int) -> np.ndarray:
    """Per-block mean |a-b| (grid array)."""
    h, w = a.shape[:2]
    gh, gw = h // block, w // block
    diff = np.abs(a[:gh * block, :gw * block].astype(np.float32)
                  - b[:gh * block, :gw * block].astype(np.float32))
    diff = diff.reshape(gh, block, gw, block).transpose(0, 2, 1, 3)
    return diff.reshape(gh, gw, block * block).mean(axis=2)


def _block_edge_max(frame: np.ndarray, bbox: list, block: int) -> float:
    """Max per-block edge energy inside a bbox — the glyph detector.

    Mean edge over a big flat panel DILUTES its sparse glyphs to nothing;
    the glyph blocks themselves always read high."""
    crop = _bbox_slice(frame, bbox)
    best = 0.0
    for y in range(0, max(1, crop.shape[0] - block + 1), block):
        for x in range(0, max(1, crop.shape[1] - block + 1), block):
            best = max(best, edge_energy(crop[y:y + block, x:x + block], None))
    return best


def _clusters(grid: np.ndarray, frame: np.ndarray, block: int) -> list[dict]:
    """Connected flat+changed grid clusters → [{"bbox", "cov"}] (gated).

    Two gates keep footage out: the cluster must contain at least one
    glyph/border block (a bare wall is flat but empty) and its fill must be
    near-extreme luma (designed chrome is cream/white/black; a sweater or
    wall is mid-toned and flat)."""
    n, _, stats, _ = cv2.connectedComponentsWithStats(
        grid.astype(np.uint8), connectivity=8)
    gh, gw = grid.shape
    out = []
    for i in range(1, n):
        cov = stats[i, cv2.CC_STAT_AREA] / float(gh * gw)
        if cov < DEEP["chrome_min_cov"]:
            continue
        bbox = [stats[i, cv2.CC_STAT_LEFT] / gw, stats[i, cv2.CC_STAT_TOP] / gh,
                stats[i, cv2.CC_STAT_WIDTH] / gw,
                stats[i, cv2.CC_STAT_HEIGHT] / gh]
        bbox = [round(v, 4) for v in bbox]
        if _block_edge_max(frame, bbox, block) < DEEP["chrome_edge_min"]:
            continue  # flat but glyph-less (a bare wall) — not chrome
        fill = float(np.median(_bbox_slice(frame, bbox)))
        if DEEP["chrome_dark_luma"] < fill < DEEP["chrome_bright_luma"]:
            continue  # mid-toned flat region (sweater/wall) — not chrome
        out.append({"bbox": bbox, "cov": round(cov, 4)})
    return out


def _bbox_slice(frame: np.ndarray, bbox: list) -> np.ndarray:
    h, w = frame.shape[:2]
    x0, y0 = int(bbox[0] * w), int(bbox[1] * h)
    x1 = min(w, x0 + max(1, int(bbox[2] * w)))
    y1 = min(h, y0 + max(1, int(bbox[3] * h)))
    return frame[y0:y1, x0:x1]


def _keep_mask(shape: tuple, bbox: list,
               exclude: "list[list] | None") -> "np.ndarray | None":
    """Boolean keep-mask for a bbox crop, excluded regions punched out.

    Other events' regions (a departing lower-third under an arriving rail,
    the face-glide corridor through a takeover) would contaminate a
    cluster's timeline — their pixels are excluded from the trace."""
    if not exclude:
        return None
    h, w = shape
    x0, y0 = int(bbox[0] * w), int(bbox[1] * h)
    keep = np.ones((min(h, y0 + max(1, int(bbox[3] * h))) - y0,
                    min(w, x0 + max(1, int(bbox[2] * w))) - x0), dtype=bool)
    for ex in exclude:
        ex0 = max(0, int(ex[0] * w) - x0)
        ey0 = max(0, int(ex[1] * h) - y0)
        ex1 = max(0, int((ex[0] + ex[2]) * w) - x0)
        ey1 = max(0, int((ex[1] + ex[3]) * h) - y0)
        keep[ey0:ey1, ex0:ex1] = False
    if keep.all() or not keep.any():
        return None            # nothing excluded / nothing left — trace whole
    return keep


def _match_trace(frames: list, ref: np.ndarray, bbox: list,
                 exclude: "list[list] | None" = None) -> list[float]:
    """Per-frame fraction of bbox pixels matching the reference frame."""
    ref_crop = _bbox_slice(ref, bbox).astype(np.int16)
    keep = _keep_mask(ref.shape[:2], bbox, exclude)
    trace = []
    for f in frames:
        crop = _bbox_slice(f, bbox).astype(np.int16)
        match = np.abs(crop - ref_crop) <= DEEP["diff_thresh"]
        trace.append(float(match[keep].mean() if keep is not None
                           else match.mean()))
    return trace


def _sweep_dir(frames: list, post: np.ndarray, bbox: list,
               first: int, last: int) -> "str | None":
    """Leading-edge direction of the arriving chrome inside its bbox."""
    def matched_box(k: int):
        crop_ref = _bbox_slice(post, bbox).astype(np.int16)
        crop = _bbox_slice(frames[k], bbox).astype(np.int16)
        region = components_bbox(np.abs(crop - crop_ref)
                                 <= DEEP["diff_thresh"])
        return region[0] if region else None
    early = matched_box(min(first + 1, last))
    late = matched_box(last)
    if early is None or late is None:
        return None
    return _sweep_direction(early, late)


def chrome_regions(pre: np.ndarray, post: np.ndarray) -> dict:
    """{"in": [clusters flat in post], "out": [clusters flat in pre]}."""
    block = max(8, int(round(pre.shape[1] / (640 / DEEP["chrome_block_px"]))))
    delta = _block_delta(pre, post, block) >= DEEP["chrome_delta_min"]
    flat_post = _block_std(post, block) < DEEP["chrome_flat_std"]
    flat_pre = _block_std(pre, block) < DEEP["chrome_flat_std"]
    return {"in": _clusters(flat_post & delta, post, block),
            "out": _clusters(flat_pre & delta, pre, block)}


def _visible_span(trace: list[float]) -> "tuple[int, int] | None":
    """(first, last) of the VISIBLE arrival: the hand-countable growth.

    The step/ease verdict uses the 8-92% core, but what the acid GT counts
    as 'sweep frames' runs from the first visible change (``chrome_vis_lo``)
    until the region is essentially arrived (``chrome_vis_hi``) — the soft
    compression asymptote past that isn't visible motion."""
    lo, hi = trace[0], trace[-1]
    if hi - lo < 1e-6:
        return None
    prog = [(v - lo) / (hi - lo) for v in trace]
    first = next((k for k, p in enumerate(prog)
                  if p >= DEEP["chrome_vis_lo"]), None)
    last = next((k for k in range(len(prog) - 1, -1, -1)
                 if prog[k] <= DEEP["chrome_vis_hi"]), None)
    if first is None or last is None or last < first:
        return None
    return first, min(last + 1, len(prog) - 1)


def _in_event(frames: list, post: np.ndarray, cluster: dict,
              exclude: "list[list] | None" = None) -> "dict | None":
    """Arrival verdict for one IN cluster: start k, frames, easing, sweep."""
    trace = _match_trace(frames, post, cluster["bbox"], exclude)
    verdict = classify_motion(trace)
    if verdict is None:
        return None
    first, last = verdict["first"], verdict["last"]
    if trace[last] - trace[first] < 0.3:
        return None
    span = _visible_span(trace) or (first, last)
    vis_frames = span[1] - span[0] + 1
    transition = None
    if verdict["kind"] == "step":
        transition = {"class": "pop", "direction": None,
                      "frames": verdict["activeFrames"]}
    elif verdict["activeFrames"] >= DEEP["sweep_min_growth_frames"]:
        steps = [trace[i] - trace[i - 1] for i in range(first + 1, last + 1)]
        if min(steps) > -0.05:  # monotonic-enough growth = sweep
            transition = {"class": "sweep",
                          "direction": _sweep_dir(frames, post,
                                                  cluster["bbox"], first, last),
                          "frames": vis_frames}
    return {"k": span[0], "frames": vis_frames,
            "easing": verdict["easing"], "transition": transition,
            "bbox": cluster["bbox"], "cov": cluster["cov"]}


def _out_event(frames: list, pre: np.ndarray, cluster: dict,
               in_starts: list[int]) -> "dict | None":
    """Departure verdict for one OUT cluster (None when merely covered)."""
    trace = _match_trace(frames, pre, cluster["bbox"])
    div = [1.0 - m for m in trace]
    peak = max(div)
    if peak < 0.3:
        return None
    div_start = next(i for i, v in enumerate(div)
                     if v >= max(0.08, 0.1 * peak))
    covered_by = [s for s in in_starts
                  if div_start > s - DEEP["chrome_out_lead_frames"]]
    if covered_by:
        return None
    settle = next((i for i, v in enumerate(div)
                   if v >= DEEP["chrome_match_settle"] * peak), len(div) - 1)
    return {"k": div_start, "frames": max(1, settle - div_start + 1),
            "easing": None, "transition": None,
            "bbox": cluster["bbox"], "cov": cluster["cov"]}


def chrome_channel(rw) -> list[dict]:
    """All chrome verdicts for one decoded run window (raw, not events).

    Returns [{"inout", "k", "frames", "bbox", "cov", "easing",
    "transition"}] — ``k`` indexes ``rw.frames``. A region that left ON ITS
    OWN (an emitted out event — the lower-third fading before the rail
    lands) is excluded from the in-clusters' traces so its departure never
    smears their timing; a region merely COVERED by the arrival stays in
    (it IS part of the arrival).
    """
    pre, post = rw.ends
    clusters = chrome_regions(pre, post)
    ins = [(cl, _in_event(rw.frames, post, cl)) for cl in clusters["in"]]
    in_starts = [ev["k"] for _, ev in ins if ev is not None]
    outs = []
    for cl in clusters["out"]:
        ev = _out_event(rw.frames, pre, cl, in_starts)
        if ev is not None:
            outs.append({"inout": "out", **ev})
    results = list(outs)
    exclude = [r["bbox"] for r in outs]
    for cl, ev in ins:
        if exclude:
            ev = _in_event(rw.frames, post, cl, exclude)
        if ev is not None:
            results.append({"inout": "in", **ev})
    return results
