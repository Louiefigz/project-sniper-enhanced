#!/usr/bin/env python3
"""study_cuts — scene-cut detection + pacing statistics for the STUDY verb.

A reference short's *pacing* is the first thing the editor brain wants to learn:
how often it cuts, whether the cadence accelerates in the hook, and how long the
longest un-cut stretch runs. This module measures that deterministically with
ffmpeg's ``scdet`` scene-change detector (score 0-100 per candidate boundary;
the sibling stages already trust ffmpeg's own analysers) and turns the cut
timestamps into shot-length statistics.

``scdet`` is preferred over ``select='gt(scene,T)'`` because it emits a clean,
parseable ``lavfi.scd.score`` / ``lavfi.scd.time`` pair per detected boundary
(validated on real footage, 2026-07-05). Score is a percentage-like 0-100 value;
the default threshold ~10 catches hard cuts on produced shorts.

No pass/fail judgement here — raw measurement only, mirroring audit_probe.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# scdet stderr: "[scdet @ 0x..] lavfi.scd.score: 38.714, lavfi.scd.time: 8.9255"
_SCDET_RE = re.compile(
    r"lavfi\.scd\.score:\s*(-?\d+(?:\.\d+)?),\s*lavfi\.scd\.time:\s*(-?\d+(?:\.\d+)?)")

BUCKET_SECONDS = 10.0            # pacing curve resolution (cuts per 10s window)
DEFAULT_SCDET_THRESHOLD = 10.0   # scdet's own default; 0-100 scale


@dataclass
class Cut:
    """One detected scene boundary."""

    time: float          # seconds into the source
    score: float         # scdet score (0-100); higher = harder cut


@dataclass
class PacingStats:
    """Everything the brain needs to characterise a reference's cutting rhythm."""

    duration: float
    cut_count: int
    cuts_per_min: float
    shot_count: int
    shot_p25: float
    shot_p50: float
    shot_p75: float
    shot_p95: float
    longest_static_s: float          # longest un-cut stretch
    bucket_curve: list[dict]         # per-10s: {"start","end","cuts","cutsPerMin"}


def detect_cuts(video_path: str, threshold: float = DEFAULT_SCDET_THRESHOLD) -> list[Cut]:
    """Return scene cuts (time-ordered) via ffmpeg ``scdet``.

    ``threshold`` is scdet's 0-100 score gate; lower detects softer transitions.
    A boundary is emitted per frame whose change score clears the threshold.
    """
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", video_path,
         "-vf", f"scdet=threshold={threshold}", "-an", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    cuts: list[Cut] = []
    for match in _SCDET_RE.finditer(proc.stderr):
        cuts.append(Cut(time=round(float(match.group(2)), 3),
                        score=round(float(match.group(1)), 3)))
    cuts.sort(key=lambda c: c.time)
    return cuts


def _shot_lengths(cut_times: list[float], duration: float) -> list[float]:
    """Lengths of every shot: gaps between consecutive cut boundaries, plus the
    opening (0→first cut) and closing (last cut→end) shots."""
    if duration <= 0:
        return []
    marks = [0.0] + [t for t in cut_times if 0.0 < t < duration] + [duration]
    return [round(marks[i + 1] - marks[i], 3) for i in range(len(marks) - 1)
            if marks[i + 1] > marks[i]]


def _percentile(sorted_vals: list[float], pct: float) -> float:
    """Linear-interpolated percentile of an already-sorted list (0 if empty)."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return round(sorted_vals[0], 3)
    rank = (pct / 100.0) * (len(sorted_vals) - 1)
    low = int(rank)
    frac = rank - low
    if low + 1 >= len(sorted_vals):
        return round(sorted_vals[-1], 3)
    return round(sorted_vals[low] + frac * (sorted_vals[low + 1] - sorted_vals[low]), 3)


def _bucket_curve(cut_times: list[float], duration: float) -> list[dict]:
    """Cuts per ``BUCKET_SECONDS`` window across the runtime (the pacing curve)."""
    if duration <= 0:
        return []
    n_buckets = max(1, int((duration + BUCKET_SECONDS - 1e-6) // BUCKET_SECONDS))
    counts = [0] * n_buckets
    for t in cut_times:
        if 0.0 <= t < duration:
            counts[min(n_buckets - 1, int(t // BUCKET_SECONDS))] += 1
    curve: list[dict] = []
    for i, count in enumerate(counts):
        start = i * BUCKET_SECONDS
        end = min(duration, start + BUCKET_SECONDS)
        span_min = (end - start) / 60.0
        curve.append({
            "start": round(start, 1), "end": round(end, 1), "cuts": count,
            "cutsPerMin": round(count / span_min, 2) if span_min > 0 else 0.0,
        })
    return curve


def compute_pacing(cuts: list[Cut], duration: float) -> PacingStats:
    """Turn detected cuts + duration into shot-length + cadence statistics."""
    cut_times = [c.time for c in cuts]
    shots = _shot_lengths(cut_times, duration)
    ordered = sorted(shots)
    cuts_per_min = round(len(cut_times) / (duration / 60.0), 2) if duration > 0 else 0.0
    return PacingStats(
        duration=round(duration, 3),
        cut_count=len(cut_times),
        cuts_per_min=cuts_per_min,
        shot_count=len(shots),
        shot_p25=_percentile(ordered, 25),
        shot_p50=_percentile(ordered, 50),
        shot_p75=_percentile(ordered, 75),
        shot_p95=_percentile(ordered, 95),
        longest_static_s=round(max(shots), 3) if shots else round(duration, 3),
        bucket_curve=_bucket_curve(cut_times, duration),
    )
