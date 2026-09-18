#!/usr/bin/env python3
"""zoom_scale — direct whole-frame ZOOM magnitude between two frames (STUDY verb).

Face-area (``study_zoom_faces``) is a noisy zoom proxy: on this reference the
presenter's face is only ~2% of the frame, so YuNet's box jitters ±10% with NO
zoom at all — it can't see a subtle push-in. This module measures the zoom
DIRECTLY off the whole frame instead.

The camera is locked, so between two frames of the same shot the ONLY global
geometric change is the editor's scale keyframe. ORB features on the static
background (shelves, wall, desk) are matched and fed to
``estimateAffinePartial2D`` (a similarity transform: uniform scale + rotation +
translation) with RANSAC — the moving head/hands fall out as outliers. The
uniform scale of that transform IS the zoom factor: >1 = push-in, <1 = pull-out.

Validated against the RAW locked camera (no zoom): scale ≈ 1.00 ± the tiny
residual reported in docs/studies/LONGFORM_VISUAL_STUDY.md, well under a real punch. Uses
cv2 — run with the venv python.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass

import cv2
import numpy as np

_FRAME_RE = re.compile(r"(?:frame|f)_(\d+)\.jpg$")
ORB_FEATURES = 1500
MATCH_RATIO = 0.75          # Lowe ratio for the knn match filter
MIN_INLIERS = 12            # fewer good matches ⇒ untrusted (scene change / blur)
ANALYSIS_W = 640            # ORB runs at this width (speed; scale is a ratio)


@dataclass
class ScaleEstimate:
    """Similarity-transform scale between two frames + its trust signals."""

    scale: float             # >1 push-in, <1 pull-out, 1.0 no zoom
    inliers: int             # RANSAC inliers backing the estimate
    matches: int             # raw good matches before RANSAC
    ok: bool                 # inliers >= MIN_INLIERS and a transform was found


def _prep(path: str) -> "np.ndarray | None":
    """Load a frame as grayscale, downscaled to ANALYSIS_W (or None)."""
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    w = img.shape[1]
    if w > ANALYSIS_W:
        scale = ANALYSIS_W / float(w)
        img = cv2.resize(img, (ANALYSIS_W, int(img.shape[0] * scale)))
    return img


def estimate_scale_frames(gray_a: "np.ndarray", gray_b: "np.ndarray") -> ScaleEstimate:
    """Similarity scale mapping frame A → frame B (both grayscale)."""
    orb = cv2.ORB_create(ORB_FEATURES)
    ka, da = orb.detectAndCompute(gray_a, None)
    kb, db = orb.detectAndCompute(gray_b, None)
    if da is None or db is None or len(ka) < MIN_INLIERS or len(kb) < MIN_INLIERS:
        return ScaleEstimate(1.0, 0, 0, False)
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    good = _ratio_matches(matcher, da, db)
    if len(good) < MIN_INLIERS:
        return ScaleEstimate(1.0, 0, len(good), False)
    src = np.float32([ka[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([kb[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    matrix, inliers = cv2.estimateAffinePartial2D(
        src, dst, method=cv2.RANSAC, ransacReprojThreshold=3.0)
    if matrix is None or inliers is None:
        return ScaleEstimate(1.0, 0, len(good), False)
    scale = float(np.sqrt(matrix[0, 0] ** 2 + matrix[1, 0] ** 2))
    n_in = int(inliers.sum())
    return ScaleEstimate(round(scale, 4), n_in, len(good), n_in >= MIN_INLIERS)


def _ratio_matches(matcher: "cv2.BFMatcher", da, db) -> list:
    """Lowe-ratio-filtered knn matches (drops ambiguous descriptor pairs)."""
    good = []
    for pair in matcher.knnMatch(da, db, k=2):
        if len(pair) == 2 and pair[0].distance < MATCH_RATIO * pair[1].distance:
            good.append(pair[0])
    return good


def estimate_scale_paths(path_a: str, path_b: str) -> ScaleEstimate:
    """Similarity scale between two frame JPGs on disk."""
    ga, gb = _prep(path_a), _prep(path_b)
    if ga is None or gb is None:
        return ScaleEstimate(1.0, 0, 0, False)
    return estimate_scale_frames(ga, gb)


def frame_index(frames_dir: str) -> dict[float, str]:
    """Map timestamp→path for a ``frame_%06d.jpg`` / ``f_%06d.jpg`` dir at 5fps."""
    out: dict[int, str] = {}
    for name in os.listdir(frames_dir):
        m = _FRAME_RE.search(name)
        if m:
            out[int(m.group(1))] = os.path.join(frames_dir, name)
    return out


def path_at(index: dict, seq_by_t, t: float, fps: float) -> "str | None":
    """Path of the frame nearest time ``t`` (fps→sequence), or None."""
    seq = int(round(t * fps)) + 1
    return index.get(seq) or index.get(seq - 1) or index.get(seq + 1)


if __name__ == "__main__":   # tiny smoke test: scale between two frame paths
    est = estimate_scale_paths(sys.argv[1], sys.argv[2])
    print(est)
