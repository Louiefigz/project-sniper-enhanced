#!/usr/bin/env python3
"""deep_regions_inout — IN vs OUT verdict for a changed region (pure pixels).

Did the changed region END with a graphic (in) or LOSE one (out)? Designed
chrome in this grammar is HIGH-CONTRAST: flat fills, white/yellow glyphs,
black strokes — so the strongest deterministic tell is the EXTREME-LUMA pixel
fraction inside the bbox (pixels beyond the dark/bright thresholds): it jumps
when chrome/text arrives and falls when footage is restored. Ties resolve by
size: small regions (text pops) go to EDGE ENERGY (glyphs add edges), large
regions (panels/cards) go to texture STD (flat chrome reads flatter than
footage). The acid study measured ~6/20 in/out inversions with the old
std-first order on text pops; extreme-frac-first fixes the text case without
breaking the panel case. Known failure mode — a graphic busier AND
mid-toned vs the footage under it — is documented in DEEP_SCHEMA.md; the
optional semantics layer is the override, never a code fallback.
"""

from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from study.deep_config import DEEP  # noqa: E402
from study.deep_regions import edge_energy  # noqa: E402

STD_RATIO = 1.08          # std must differ by this factor to decide


def _crop(gray: np.ndarray, bbox_norm: "list[float] | None") -> np.ndarray:
    """The bbox crop of a grayscale frame (whole frame when None)."""
    if bbox_norm is None:
        return gray
    h, w = gray.shape[:2]
    x0, y0 = int(bbox_norm[0] * w), int(bbox_norm[1] * h)
    x1 = min(w, x0 + max(1, int(bbox_norm[2] * w)))
    y1 = min(h, y0 + max(1, int(bbox_norm[3] * h)))
    return gray[y0:y1, x0:x1]


def region_std(gray: np.ndarray, bbox_norm: "list[float] | None") -> float:
    """Pixel std inside a normalised bbox (whole frame when None)."""
    return float(_crop(gray, bbox_norm).std())


def extreme_frac(gray: np.ndarray, bbox_norm: "list[float] | None") -> float:
    """Fraction of bbox pixels beyond the dark/bright luma thresholds."""
    crop = _crop(gray, bbox_norm)
    return float(((crop < DEEP["dark_luma"])
                  | (crop > DEEP["bright_luma"])).mean())


def _extreme_verdict(pre: np.ndarray, post: np.ndarray,
                     bbox: "list[float] | None") -> "str | None":
    """Chrome = high-contrast: the side with more extreme pixels has it.

    Only decisive when the lesser side reads footage-like (mid-toned,
    ``inout_extreme_bgmax``) — text popping ON a dark panel keeps both sides
    extreme and must fall through to the edge/std tells.
    """
    ext_pre, ext_post = extreme_frac(pre, bbox), extreme_frac(post, bbox)
    if min(ext_pre, ext_post) > DEEP["inout_extreme_bgmax"]:
        return None
    ratio, floor = DEEP["inout_extreme_ratio"], DEEP["inout_extreme_min"]
    if ext_post >= max(ext_pre * ratio, ext_pre + floor):
        return "in"
    if ext_pre >= max(ext_post * ratio, ext_post + floor):
        return "out"
    return None


def inout_verdict(pre: np.ndarray, post: np.ndarray,
                  bbox_norm: "list[float] | None") -> str:
    """"in" when the region ends with the graphic, "out" otherwise."""
    verdict = _extreme_verdict(pre, post, bbox_norm)
    if verdict is not None:
        return verdict
    area = ((bbox_norm[2] * bbox_norm[3]) if bbox_norm is not None else 1.0)
    edge_pre = edge_energy(pre, bbox_norm)
    edge_post = edge_energy(post, bbox_norm)
    if area < DEEP["inout_edge_max_area"]:      # text-scale: glyphs add edges
        return "in" if edge_post >= edge_pre else "out"
    std_pre = region_std(pre, bbox_norm)        # panel-scale: chrome is flat
    std_post = region_std(post, bbox_norm)
    if std_post * STD_RATIO < std_pre:
        return "in"
    if std_pre * STD_RATIO < std_post:
        return "out"
    return "in" if edge_post >= edge_pre else "out"
