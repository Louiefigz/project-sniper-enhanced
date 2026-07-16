#!/usr/bin/env python3
"""deep_face — the FACE CHANNEL: punches, glides and face zooms from P2.

The acid study proved the Haar track (faceX / faceWidthFrac) reproduces the
hand-measured framing facts exactly, while ORB scale across a cut boundary is
wildly off (91% error on punch magnitude). So every face-framing verdict
derives from the P2 signals themselves:

* ``face_step``     — settled-median faceW step across ONE boundary frame →
                      punch magnitude (dScalePct) + direction. Used by the
                      impulse classifier for cut events.
* ``face_run_events`` — one run window → at most ONE motion event: a 1-3
                      frame faceW step is a JUMP CUT (class ``cut``, never an
                      eased zoom); a smooth faceX glide is a ``pan``; a smooth
                      faceW ramp is a ``zoom-in/out``. Glide-vs-zoom resolves
                      by the DOMINANT axis (a lateral slide-to-PIP moves faceX
                      far more than faceW). All pure arithmetic on the signal
                      arrays; no decoding here.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from study.deep_config import DEEP  # noqa: E402
from study.deep_easing import classify_motion  # noqa: E402
from study.deep_signals import SignalTrack  # noqa: E402


def _settled_median(vals: list, present: list, lo: int, hi: int) -> "float | None":
    """Median of the face signal over [lo, hi) counting present frames only."""
    picked = sorted(vals[i] for i in range(max(0, lo), min(len(vals), hi))
                    if present[i])
    if not picked:
        return None
    return picked[len(picked) // 2]


def face_step(sig: SignalTrack, i: int, wide: bool = False) -> "dict | None":
    """Punch verdict for boundary frame ``i``: faceW step across the cut.

    Returns ``{"punch", "dScalePct", "preW", "postW"}`` or None when either
    side lacks a settled face or the step is under ``punch_facew_min``.
    ``wide`` widens the settle windows (x2 guard, x2 settle) for boundaries
    where a graphic transition occludes the face for a few frames — the
    scdet-anchored forcing uses it as its second look.
    """
    guard, settle = DEEP["face_guard_frames"], DEEP["face_settle_frames"]
    if wide:
        guard, settle = guard * 3, settle * 2
    pre = _settled_median(sig.face_w, sig.face_present,
                          i - guard - settle, i - guard)
    post = _settled_median(sig.face_w, sig.face_present,
                           i + 1 + guard, i + 1 + guard + settle)
    if not pre or not post:
        return None
    pct = (post / pre - 1.0) * 100.0
    if abs(pct) < DEEP["punch_facew_min"] * 100.0:
        return None
    return {"punch": "in" if pct > 0 else "out",
            "dScalePct": round(pct, 1),
            "preW": round(pre, 4), "postW": round(post, 4)}


def _span_paths(sig: SignalTrack, start: int, end: int) -> "tuple | None":
    """(fw_path, fx_path) over the padded span, or None without a face."""
    pad = DEEP["face_settle_frames"]
    lo, hi = max(0, start - pad), min(sig.frames, end + 1 + pad)
    present = sig.face_present[lo:hi]
    if not present or sum(present) < DEEP["face_present_min"] * len(present):
        return None
    fw = [sig.face_w[i] for i in range(lo, hi) if sig.face_present[i]]
    fx = [sig.face_x[i] for i in range(lo, hi) if sig.face_present[i]]
    idx = [i for i in range(lo, hi) if sig.face_present[i]]
    return fw, fx, idx


def _plateaus(fw: list, j: int, k: int) -> "tuple | None":
    """Settled pre/post windows around a step at j→j+k, or None."""
    pre_w = fw[max(0, j - 4):j + 1]
    post_w = fw[j + k:min(len(fw), j + k + 5)]
    if len(pre_w) < 2 or len(post_w) < 2:
        return None
    return pre_w, post_w


def _step_event(fw: list, idx: list, lo_f: int, hi_f: int) -> "dict | None":
    """Largest 1..step_max faceW step INSIDE [lo_f, hi_f] → jump-cut fields.

    The settle pads exist for the medians only — a step landing in the pads
    belongs to the neighbouring boundary, not this run. Both sides must be
    PLATEAUS (each window's spread under ``punch_plateau_frac`` of the step),
    so a fast eased glide never reads as a stack of little cuts.
    """
    best = None
    for k in range(1, DEEP["step_max_frames"] + 1):
        for j in range(len(fw) - k):
            if not lo_f <= idx[j + k] <= hi_f:
                continue
            windows = _plateaus(fw, j, k)
            if windows is None:
                continue
            pre_w, post_w = windows
            pre = sorted(pre_w)[len(pre_w) // 2]
            post = sorted(post_w)[len(post_w) // 2]
            if pre <= 0:
                continue
            pct = (post / pre - 1.0) * 100.0
            step = abs(fw[j + k] - fw[j])
            if (abs(pct) < DEEP["punch_facew_min"] * 100.0
                    or max(pre_w) - min(pre_w)
                    > DEEP["punch_plateau_frac"] * step
                    or max(post_w) - min(post_w)
                    > DEEP["punch_plateau_frac"] * step):
                continue
            if best is None or step > best["step"]:
                best = {"step": step, "frame": idx[j + k], "frames": k,
                        "punch": "in" if pct > 0 else "out",
                        "dScalePct": round(pct, 1)}
    return best


def face_run_events(sig: SignalTrack, start: int, end: int) -> list[dict]:
    """Face-channel verdicts for one run span (fields only, no event dict).

    Returns a list of raw verdicts: ``{"kind": "cut"|"pan"|"zoom", ...}`` —
    the classifier turns them into schema events.
    """
    paths = _span_paths(sig, start, end)
    if paths is None:
        return []
    fw, fx, idx = paths
    step = _step_event(fw, idx, start - 1, end + 1)
    if step is not None:
        return [{"kind": "cut", **step}]
    dx = abs(fx[-1] - fx[0])
    dw_frac = abs(fw[-1] - fw[0]) / fw[0] if fw[0] > 0 else 0.0
    glide = dx >= DEEP["face_glide_min"]
    zoom = dw_frac >= DEEP["face_zoom_min"]
    if glide and (not zoom or dx >= DEEP["face_axis_ratio"] * dw_frac):
        verdict = classify_motion(fx)
        if verdict is None or verdict["kind"] == "step":
            return []
        return [{"kind": "pan", "verdict": verdict, "idx": idx,
                 "fromX": round(fx[0], 4), "toX": round(fx[-1], 4)}]
    if zoom:
        verdict = classify_motion(fw)
        if verdict is None:
            return []
        if verdict["kind"] == "step":
            return []  # sub-threshold step: _step_event already declined it
        return [{"kind": "zoom", "verdict": verdict, "idx": idx,
                 "magnitude": round(dw_frac, 4),
                 "direction": "in" if fw[-1] > fw[0] else "out"}]
    return []
