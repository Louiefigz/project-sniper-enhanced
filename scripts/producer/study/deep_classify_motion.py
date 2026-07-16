#!/usr/bin/env python3
"""deep_classify_motion — no-face motion probes for run windows.

The face channel (deep_face) owns framing verdicts whenever a Haar track is
available; these ORB/phase/region probes cover everything else (synthetic
clips, faceless b-roll, camera moves). Every probe goes through the shared
STEP-vs-EASED gate (deep_easing.classify_motion): a motion completing in
<= ``step_max_frames`` is a hard cut (class ``step`` boundary), NEVER an
eased zoom/pan — the acid study's 7 phantom "eased power3-out zooms" were all
1-3-frame steps. Easing fits only over the ACTIVE span (the settled pads
either side of a run otherwise fake a power-out on every step).
"""

from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from study.deep_config import DEEP  # noqa: E402
from study.deep_easing import classify_motion, fit_easing  # noqa: E402
from study.deep_regions import (  # noqa: E402
    changed_region, growth_trace, sweep_from_trace)
from study.deep_regions_inout import inout_verdict  # noqa: E402
from study.zoom_scale import estimate_scale_frames  # noqa: E402


def base_event(sig, frame: int, etype: str, **fields) -> dict:
    """Base event dict (t derived from the analysis frame index)."""
    ev = {"t": sig.t(frame), "frame": frame, "type": etype,
          "durationFrames": 1, "bbox": None, "coverage": None,
          "transition": None, "easing": None, "detail": {}}
    ev.update(fields)
    return ev


def _step_cut(ctx, frame: int, frames: int, scale: "float | None") -> dict:
    """A <=3-frame motion step = a jump/punch CUT, never an eased move."""
    detail = {}
    if scale is not None:
        detail = {"punch": "in" if scale > 1.0 else "out",
                  "dScalePct": round((scale - 1.0) * 100.0, 1),
                  "scaleSource": "orb"}
    return base_event(ctx.sig, frame, "cut",
                      magnitude=round(ctx.sig.d[frame], 2),
                      transition={"class": "hard-cut", "direction": None,
                                  "frames": frames},
                      detail=detail)


def _scale_path(frames: list) -> tuple[list[float], list[int], int]:
    """Cumulative ORB scale frame0→frame_i + the frame offset of each point."""
    path, ks, inliers = [1.0], [0], 0
    for k, f in enumerate(frames[1:], start=1):
        est = estimate_scale_frames(frames[0], f)
        if not est.ok:
            continue
        path.append(est.scale)
        ks.append(k)
        inliers = max(inliers, est.inliers)
    return path, ks, inliers


def try_zoom(ctx, rw) -> "dict | None":
    """Animated zoom (ORB scale ramp) — or a step, which becomes a cut."""
    path, ks, inliers = _scale_path(rw.run_frames)
    if len(path) < 3 or inliers < DEEP["zoom_min_inliers"]:
        return None
    scale = path[-1]
    if abs(scale - 1.0) < DEEP["zoom_scale_min"]:
        return None
    verdict = classify_motion(path)
    if verdict is None:
        return None
    first_f = rw.start + ks[verdict["first"]]
    active = ks[verdict["last"]] - ks[verdict["first"]] + 1
    if verdict["kind"] == "step":
        return _step_cut(ctx, first_f, active, scale)
    etype = "zoom-in" if scale > 1.0 else "zoom-out"
    return base_event(ctx.sig, first_f, etype, durationFrames=active,
                      magnitude=round(abs(scale - 1.0), 4),
                      easing=fit_easing(path),  # detector-bounded: fit whole
                      detail={"scale": round(scale, 4), "inliers": inliers})


def try_pan(ctx, rw) -> "dict | None":
    """Pan: cumulative phase-correlation drift with no scale change."""
    cum, path = (0.0, 0.0), [0.0]
    for i in range(rw.start, rw.end + 1):
        cum = (cum[0] + ctx.sig.pan_dx[i], cum[1] + ctx.sig.pan_dy[i])
        path.append(math.hypot(*cum))
    if path[-1] < DEEP["pan_min_px"]:
        return None
    est = estimate_scale_frames(*rw.ends)
    if est.ok and abs(est.scale - 1.0) > DEEP["pan_scale_tol"]:
        return None
    verdict = classify_motion(path)
    if verdict is None:
        return None
    if verdict["kind"] == "step":
        return _step_cut(ctx, rw.start + verdict["first"],
                         verdict["activeFrames"], None)
    axis = "x" if abs(cum[0]) >= abs(cum[1]) else "y"
    direction = {("x", True): "left", ("x", False): "right",
                 ("y", True): "up", ("y", False): "down"}[
                     (axis, (cum[0] if axis == "x" else cum[1]) < 0)]
    px_src = path[-1] * ctx.info.width / ctx.sig.width
    return base_event(ctx.sig, rw.start + max(0, verdict["first"] - 1), "pan",
                      durationFrames=verdict["activeFrames"],
                      magnitude=round(px_src, 1),
                      easing=fit_easing(path),  # detector-bounded: fit whole
                      detail={"dxPx": round(cum[0], 2),
                              "dyPx": round(cum[1], 2),
                              "direction": direction,
                              "analysisWidth": ctx.sig.width})


def try_flash_fade(ctx, rw) -> "dict | None":
    """Run-shaped flash (spike and return) or fade (global luma ramp)."""
    lumas = ctx.sig.luma[rw.start:rw.end + 1]
    region = changed_region(*rw.ends)
    settle_cov = 0.0 if region is None else region[1]
    spike = max(lumas) - max(lumas[0], lumas[-1])
    dip = min(lumas[0], lumas[-1]) - min(lumas)
    if (max(spike, dip) >= DEEP["flash_luma_min"]
            and settle_cov < DEEP["flash_settle_cov"]):
        return base_event(ctx.sig, rw.start, "flash",
                          durationFrames=rw.end - rw.start,
                          magnitude=round(max(spike, dip), 2),
                          transition={"class": "flash", "direction": None,
                                      "frames": rw.end - rw.start})
    ramp = lumas[-1] - lumas[0]
    if (abs(ramp) >= DEEP["fade_luma_min"]
            and settle_cov >= DEEP["global_frac"]):
        return base_event(ctx.sig, rw.start, "cut",
                          durationFrames=rw.end - rw.start,
                          coverage=settle_cov, magnitude=round(abs(ramp), 2),
                          transition={"class": "fade", "direction": None,
                                      "frames": rw.end - rw.start})
    return None


def try_sweep(ctx, rw) -> "dict | None":
    """Sweep: monotonic >=5-frame region growth — direction + frames."""
    trace = growth_trace(rw.frames)
    sweep = sweep_from_trace(trace)
    if sweep is None:
        return None
    cov = sweep["finalCoverage"]
    kind = "panel" if cov >= DEEP["panel_frac"] else "graphic"
    verdict = inout_verdict(rw.frames[0], rw.frames[-1], sweep["bbox"])
    covs = trace["coverages"]
    grow = [i for i, c in enumerate(covs) if c > 0.5 * DEEP["sweep_min_cov"]]
    ease_path = covs[grow[0]:grow[0] + sweep["frames"] + 1] if grow else covs
    return base_event(ctx.sig, rw.start, f"{kind}-{verdict}",
                      durationFrames=sweep["frames"], bbox=sweep["bbox"],
                      coverage=cov, magnitude=cov,
                      easing=fit_easing(ease_path),
                      transition={"class": "sweep",
                                  "direction": sweep["direction"],
                                  "frames": sweep["frames"]})
