#!/usr/bin/env python3
"""deep_events — P3: change-points across every P2 signal → unified events[].

Detection is three-tier:

* IMPULSES — 1-frame global d spikes standing clear of both neighbours
  (hard cuts, punch-in cuts, instant graphic lands, flash frames).
* RUNS — sustained spans of elevated d (zooms, pans, sweeps, fades,
  multi-frame flashes, animated graphic builds). One run may yield SEVERAL
  events (face glide + rail sweep + panel out are separate signals).
* POP SCAN — a region-diff pass over every frame catches the localized
  instant pops the global d-metric can't see (deep_pops).

Cut boundaries are anchored twice: d-spikes classify them, and any scdet cut
the classifiers missed is SYNTHESIZED loudly (the fingerprint's cut layer is
frame-exact; the event layer must never lose one). Same-family duplicates
from the overlapping tiers are merged keeping the richest verdict. Runs
nothing could name are COUNTED loudly (``unclassifiedRuns``).
"""

from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from study.deep_classify import ClassifyCtx, classify_impulse, classify_run  # noqa: E402
from study.deep_config import DEEP  # noqa: E402
from study.deep_pops import scan_pops  # noqa: E402
from study.deep_signals import SignalTrack, freeze_runs  # noqa: E402

SPIKE_RATIO = 2.5          # an impulse must stand this far above its neighbours
RUN_JOIN_GAP = 2           # runs separated by <= this many quiet frames merge
MERGE_NEAR_FRAMES = 6      # same-type events this close collapse into one
IN_FAMILY = ("graphic-in", "panel-in")
OUT_FAMILY = ("graphic-out", "panel-out")


def _rolling_baseline(values: list[float], window: int) -> np.ndarray:
    """Per-frame LOW-percentile of d (edge-clamped window) — the quiet
    baseline. A rolling MEDIAN rises inside a 20-30 frame motion and swallows
    the very run it should expose; the 20th percentile stays pinned to the
    quiet frames as long as >=20% of the window is quiet."""
    arr = np.asarray(values, dtype=np.float64)
    half = window // 2
    out = np.empty_like(arr)
    for i in range(arr.size):
        lo, hi = max(0, i - half), min(arr.size, i + half + 1)
        out[i] = np.percentile(arr[lo:hi], DEEP["baseline_pct"])
    return out


def _impulse_indices(sig: SignalTrack, baseline: np.ndarray) -> list[int]:
    """Frames whose d spikes clear of the baseline AND both neighbours."""
    d, hits = sig.d, []
    for i in range(1, sig.frames - 1):
        thr = max(DEEP["impulse_abs_min"], DEEP["impulse_rel"] * baseline[i])
        neighbour = max(d[i - 1], d[i + 1])
        if d[i] >= thr and d[i] >= SPIKE_RATIO * max(neighbour, 0.2):
            hits.append(i)
    return hits


def _extend(span: list[int], sig: SignalTrack, low: np.ndarray) -> list[int]:
    """Hysteresis: grow a span while d stays above the LOW threshold — an
    eased glide tapers below the entry threshold long before it ends, and
    the tail is exactly what separates power2/power3-out from linear."""
    s, e = span
    while s > 1 and sig.d[s - 1] >= low[s - 1]:
        s -= 1
    while e + 1 < sig.frames and sig.d[e + 1] >= low[e + 1]:
        e += 1
    return [s, e]


def _run_spans(sig: SignalTrack, baseline: np.ndarray,
               impulses: list[int]) -> list[tuple[int, int]]:
    """Maximal sustained-motion spans [start, end], impulses excluded."""
    skip = set(impulses)
    active = [i for i in range(1, sig.frames)
              if i not in skip and sig.d[i] >= max(
                  DEEP["run_abs_min"], DEEP["run_rel"] * baseline[i])]
    spans: list[list[int]] = []
    for i in active:
        if spans and i - spans[-1][1] <= RUN_JOIN_GAP + 1:
            spans[-1][1] = i
        else:
            spans.append([i, i])
    low = np.maximum(DEEP["run_abs_min"] * 0.4, 1.2 * baseline)
    extended = [_extend(sp, sig, low) for sp in spans
                if sp[1] - sp[0] + 1 >= DEEP["run_min_frames"]]
    merged: list[list[int]] = []
    for s, e in extended:
        if merged and s <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [(s, e) for s, e in merged]


def _merge_near(events: list[dict]) -> list[dict]:
    """Collapse same-type events within MERGE_NEAR_FRAMES (flash echoes,
    the impulse+run double-detection of one cut)."""
    merged: list[dict] = []
    for ev in sorted(events, key=lambda e: e["frame"]):
        prev = next((m for m in reversed(merged)
                     if m["type"] == ev["type"]
                     and ev["frame"] - m["frame"] <= MERGE_NEAR_FRAMES), None)
        if prev is not None and ev["type"] not in IN_FAMILY + OUT_FAMILY:
            prev["durationFrames"] = max(
                prev["durationFrames"],
                ev["frame"] - prev["frame"] + ev["durationFrames"])
            if not prev.get("detail") and ev.get("detail"):
                prev["detail"] = ev["detail"]
            continue
        merged.append(ev)
    return merged


def _iou(a: "list | None", b: "list | None") -> float:
    """IoU of two normalised bboxes (0 when either is missing)."""
    if a is None or b is None:
        return 0.0
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1 = min(a[0] + a[2], b[0] + b[2])
    y1 = min(a[1] + a[3], b[1] + b[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    inter = (x1 - x0) * (y1 - y0)
    return inter / (a[2] * a[3] + b[2] * b[3] - inter)


def _richness(ev: dict) -> tuple:
    """Dedup rank: transition length, duration, earlier start wins ties."""
    tr = ev.get("transition") or {}
    return (tr.get("frames") or 0, ev.get("durationFrames") or 0,
            -ev["frame"])


def _dedup_family(events: list[dict]) -> list[dict]:
    """Same-family in/out events close in time + space merge, richest kept."""
    kept: list[dict] = []
    for ev in sorted(events, key=lambda e: e["frame"]):
        fam = ("in" if ev["type"] in IN_FAMILY
               else "out" if ev["type"] in OUT_FAMILY else None)
        if fam is None:
            kept.append(ev)
            continue
        dup = next(
            (k for k in kept
             if k["type"] in (IN_FAMILY if fam == "in" else OUT_FAMILY)
             and abs(ev["frame"] - k["frame"]) <= DEEP["dedup_frames"]
             and _iou(ev.get("bbox"), k.get("bbox")) >= DEEP["dedup_iou"]),
            None)
        if dup is None:
            kept.append(ev)
        elif _richness(ev) > _richness(dup):
            kept[kept.index(dup)] = ev
    return kept


def _freeze_events(sig: SignalTrack) -> list[dict]:
    """YDIF==0 spans as freeze events."""
    return [{"t": run["t"], "frame": run["startFrame"], "type": "freeze",
             "durationFrames": run["frames"], "magnitude": run["frames"],
             "bbox": None, "coverage": None, "transition": None,
             "easing": None, "detail": {"durationS": run["durationS"]}}
            for run in freeze_runs(sig)]


def _force_scdet_cuts(ctx: ClassifyCtx, events: list[dict],
                      scdet_frames: list[int]) -> list[dict]:
    """Re-classify any scdet boundary the detectors never touched.

    An scdet hit near an already-classified boundary (cut OR graphics event)
    is left alone — the classifier saw it and ruled. Only boundaries with
    NOTHING nearby get a synthesized verdict (cut with evidence, localized
    graphics otherwise), so a lost cut is impossible but a graphics-clear is
    never force-promoted into a phantom cut."""
    forced = []
    for f in scdet_frames:
        if f >= ctx.sig.frames:
            continue
        near_cut = any(e["type"] == "cut"
                       and abs(f - e["frame"]) <= DEEP["scdet_force_frames"]
                       for e in events)
        near_any = any(e["type"] != "freeze"
                       and abs(f - e["frame"]) <= 2 for e in events)
        if near_cut or near_any:
            continue
        forced += classify_impulse(ctx, f, scdet_frames=[f])
    return forced


def _near_boundary(events: list[dict], start: int) -> bool:
    """A run starting at a just-emitted cut/flash is boundary settle."""
    return any(e["type"] in ("cut", "flash")
               and abs(e["frame"] - start) <= MERGE_NEAR_FRAMES
               for e in events)


def detect_events(ctx: ClassifyCtx,
                  scdet_cuts: "list[float] | None" = None) -> dict:
    """The full P3 pass: impulses + runs + pops + freezes → events[]."""
    sig = ctx.sig
    baseline = _rolling_baseline(sig.d, DEEP["baseline_window"])
    impulses = _impulse_indices(sig, baseline)
    spans = _run_spans(sig, baseline, impulses)
    scdet_frames = sorted(round(t * sig.fps) for t in (scdet_cuts or []))
    events: list[dict] = []
    for i in impulses:
        events += classify_impulse(ctx, i, scdet_frames)
    unclassified = 0
    for start, end in spans:
        got = classify_run(ctx, start, end, scdet_frames)
        if not got and not _near_boundary(events, start):
            unclassified += 1
        events += got
    events += _force_scdet_cuts(ctx, events, scdet_frames)
    events = _merge_near(events)
    events = _dedup_family(events + scan_pops(ctx.video, ctx.info, sig, events))
    events += _freeze_events(sig)
    events.sort(key=lambda e: (e["t"], e["type"]))
    for n, ev in enumerate(events, start=1):
        ev["id"] = f"ev-{n:03d}"
    return {"events": events, "unclassifiedRuns": unclassified}
