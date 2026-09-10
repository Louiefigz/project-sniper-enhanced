#!/usr/bin/env python3
"""audit_frames — visual-review frame extraction + the safe-zone pixel heuristic.

Audit B is half deterministic measurement and half *"let a human/Claude look at
it."* This module prepares that look: it samples the finished master at the
moments most worth eyeballing (cover, title-card holds, every graphic's phases,
caption beats, final frame) and writes JPGs to ``<out_dir>/audit_frames/``. It
also runs a cheap,
honest edge-density heuristic that flags burned-in text/graphics sitting in the
bottom platform-UI danger zone (below the safe box) — edge C7. See
docs/producer/PRODUCER_PLAN.md §5.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audit.audit_checks import CheckResult, FAIL, PASS, WARN  # noqa: E402
from audit.audit_probe import extract_frame  # noqa: E402
from audit.audit_frame_batch import extract_nearby_frames, review_batch_eligible  # noqa: E402
from audit.audit_safe_zone import scan_safe_zone  # noqa: E402
from stage_timing import stage_span  # noqa: E402

FRAME_END_PAD_S = 0.1
GRAPHIC_PHASE_PAD_S = 0.6
TIMESTAMP_PRECISION = 3


@dataclass
class FrameRef:
    """One extracted review frame: what it is, when, where on disk."""

    label: str          # short slug ("cover", "card0", "caption1", "final")
    kind: str           # "cover" | "titlecard" | "graphic" | "caption" | "final"
    timestamp: float    # output-time seconds
    path: str           # absolute path to the JPG (or "" if extraction failed)
    note: str = ""      # what a reviewer should eyeball here


def plan_frames(plan: dict, output_duration: float) -> list[FrameRef]:
    """Decide which output-time moments to sample (paths filled in on extract).

    Cover/hook at t=0.2; the midpoint of each title-card window; settled, middle,
    and exit phases of every graphic; three evenly spaced caption beats across
    the runtime; the final frame.
    """
    frames: list[FrameRef] = [
        FrameRef("cover", "cover", 0.2, "",
                 "Frame 1 is the thumbnail + loop start: settled (not mid-word)? "
                 "Hook card inside the safe box, centered ~x495?"),
    ]
    for i, card in enumerate(plan.get("titleCards") or []):
        mid = (float(card.get("outStart", 0.0)) + float(card.get("outEnd", 0.0))) / 2.0
        frames.append(FrameRef(
            f"card{i}", "titlecard", mid, "",
            "Title-card text fully inside the safe box, <=2 lines, legible, "
            "not overflowing the canvas?"))
    frames.extend(_cut_boundary_frames(plan, output_duration))
    for i, graphic in enumerate(plan.get("graphicsTrack") or []):
        frames.extend(_graphic_frames(i, graphic, output_duration))
    for i, punch in enumerate(plan.get("punchIns") or []):
        frames.extend(_motion_frames(i, punch, output_duration))
    for i, transition in enumerate(plan.get("transitions") or []):
        frames.extend(_transition_frames(i, transition, output_duration))
    for i, frac in enumerate((0.25, 0.5, 0.75)):
        frames.append(FrameRef(
            f"caption{i + 1}", "caption", round(output_duration * frac, 3), "",
            "Captions legible + fully on-canvas, in the lower band; subject "
            "framing sane (no chopped forehead / readable screen)?"))
    frames.append(FrameRef(
        "final", "final", max(0.0, output_duration - 0.15), "",
        "Tail frame clean? Loop-friendly back to the cover?"))
    return frames


def _graphic_frames(index: int, graphic: dict,
                    output_duration: float) -> list[FrameRef]:
    """Settled/middle/exit review frames for one graphic, safely clamped.

    Very short or entirely out-of-range windows can collapse phase timestamps;
    those duplicates are removed without dropping the event's sole sample.
    """
    start = float(graphic.get("outStart", 0.0))
    end = float(graphic.get("outEnd", start))
    refs = _window_phase_refs(f"graphic{index}", "graphic", start, end,
                              output_duration)
    for ref in refs:
        phase = ref.label.rsplit("_", 1)[-1]
        ref.note = (f"Graphic {index} {phase}: correct canvas coverage, "
                    "placement, copy, legibility, and compositing?")
    return refs


def _cut_boundary_frames(plan: dict,
                         output_duration: float) -> list[FrameRef]:
    """Before/seam/after evidence for every internal output cut."""
    refs: list[FrameRef] = []
    running = 0.0
    segments = plan.get("cutTrack") or []
    for index, segment in enumerate(segments[:-1]):
        speed = float(segment.get("speed", 1.0)) or 1.0
        running += (float(segment["end"]) - float(segment["start"])) / speed
        for phase, timestamp in (("before", running - 0.1),
                                 ("seam", running), ("after", running + 0.1)):
            refs.append(FrameRef(
                f"cut{index}_{phase}", "cut", _clamp_time(
                    timestamp, output_duration), "",
                f"Cut {index + 1} {phase}: intended continuity, no flash, "
                "duplicate frame, jump-back, or frozen outgoing/incoming shot?"))
    return refs


def _motion_frames(index: int, punch: dict,
                   output_duration: float) -> list[FrameRef]:
    """Attack/mid/release evidence for every authored footage motion."""
    start = float(punch.get("outStart", 0.0))
    end = float(punch.get("outEnd", start))
    refs = _window_phase_refs(f"motion{index}", "motion", start, end,
                              output_duration)
    for ref in refs:
        ref.note = (f"Motion {index} {ref.label.rsplit('_', 1)[-1]}: subject "
                    "framing, easing state, crop safety, and visual continuity?")
    return refs


def _window_phase_refs(prefix: str, kind: str, start: float, end: float,
                       output_duration: float) -> list[FrameRef]:
    """Deduped settled/mid/exit samples for any bounded visual event."""
    lower, upper = sorted((_clamp_time(start, output_duration),
                           _clamp_time(end, output_duration)))
    pad = min(GRAPHIC_PHASE_PAD_S, max(0.0, (upper - lower) / 4.0))
    phases = (("settled", lower + pad), ("mid", (lower + upper) / 2.0),
              ("exit", upper - pad))
    refs: list[FrameRef] = []
    seen: set[float] = set()
    for phase, timestamp in phases:
        timestamp = _clamp_time(timestamp, output_duration)
        if timestamp not in seen:
            seen.add(timestamp)
            refs.append(FrameRef(f"{prefix}_{phase}", kind, timestamp, ""))
    return refs


def _transition_frames(index: int, transition: dict,
                       output_duration: float) -> list[FrameRef]:
    """Before/seam/after evidence for every authored transition."""
    seam = float(transition.get("outTime", 0.0))
    refs: list[FrameRef] = []
    seen: set[float] = set()
    for phase, timestamp in (("before", seam - 0.1), ("seam", seam),
                             ("after", seam + 0.1)):
        timestamp = _clamp_time(timestamp, output_duration)
        if timestamp in seen:
            continue
        seen.add(timestamp)
        refs.append(FrameRef(
            f"transition{index}_{phase}", "transition", timestamp, "",
            f"Transition {index} {phase}: no flash, frozen layer, bad crop, "
            "or discontinuity?"))
    return refs


def _clamp_time(timestamp: float, output_duration: float) -> float:
    """Clamp a review timestamp to a reliably extractable output-time point."""
    upper = max(0.0, float(output_duration) - FRAME_END_PAD_S)
    return round(min(max(0.0, timestamp), upper), TIMESTAMP_PRECISION)


def extract_review_frames(final_path: str, out_dir: str,
                          frames: list[FrameRef], probe: dict | None = None) -> list[FrameRef]:
    """Extract every planned frame into ``<out_dir>/audit_frames/``.

    Returns the same refs with ``path`` populated (empty string on a failed
    extraction — reported, never silently dropped).
    """
    frames_dir = os.path.join(out_dir, "audit_frames")
    os.makedirs(frames_dir, exist_ok=True)
    requested = [(ref.timestamp, os.path.join(frames_dir, f"{ref.label}_t{ref.timestamp:07.3f}.jpg")) for ref in frames]
    eligible = review_batch_eligible(probe)
    with stage_span(out_dir, "audit_review_frame_extraction", {"evidenceImages": len(frames),
                    "phase": "nearby-batch" if eligible else "serial-unqualified"}):
        results = (extract_nearby_frames(final_path, requested, extract_frame) if eligible
                   else [extract_frame(final_path, timestamp, destination) for timestamp, destination in requested])
    return [FrameRef(ref.label, ref.kind, ref.timestamp, destination if ok else "", ref.note)
            for ref, (_, destination), ok in zip(frames, requested, results)]


def check_frame_extraction(frames: list[FrameRef]) -> CheckResult:
    """Fail closed unless every planned visual-review frame was extracted."""
    failed = [ref.label for ref in frames if not ref.path]
    if failed:
        return CheckResult(
            "review_frames_extracted", FAIL,
            f"{len(frames) - len(failed)}/{len(frames)} required frame(s)",
            "failed: " + ", ".join(failed))
    return CheckResult(
        "review_frames_extracted", PASS,
        f"{len(frames)}/{len(frames)} required frame(s)",
        "every planned visual-review frame extracted")
