#!/usr/bin/env python3
"""zoom_detect — turn cuts + a whole-frame scale signal into ZOOM EVENTS (pure).

Two zoom techniques a professional talking-head edit uses, and how each is
measured here (magnitudes come from ``zoom_scale``'s ORB similarity scale, which
has a ~0.1% noise floor on this locked camera — face-area was too jittery):

  * PUNCH-IN CUT — a hard cut to a tighter/wider framing of the SAME shot. It is
    a STEP in whole-frame scale ACROSS a cut whose backgrounds still MATCH
    (ORB locks on → high inliers). A plain jump cut keeps the framing → scale
    ≈ 1.0 → no event. A cut to different content → ORB can't match → not a
    punch (it is a cutaway, tracked separately).
  * ANIMATED RAMP — a keyframed push-in / pull-out WITHIN one continuous shot:
    a scale change from the shot's first settled frame to its last, no cut
    between. A mid-shot probe confirms it ramped gradually (not a hidden cut).

No OpenCV here — the frame math is injected as ``scale_*`` callbacks so this
stays unit-testable and the thresholds (set from the RAW baseline) are
auditable. Face-area (from ``study_zoom_faces``) is used only to CLASSIFY each
shot (talking-head vs cutaway) and is recorded on each event as corroboration.
See docs/studies/LONGFORM_VISUAL_STUDY.md.
"""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass, field
from typing import Callable

# Scale thresholds are LINEAR zoom fractions (|scale-1|). The RAW locked camera
# reads |scale-1| < 0.002 with no zoom, so these sit far above the noise floor.
DEFAULT_CFG = {
    "smooth_window": 3,          # rolling-median window (samples) for face-area
    "edge_guard_s": 0.25,        # seconds trimmed at each shot edge (cut smear)
    "min_talking_rate": 0.6,     # face-present rate ⇒ talking-head shot
    "cutaway_rate": 0.35,        # face-present rate below ⇒ cutaway / b-roll shot
    "min_inliers": 25,           # ORB inliers below this ⇒ scale untrusted
    "punch_scale_min": 0.03,     # |scale-1| across a matched cut ⇒ punch-in cut
    "ramp_scale_min": 0.02,      # |scale-1| within a shot ⇒ animated ramp
    "ramp_min_dur": 1.2,         # a shot must be this long to test for a ramp
    "ramp_edge_samples": 3,      # face-area samples averaged at each shot end
    "ramp_step_frac": 0.55,      # >= this of the change in one segment ⇒ a hidden
                                 # punch, not a gradual ramp (scdet under-detects
                                 # punches on a matched background)
    "dedupe_window_s": 0.5,      # merge punch events closer than this (scdet emits
                                 # boundaries a few frames apart)
}

# A scale probe: returns (scale, inliers, ok). scale>1 push-in, <1 pull-out.
ScaleProbe = Callable[[float, float], "tuple[float, int, bool]"]


@dataclass
class ShotScan:
    """Trajectory scan of one shot: cumulative scale + how concentrated it is."""

    scale: float             # cumulative first→last scale (product of segments)
    inliers: int             # min inliers across the trusted segments
    ok: bool
    step_frac: float         # share of the total change in the single biggest segment
    step_t: float            # time of that dominant segment (a hidden punch's cut)
    step_scale: float        # scale of that dominant segment alone


# A shot-trajectory probe: Shot → ShotScan.
RampProbe = Callable[["Shot"], ShotScan]


@dataclass
class Shot:
    """One inter-cut span with its face-track summary."""

    index: int
    start: float
    end: float
    duration: float
    kind: str                    # talking-head | cutaway | sparse
    face_rate: float
    n_present: int
    area_start: float            # smoothed face area, first edge (corroboration)
    area_end: float
    area_med: float


@dataclass
class ZoomEvent:
    """A detected framing change (punch-in cut or animated ramp)."""

    t: float
    kind: str                    # punch_in_cut | ramp
    direction: str               # in | out
    scale: float                 # linear zoom factor (>1 in, <1 out)
    scale_pct: float             # (scale-1)*100 — the number an editor dials
    ramp_dur: float | None       # seconds (None for a cut)
    ramp_speed_pct_s: float | None   # ramp %/second (None for a cut)
    inliers: int
    shot_index: int
    area_from: float = 0.0       # face-area corroboration
    area_to: float = 0.0
    said: str = field(default="")    # transcript, filled by the orchestrator
    said_t: float = field(default=0.0)


def rolling_median(values: list[float], window: int) -> list[float]:
    """Centered rolling median; short/edge windows shrink to what's available."""
    if window <= 1 or len(values) <= 2:
        return list(values)
    half = window // 2
    return [statistics.median(values[max(0, i - half):min(len(values), i + half + 1)])
            for i in range(len(values))]


def _shot_spans(cut_times: list[float], duration: float) -> list[tuple[float, float]]:
    """[(start,end)] shots: 0→first cut, between cuts, last cut→end."""
    marks = [0.0] + [t for t in sorted(cut_times) if 0.0 < t < duration] + [duration]
    return [(marks[i], marks[i + 1]) for i in range(len(marks) - 1)
            if marks[i + 1] - marks[i] > 1e-3]


def _rows_in(samples: list, start: float, end: float) -> list:
    """Face samples with timestamp inside [start, end)."""
    return [s for s in samples if start <= s["t"] < end]


def build_shots(samples: list, cut_times: list[float], duration: float,
                cfg: dict) -> list[Shot]:
    """Summarise each inter-cut shot's face track (area at each edge + kind)."""
    guard = cfg["edge_guard_s"]
    shots: list[Shot] = []
    for idx, (start, end) in enumerate(_shot_spans(cut_times, duration)):
        rows = _rows_in(samples, start + guard, end - guard) or _rows_in(samples, start, end)
        present = [r for r in rows if r["present"]]
        rate = round(len(present) / len(rows), 3) if rows else 0.0
        areas = rolling_median([r["area"] for r in present], cfg["smooth_window"])
        k = cfg["ramp_edge_samples"]
        a_start = round(statistics.median(areas[:k]), 5) if areas else 0.0
        a_end = round(statistics.median(areas[-k:]), 5) if areas else 0.0
        a_med = round(statistics.median(areas), 5) if areas else 0.0
        kind = ("talking-head" if rate >= cfg["min_talking_rate"]
                else "cutaway" if rate <= cfg["cutaway_rate"] else "sparse")
        shots.append(Shot(idx, round(start, 3), round(end, 3), round(end - start, 3),
                          kind, rate, len(present), a_start, a_end, a_med))
    return shots


def detect_punch_cuts(shots: list[Shot], across: ScaleProbe, cfg: dict) -> list[ZoomEvent]:
    """Punch-in / pull-out CUTS: a matched-background scale step across a cut."""
    events: list[ZoomEvent] = []
    ordered = sorted(shots, key=lambda s: s.start)
    for left, right in zip(ordered, ordered[1:]):
        if left.kind == "cutaway" or right.kind == "cutaway":
            continue                       # a cutaway boundary is not a punch
        scale, inliers, ok = across(left.end, right.start)
        if not ok or inliers < cfg["min_inliers"] or abs(scale - 1.0) < cfg["punch_scale_min"]:
            continue
        events.append(ZoomEvent(
            t=round(right.start, 3), kind="punch_in_cut",
            direction="in" if scale > 1 else "out", scale=round(scale, 4),
            scale_pct=round((scale - 1) * 100, 1), ramp_dur=None,
            ramp_speed_pct_s=None, inliers=inliers, shot_index=right.index,
            area_from=left.area_end, area_to=right.area_start))
    return events


def detect_ramps(shots: list[Shot], scan: RampProbe, cfg: dict) -> list[ZoomEvent]:
    """Framing change inside one continuous talking-head shot.

    A gradual, distributed change is an ANIMATED RAMP. A change concentrated in
    one segment is a PUNCH-IN CUT scdet under-detected (a hard punch on a matched
    background scores low), reported at the segment where it happens.
    """
    events: list[ZoomEvent] = []
    for shot in shots:
        if shot.kind != "talking-head" or shot.duration < cfg["ramp_min_dur"]:
            continue
        obs = scan(shot)
        if not obs.ok or obs.inliers < cfg["min_inliers"]:
            continue
        if obs.step_frac >= cfg["ramp_step_frac"]:
            events.append(_hidden_punch(shot, obs, cfg))
        elif abs(obs.scale - 1.0) >= cfg["ramp_scale_min"]:
            events.append(_ramp_event(shot, obs, cfg))
    return [e for e in events if e is not None]


def _ramp_event(shot: Shot, obs: ShotScan, cfg: dict) -> ZoomEvent:
    """A gradual animated push/pull over the whole shot."""
    span = round(shot.duration - 2 * cfg["edge_guard_s"], 3)
    return ZoomEvent(
        t=round(shot.start, 3), kind="ramp",
        direction="in" if obs.scale > 1 else "out", scale=round(obs.scale, 4),
        scale_pct=round((obs.scale - 1) * 100, 1), ramp_dur=span,
        ramp_speed_pct_s=round((obs.scale - 1) * 100 / span, 2) if span else None,
        inliers=obs.inliers, shot_index=shot.index,
        area_from=shot.area_start, area_to=shot.area_end)


def _hidden_punch(shot: Shot, obs: ShotScan, cfg: dict) -> "ZoomEvent | None":
    """A hard punch scdet missed inside the shot (change in one segment)."""
    if abs(obs.step_scale - 1.0) < cfg["punch_scale_min"]:
        return None
    return ZoomEvent(
        t=round(obs.step_t, 3), kind="punch_in_cut",
        direction="in" if obs.step_scale > 1 else "out", scale=round(obs.step_scale, 4),
        scale_pct=round((obs.step_scale - 1) * 100, 1), ramp_dur=None,
        ramp_speed_pct_s=None, inliers=obs.inliers, shot_index=shot.index,
        area_from=shot.area_start, area_to=shot.area_end)


def dedupe_events(events: list[ZoomEvent], window_s: float) -> list[ZoomEvent]:
    """Collapse same-kind, same-direction events within ``window_s`` (keep max)."""
    events = sorted(events, key=lambda e: e.t)
    out: list[ZoomEvent] = []
    for ev in events:
        prev = out[-1] if out else None
        same = (prev and prev.kind == ev.kind and prev.direction == ev.direction
                and ev.t - prev.t <= window_s)
        if same and abs(ev.scale_pct) > abs(prev.scale_pct):
            out[-1] = ev
        elif not same:
            out.append(ev)
    return out


def cutaway_segments(shots: list[Shot]) -> list[dict]:
    """Merge consecutive non-talking-head shots into cutaway/b-roll segments."""
    segs: list[dict] = []
    run: list[Shot] = []

    def flush() -> None:
        if run:
            segs.append({"start": run[0].start, "end": run[-1].end,
                         "duration": round(run[-1].end - run[0].start, 3),
                         "shots": len(run),
                         "kinds": sorted({s.kind for s in run})})
    for shot in sorted(shots, key=lambda s: s.start):
        if shot.kind == "talking-head":
            flush()
            run = []
        else:
            run.append(shot)
    flush()
    return segs


def events_to_dicts(events: list[ZoomEvent]) -> list[dict]:
    """JSON-ready event dicts (dataclass → dict)."""
    return [asdict(e) for e in events]
