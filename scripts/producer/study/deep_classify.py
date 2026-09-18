#!/usr/bin/env python3
"""deep_classify — P3 classifiers: one impulse or run window → EVENTS.

The detector (deep_events) finds WHERE the signals changed; this module
decodes a short window there and names WHAT happened. Both classifiers
return LISTS — co-occurring moves are separated by REGION and by SIGNAL
FAMILY instead of being conflated into one verdict:

impulse (1 frame):  flash → CUT (scdet-anchored / global coverage / faceW
                    punch step — magnitude+direction from the Haar track,
                    never ORB across a cut) → per-component localized
                    graphic/panel pops.
run (N frames):     global flash/fade → FACE channel (jump-cut step, glide
                    pan, face zoom) + CHROME channel (panel/rail/takeover
                    per-region in/out with own timing) → no-face fallbacks
                    (ORB zoom, phase pan, region sweep — all step-gated) →
                    per-component localized change.

Multi-frame motions fit easing over their ACTIVE span only; a motion
completing in <= step_max_frames is a STEP (a cut), never eased.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from study.deep_chrome import chrome_channel  # noqa: E402
from study.deep_classify_motion import (  # noqa: E402
    base_event, try_flash_fade, try_pan, try_sweep, try_zoom)
from study.deep_config import DEEP  # noqa: E402
from study.deep_face import face_run_events, face_step  # noqa: E402
from study.deep_frames import VideoInfo, Window, decode_window  # noqa: E402
from study.deep_regions import (  # noqa: E402
    changed_region, component_regions, diff_mask)
from study.deep_regions_inout import inout_verdict  # noqa: E402
from study.deep_signals import SignalTrack  # noqa: E402
from study.zoom_scale import estimate_scale_frames  # noqa: E402


@dataclass
class ClassifyCtx:
    """Everything a classifier needs about the source under study."""

    video: str
    info: VideoInfo
    sig: SignalTrack


@dataclass
class RunWindow:
    """A decoded run window: settled ends + the run frames themselves."""

    start: int                   # first analysis frame of the run
    end: int                     # last analysis frame of the run
    frames: list                 # all decoded frames incl. settled pads
    offset: int                  # index of the run's first frame in ``frames``

    @property
    def ends(self) -> tuple:
        return self.frames[0], self.frames[-1]

    @property
    def run_frames(self) -> list:
        run = self.frames[self.offset:self.offset + (self.end - self.start + 1)]
        return run if len(run) >= 2 else self.frames


def _decode_span(ctx: ClassifyCtx, first: int, last: int) -> RunWindow:
    """Gray frames (window width) covering analysis frames [first, last]."""
    pad = DEEP["window_pad_frames"]
    t0 = max(0.0, (first - pad) / ctx.sig.fps)
    t1 = min(ctx.info.duration, (last + pad + 1) / ctx.sig.fps)
    win = Window(t0=t0, t1=t1, fps=ctx.sig.fps, width=DEEP["window_width"])
    frames = decode_window(ctx.video, win, ctx.info, "gray")
    if len(frames) < 2:
        raise RuntimeError(f"event window decode came back empty at t={t0:.2f}s "
                           f"in {ctx.video}")
    return RunWindow(start=first, end=last, frames=frames,
                     offset=min(pad, first))


def _localized_events(ctx: ClassifyCtx, frame: int, rw: RunWindow,
                      duration: int = 1) -> list[dict]:
    """Per-component graphic/panel in/out events (conflation-free)."""
    pre, post = rw.ends
    events = []
    for comp in component_regions(diff_mask(pre, post)):
        if comp["cov"] < DEEP["graphic_min_cov"]:
            continue
        kind = "panel" if comp["cov"] >= DEEP["panel_frac"] else "graphic"
        verdict = inout_verdict(pre, post, comp["bbox"])
        events.append(base_event(
            ctx.sig, frame, f"{kind}-{verdict}", durationFrames=duration,
            bbox=comp["bbox"], coverage=comp["cov"],
            magnitude=round(comp["cov"], 4)))
    return events


def _is_impulse_flash(ctx: ClassifyCtx, i: int, settle_cov: float) -> bool:
    """Luma spike vs neighbours + the scene settling back = flash."""
    luma = ctx.sig.luma
    lo, hi = max(0, i - 2), min(len(luma) - 1, i + 2)
    around = max(luma[lo], luma[hi])
    return (abs(luma[i] - around) >= DEEP["flash_luma_min"]
            and settle_cov < DEEP["flash_settle_cov"])


def _cut_event(ctx: ClassifyCtx, i: int, cov: float, rw: RunWindow,
               step: "dict | None") -> dict:
    """A CUT at boundary frame i — punch from the Haar step when a face is
    tracked, from ORB across the boundary otherwise (faceless sources)."""
    detail = {}
    if step is not None:
        detail = {"punch": step["punch"], "dScalePct": step["dScalePct"],
                  "preW": step["preW"], "postW": step["postW"],
                  "scaleSource": "faceW"}
    else:
        est = estimate_scale_frames(*rw.ends)
        if est.ok and abs(est.scale - 1.0) >= DEEP["zoom_scale_min"]:
            detail = {"punch": "in" if est.scale > 1.0 else "out",
                      "dScalePct": round((est.scale - 1.0) * 100.0, 1),
                      "scaleSource": "orb"}
    return base_event(ctx.sig, i, "cut", coverage=round(cov, 4) or None,
                      magnitude=round(ctx.sig.d[i], 2),
                      transition={"class": "hard-cut", "direction": None,
                                  "frames": 1},
                      detail=detail)


def classify_impulse(ctx: ClassifyCtx, i: int,
                     scdet_frames: "tuple | list" = ()) -> list[dict]:
    """One 1-frame global d spike → flash / cut / localized pop events.

    A cut needs CUT EVIDENCE: whole-frame coverage, or a real faceW punch
    step (scdet-adjacent boundaries get a second, wider look for punches a
    graphic transition briefly occludes). An scdet hit without either is a
    GRAPHICS CLEAR — a big visual state change with no camera re-frame —
    and classifies as localized graphic events, never a cut.
    """
    rw = _decode_span(ctx, i, i)
    region = changed_region(*rw.ends)
    cov = 0.0 if region is None else region[1]
    if _is_impulse_flash(ctx, i, cov):
        return [base_event(
            ctx.sig, i, "flash",
            magnitude=round(abs(ctx.sig.luma[i]
                                - ctx.sig.luma[max(0, i - 2)]), 2),
            transition={"class": "flash", "direction": None, "frames": 1})]
    scdet = any(abs(i - f) <= 1 for f in scdet_frames)
    punch = face_step(ctx.sig, i)
    if punch is None and scdet:
        punch = face_step(ctx.sig, i, wide=True)
    if cov >= DEEP["global_frac"] or (
            punch is not None and cov >= DEEP["cut_min_cov"]) or (
            _orb_step(ctx, i, rw) and cov >= DEEP["cut_min_cov"]):
        return [_cut_event(ctx, i, cov, rw, punch)]
    if region is None:
        return []
    return _localized_events(ctx, i, rw)


def _orb_step(ctx: ClassifyCtx, i: int, rw: RunWindow) -> bool:
    """Faceless punch evidence: a trusted ORB scale step across the
    boundary. Face-tracked sources never take this path — a graphics clear
    with a static face must not read as a cut."""
    guard = DEEP["face_guard_frames"] + DEEP["face_settle_frames"]
    lo, hi = max(0, i - guard), min(ctx.sig.frames, i + guard + 1)
    if any(ctx.sig.face_present[lo:hi]):
        return False
    est = estimate_scale_frames(*rw.ends)
    return (est.ok and est.inliers >= DEEP["zoom_min_inliers"]
            and abs(est.scale - 1.0) >= DEEP["zoom_scale_min"])


def _face_event(ctx: ClassifyCtx, fv: dict) -> "dict | None":
    """One face-channel verdict → a schema event."""
    if fv["kind"] == "cut":
        ev = base_event(ctx.sig, fv["frame"], "cut",
                        magnitude=round(ctx.sig.d[fv["frame"]], 2),
                        transition={"class": "hard-cut", "direction": None,
                                    "frames": fv["frames"]},
                        detail={"punch": fv["punch"],
                                "dScalePct": fv["dScalePct"],
                                "scaleSource": "faceW"})
        return ev
    verdict, idx = fv["verdict"], fv["idx"]
    first_f = idx[min(verdict["first"], len(idx) - 1)]
    last_f = idx[min(verdict["last"], len(idx) - 1)]
    duration = max(1, last_f - first_f)
    if fv["kind"] == "pan":
        px = abs(fv["toX"] - fv["fromX"]) * ctx.info.width
        return base_event(ctx.sig, first_f, "pan", durationFrames=duration,
                          magnitude=round(px, 1), easing=verdict["easing"],
                          detail={"faceGlide": True, "fromX": fv["fromX"],
                                  "toX": fv["toX"],
                                  "direction": ("right" if fv["toX"]
                                                > fv["fromX"] else "left")})
    return base_event(ctx.sig, first_f, f"zoom-{fv['direction']}",
                      durationFrames=duration, magnitude=fv["magnitude"],
                      easing=verdict["easing"],
                      detail={"scaleSource": "faceW"})


def _chrome_event(ctx: ClassifyCtx, rw: RunWindow, cv: dict) -> dict:
    """One chrome-channel verdict → a schema event (window k → frame)."""
    frame = max(0, rw.start - rw.offset + cv["k"])
    kind = "panel" if cv["cov"] >= DEEP["panel_frac"] else "graphic"
    return base_event(ctx.sig, frame, f"{kind}-{cv['inout']}",
                      durationFrames=cv["frames"], bbox=cv["bbox"],
                      coverage=cv["cov"], magnitude=cv["cov"],
                      transition=cv["transition"], easing=cv["easing"])


def classify_run(ctx: ClassifyCtx, start: int, end: int,
                 scdet_frames: "tuple | list" = ()) -> list[dict]:
    """One sustained-motion span [start, end] → typed events (possibly several,
    one per co-occurring region/signal family).

    Face + chrome channels run FIRST: a rail push or takeover changes most
    of the frame AND ramps the luma, so a global fade verdict would swallow
    the compound move the channels can separate (the module rail-in failure).
    """
    rw = _decode_span(ctx, start, end)
    events = [e for e in (_face_event(ctx, fv)
                          for fv in face_run_events(ctx.sig, start, end))
              if e is not None]
    events += [_chrome_event(ctx, rw, cv) for cv in chrome_channel(rw)]
    if events:
        return events
    ff = try_flash_fade(ctx, rw)
    if ff is not None:
        return [ff]
    for probe in (try_zoom, try_pan, try_sweep):
        ev = probe(ctx, rw)
        if ev is not None:
            return [ev]
    region = changed_region(*rw.ends)
    if region is None or region[1] < DEEP["graphic_min_cov"]:
        return []
    if region[1] >= DEEP["global_frac"]:
        return [base_event(ctx.sig, start, "cut", durationFrames=end - start,
                           coverage=region[1],
                           magnitude=round(max(ctx.sig.d[start:end + 1]), 2),
                           transition={"class": "hard-cut", "direction": None,
                                       "frames": end - start})]
    return _localized_events(ctx, start, rw, duration=end - start)
