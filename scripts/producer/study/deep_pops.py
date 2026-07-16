#!/usr/bin/env python3
"""deep_pops — the POP SCAN: localized instant graphics the d-metric misses.

The acid study's headline miss: keyword pops (big yellow serif landing for
0.6-1.0s) sit at global d ≈ 3-4 on a talking head's ≈2 noise floor — no
global threshold can find them, and on busy footage even a consecutive-frame
region diff drowns in body sway. The tell that survives sway is PER-PIXEL
FREEZE: rendered chrome is pixel-frozen while footage keeps moving. A pop is
a component of pixels that CHANGED at one boundary and are FROZEN on one
side of it:

* frozen AFTER  → the graphic landed (in)
* frozen BEFORE → the graphic left (out)

Two rejection gates keep footage honest: a TRANSLATION check (content that
merely moved with the body/camera — a shirt logo — matches its own pre-frame
neighbourhood) and the caption-band geometry gate (caption-slot word swaps
belong to the caption system, not the event list). Consecutive candidates
chain into short BUILDS (a drawn arrow, a growing list) with true start +
duration. One extra streaming pass (ring buffer, memory-safe); every verdict
is pixel arithmetic; thresholds in deep_config (pop_*).
"""

from __future__ import annotations

import os
import sys
from collections import deque

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from study.deep_config import DEEP  # noqa: E402
from study.deep_frames import VideoInfo, iter_gray  # noqa: E402
from study.deep_regions import component_regions, diff_mask  # noqa: E402
from study.deep_regions_inout import inout_verdict  # noqa: E402
from study.deep_signals import SignalTrack  # noqa: E402

GUARD_TYPES = {"cut", "flash"}      # whole-frame boundaries: no pops nearby


def _guard_frames(events: list[dict]) -> set[int]:
    """Frames adjacent to whole-frame boundaries (cuts/flashes)."""
    guard = set()
    pad = DEEP["pop_cut_guard_frames"]
    for ev in events:
        if ev["type"] not in GUARD_TYPES:
            continue
        for k in range(ev["frame"] - pad, ev["frame"]
                       + ev.get("durationFrames", 1) + pad + 1):
            guard.add(k)
    return guard


def _caption_scale(bbox: list) -> bool:
    """Caption-slot geometry: small height, chest/chin band."""
    lo, hi = DEEP["pop_caption_band"]
    y_center = bbox[1] + bbox[3] / 2.0
    return bbox[3] <= DEEP["pop_caption_max_h"] and lo <= y_center <= hi


def _crop(frame: np.ndarray, bbox: list, inflate: float = 1.0) -> np.ndarray:
    h, w = frame.shape[:2]
    cx, cy = bbox[0] + bbox[2] / 2.0, bbox[1] + bbox[3] / 2.0
    bw, bh = bbox[2] * inflate, bbox[3] * inflate
    x0, y0 = max(0, int((cx - bw / 2) * w)), max(0, int((cy - bh / 2) * h))
    x1 = min(w, x0 + max(1, int(bw * w)))
    y1 = min(h, y0 + max(1, int(bh * h)))
    return frame[y0:y1, x0:x1]


def _is_translation(cur: np.ndarray, pre: np.ndarray, bbox: list) -> bool:
    """Content that just MOVED (shirt logo, camera nudge) matches its own
    pre-frame neighbourhood; freshly rendered chrome does not."""
    patch = _crop(cur, bbox)
    hood = _crop(pre, bbox, inflate=DEEP["pop_translate_inflate"])
    if min(patch.shape[:2]) < 8 or hood.shape[0] < patch.shape[0] \
            or hood.shape[1] < patch.shape[1]:
        return False
    score = cv2.matchTemplate(hood, patch, cv2.TM_CCOEFF_NORMED)
    return float(score.max()) >= DEEP["pop_translate_ncc"]


def _tight_bbox(evidence: np.ndarray, bbox: list) -> "list | None":
    """Shrink a dilated component bbox to its evidence pixels (the dilation
    margin drags footage into OCR crops and caption-gate geometry)."""
    h, w = evidence.shape[:2]
    x0, y0 = int(bbox[0] * w), int(bbox[1] * h)
    x1 = min(w, x0 + max(1, int(bbox[2] * w)))
    y1 = min(h, y0 + max(1, int(bbox[3] * h)))
    ys, xs = np.nonzero(evidence[y0:y1, x0:x1])
    if ys.size == 0:
        return None
    return [round((x0 + xs.min()) / w, 4), round((y0 + ys.min()) / h, 4),
            round((xs.max() - xs.min() + 1) / w, 4),
            round((ys.max() - ys.min() + 1) / h, 4)]


def _region_mean(mask: np.ndarray, bbox: list) -> float:
    h, w = mask.shape[:2]
    x0, y0 = int(bbox[0] * w), int(bbox[1] * h)
    x1 = min(w, x0 + max(1, int(bbox[2] * w)))
    y1 = min(h, y0 + max(1, int(bbox[3] * h)))
    return float(mask[y0:y1, x0:x1].mean())


def _extreme(gray: np.ndarray) -> np.ndarray:
    """Chrome-coloured pixels: this grammar's fills/glyphs are near-extreme
    luma (white/yellow/cream/black-stroke); body sway is mid-toned."""
    return (gray < DEEP["dark_luma"]) | (gray > DEEP["bright_luma"])


def _boundary_candidates(ring: dict, i: int, kernel) -> list[dict]:
    """Freeze-side chrome components at boundary i → raw pop candidates.

    Evidence pixels only: IN = changed & extreme-in-post & frozen-after;
    OUT = changed & extreme-in-pre & frozen-before. Restricting to extreme
    pixels is what survives busy footage — sway pixels change constantly
    but are mid-toned, so they never join a component."""
    fz = DEEP["pop_freeze_thresh"]
    frozen = lambda a, b: (np.abs(a.astype(np.int16)  # noqa: E731
                                  - b.astype(np.int16)) <= fz)
    changed = diff_mask(ring[i - 1], ring[i])
    after = frozen(ring[i], ring[i + 1]) & frozen(ring[i], ring[i + 3])
    before = frozen(ring[i - 1], ring[i - 2]) & frozen(ring[i - 1], ring[i - 4])
    in_mask = changed & after & _extreme(ring[i])
    out_mask = changed & before & _extreme(ring[i - 1])
    evidence = in_mask | out_mask
    mask = cv2.dilate(evidence.astype(np.uint8), kernel) > 0
    h, w = changed.shape[:2]
    out = []
    for comp in component_regions(mask, max_k=4):
        comp["bbox"] = _tight_bbox(evidence, comp["bbox"]) or comp["bbox"]
        if comp["cov"] < DEEP["pop_min_cov"] or _caption_scale(comp["bbox"]):
            continue
        if min(comp["bbox"][2] * w, comp["bbox"][3] * h) < DEEP["pop_min_px"]:
            continue    # a sliver too thin to verify (revealed edge, jitter)
        in_score = _region_mean(in_mask, comp["bbox"])
        out_score = _region_mean(out_mask, comp["bbox"])
        if min(in_score, out_score) >= DEEP["pop_swap_frac"] \
                * max(in_score, out_score):
            verdict = "in"      # frozen BOTH sides = an in-place SWAP = enter
        elif in_score > out_score:
            verdict = "in"
        elif out_score > in_score:
            verdict = "out"
        else:
            verdict = inout_verdict(ring[i - 1], ring[i + 3], comp["bbox"])
        anchor = ring[i] if verdict == "in" else ring[i - 1]
        other = ring[i - 1] if verdict == "in" else ring[i]
        if _is_translation(anchor, other, comp["bbox"]):
            continue
        out.append({"frame": i, "bbox": comp["bbox"], "cov": comp["cov"],
                    "verdict": verdict})
    return out


def _touch(a: list, b: list) -> bool:
    """Bboxes overlap or nearly touch (same build)."""
    gap = 0.02
    return not (a[0] > b[0] + b[2] + gap or b[0] > a[0] + a[2] + gap
                or a[1] > b[1] + b[3] + gap or b[1] > a[1] + a[3] + gap)


def _chain(cands: list[dict]) -> list[list[dict]]:
    """Group candidates into builds: near-in-time + touching-in-space."""
    chains: list[list[dict]] = []
    for c in cands:
        home = next((ch for ch in chains
                     if c["frame"] - ch[-1]["frame"] <= 2
                     and c["verdict"] == ch[-1]["verdict"]
                     and _touch(c["bbox"], ch[-1]["bbox"])), None)
        (home.append(c) if home is not None else chains.append([c]))
    return chains


def _chain_event(sig: SignalTrack, chain: list[dict]) -> "dict | None":
    """One candidate chain → a pop/build event (None: too long = a run)."""
    frames = chain[-1]["frame"] - chain[0]["frame"] + 1
    if frames > DEEP["pop_build_max_frames"]:
        return None
    x0 = min(c["bbox"][0] for c in chain)
    y0 = min(c["bbox"][1] for c in chain)
    x1 = max(c["bbox"][0] + c["bbox"][2] for c in chain)
    y1 = max(c["bbox"][1] + c["bbox"][3] for c in chain)
    bbox = [round(x0, 4), round(y0, 4), round(x1 - x0, 4), round(y1 - y0, 4)]
    cov = round(max(c["cov"] for c in chain), 4)
    kind = "panel" if cov >= DEEP["panel_frac"] else "graphic"
    start = chain[0]["frame"]
    transition = ({"class": "pop", "direction": None, "frames": frames}
                  if frames <= DEEP["pop_max_frames"] else None)
    return {"t": sig.t(start), "frame": start,
            "type": f"{kind}-{chain[0]['verdict']}", "durationFrames": frames,
            "bbox": bbox, "coverage": cov, "magnitude": cov,
            "transition": transition, "easing": None,
            "detail": {"source": "pop-scan"}}


def scan_pops(video: str, info: VideoInfo, sig: SignalTrack,
              events: list[dict]) -> list[dict]:
    """Full-video pop scan → schema events (deduped by the caller)."""
    guard = _guard_frames(events)
    kernel_px = max(2, int(DEEP["pop_dilate_frac"] * DEEP["analysis_width"]))
    kernel = np.ones((kernel_px, kernel_px), dtype=np.uint8)
    ring: deque = deque(maxlen=8)
    base = 0                        # frame index of ring[0]
    cands: list[dict] = []
    for idx, gray in enumerate(iter_gray(video, info, sig.fps,
                                         DEEP["analysis_width"])):
        ring.append(gray)
        base = idx - len(ring) + 1
        i = idx - 3                 # boundary now fully observable (i+3 seen)
        if i - 4 < base or i in guard:
            continue
        frames = {k: ring[k - base] for k in range(i - 4, i + 4)}
        cands += _boundary_candidates(frames, i, kernel)
    return [ev for ev in (_chain_event(sig, ch) for ch in _chain(cands))
            if ev is not None]
