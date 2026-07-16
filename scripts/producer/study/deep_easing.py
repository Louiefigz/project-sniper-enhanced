#!/usr/bin/env python3
"""deep_easing — EASING FIT: least-squares model fit for multi-frame motions.

Given a measured progress path (per-frame zoom scale, pan displacement or sweep
coverage), normalise it to [0,1] and fit four canonical easing shapes with one
free amplitude each (pure numpy arithmetic, closed-form least squares):

* ``linear``      p(u) = u
* ``power2-out``  p(u) = 1 - (1-u)^2
* ``power3-out``  p(u) = 1 - (1-u)^3
* ``bell``        p(u) = u^2(3-2u)   (smoothstep — bell-shaped increments)

Reports every model's R² plus the winner. A path too short or too flat to
discriminate returns None (the event simply carries no easing block).
"""

from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from study.deep_config import DEEP  # noqa: E402

MIN_SAMPLES = 5           # fewer frames can't discriminate the shapes
MIN_SPAN = 1e-6           # flat paths carry no easing information


def active_span(path: "list[float]") -> "tuple[int, int, int] | None":
    """(lo_cross, hi_cross, fit_hi) — the ACTIVE portion of a motion path.

    A run window is padded with settled frames; fitting easing over the pads
    turns every step into a fake power-out and every glide into a bell.
    ``lo_cross``/``hi_cross`` = where normalised progress first crosses
    ``active_lo``/``active_hi`` (the visible-motion core; a step completes
    lo→hi in <= step_max_frames). ``fit_hi`` = the core end plus an equal
    tail allowance — a power-out's asymptotic tail is as long as its core
    and carries the shape information, while anything beyond is pad. None
    when the path is flat or too short to bound.
    """
    arr = np.asarray(path, dtype=np.float64)
    if arr.size < 2:
        return None
    span = arr[-1] - arr[0]
    if abs(span) < MIN_SPAN:
        return None
    prog = (arr - arr[0]) / span
    above_lo = np.nonzero(prog >= DEEP["active_lo"])[0]
    above_hi = np.nonzero(prog >= DEEP["active_hi"])[0]
    if above_lo.size == 0 or above_hi.size == 0:
        return None
    lo_cross, hi_cross = int(above_lo[0]), int(above_hi[0])
    core = max(1, hi_cross - lo_cross)
    fit_hi = min(arr.size - 1, hi_cross + core)
    return lo_cross, hi_cross, fit_hi


def _models(u: np.ndarray) -> dict[str, np.ndarray]:
    """The four canonical progress curves sampled at ``u``."""
    return {
        "linear": u,
        "power2-out": 1.0 - (1.0 - u) ** 2,
        "power3-out": 1.0 - (1.0 - u) ** 3,
        "bell": u * u * (3.0 - 2.0 * u),
    }


def normalize_progress(path: "list[float]") -> "np.ndarray | None":
    """Map a raw motion path onto [0,1] progress (None when degenerate)."""
    arr = np.asarray(path, dtype=np.float64)
    if arr.size < MIN_SAMPLES:
        return None
    span = arr[-1] - arr[0]
    if abs(span) < MIN_SPAN:
        return None
    return (arr - arr[0]) / span


def classify_motion(path: "list[float]") -> "dict | None":
    """STEP-vs-EASED verdict for a motion path (the fix-4 single source).

    Returns ``{"kind": "step"|"eased"|"drift", "first", "last",
    "activeFrames", "easing"}`` or None for flat/short paths. A motion whose
    active span completes in <= ``step_max_frames`` is a STEP — never eased;
    easing is fitted (over the active span only) when the active span is
    >= ``ease_min_frames``; anything between is a plain drift (no easing).
    """
    span = active_span(path)
    if span is None:
        return None
    lo_cross, hi_cross, fit_hi = span
    first = max(0, lo_cross - 1)
    frames = hi_cross - first + 1
    verdict = {"kind": "drift", "first": first, "last": hi_cross,
               "activeFrames": frames, "easing": None}
    if hi_cross - first <= DEEP["step_max_frames"]:
        verdict["kind"] = "step"
        return verdict
    if frames >= DEEP["ease_min_frames"]:
        verdict["kind"] = "eased"
        verdict["last"] = fit_hi
        verdict["easing"] = fit_easing(list(path[first:fit_hi + 1]))
    return verdict


def fit_easing(path: "list[float]") -> "dict | None":
    """Best-fit easing for a measured motion path.

    Returns ``{"bestFit", "r2", "fits": {model: r2}}`` or None when the path
    is too short/flat. Each model gets one least-squares amplitude
    ``a = Σ y·m / Σ m²`` before scoring R² — so a slightly over/undershooting
    measurement still matches its true shape.
    """
    y = normalize_progress(path)
    if y is None:
        return None
    u = np.linspace(0.0, 1.0, y.size)
    ss_tot = float(((y - y.mean()) ** 2).sum())
    if ss_tot < MIN_SPAN:
        return None
    fits: dict[str, float] = {}
    for name, m in _models(u).items():
        denom = float((m * m).sum())
        a = float((y * m).sum()) / denom if denom > 0 else 0.0
        ss_res = float(((y - a * m) ** 2).sum())
        fits[name] = round(1.0 - ss_res / ss_tot, 4)
    best = max(fits, key=lambda k: fits[k])
    return {"bestFit": best, "r2": fits[best], "fits": fits}
