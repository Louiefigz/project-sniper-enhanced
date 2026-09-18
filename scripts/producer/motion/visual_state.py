#!/usr/bin/env python3
"""visual_state — per-zone talking-head / screen-share / mixed classifier.

The graphics-placement doctrine (docs/producer/PRODUCER_MOTION_GRAPHICS_PLAN.md §2.1)
says the footage's VISUAL STATE decides where a graphic may go, or whether it
goes at all: over a screen-share you never stack text (cut away instead); over a
talking head graphics live AROUND the face (never on it). This module supplies
that per-zone state so the lint can enforce it.

For each zone it samples a handful of frames from the (mezzanine) video at the
zone's OUTPUT time range and fuses two deterministic signals:

  * face presence + prominence — the bundled Haar cascade (reused from
    ``face_track``); a prominent, stable face ⇒ talking head. The median face
    box is returned NORMALISED as ``faceBBoxNorm`` for the face-exclusion lint.
  * screen-content spread — Canny edge density measured per grid cell. A
    screen-share lights up detail across MANY cells (UI chrome, dense text); a
    talking head concentrates detail on the face/hair only.

Deliberate limits (stated honestly): Haar is a frontal detector — a turned head
or a tiny corner-cam face is missed, and synthetic/test footage (bars, plates)
reads as busy detail. So thresholds are conservative and every zone carries a
``confidence``; the operator's editor notes can always override a zone's state.

Uses cv2 (run with the venv python). CLI:
    visual_state.py <video.mp4> <zones.json> [out.json]
``zones.json`` is a list of ``{"outStart","outEnd"}`` (or a plan/treatment-map
object carrying a ``treatmentMap``/``zones`` list). Prints the result array to
stdout, or writes it to ``out.json`` + prints an NDJSON status line.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
from dataclasses import dataclass, field
from typing import Optional

import cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motion.face_track import _load_cascade, _read_at, _sample_times  # noqa: E402
from producer_config import FACE_TRACK  # noqa: E402

# =========================================================================== #
# Tunable thresholds (this module's config; practitioner heuristics). Calibrated
# 2026-07-05 on the livestream mezzanine (screen-share) + testsrc2 synthetic
# footage. Screen-content numbers are edge-detail heuristics, not OCR.
# =========================================================================== #
VISUAL_STATE = {
    "samples_per_zone": 6,          # frames sampled evenly across each zone
    "edge_downscale_w": 720,        # analyse edges at this width (speed/stability)
    "canny_lo": 80,
    "canny_hi": 180,
    "grid_cols": 8,                 # detail-spread grid
    "grid_rows": 6,
    "cell_edge_frac": 0.045,        # a cell is "busy" above this edge fraction
    # Aggregate decision lines.
    "face_present_rate": 0.4,       # face in >= this fraction of samples ⇒ present
    "face_prominent_area": 0.03,    # median face box >= 3% of frame ⇒ prominent
    "screen_busy_frac": 0.35,       # >= this fraction of cells busy ⇒ screen content
}


def _resolve_cfg() -> dict:
    """Merge the Haar detection params from FACE_TRACK with local thresholds."""
    return {**FACE_TRACK, **VISUAL_STATE}


@dataclass
class ZoneContext:
    """Per-video detection context threaded through the zone analysis."""

    frame_size: tuple[int, int]
    cascade: "cv2.CascadeClassifier"
    cfg: dict


@dataclass
class ZoneSamples:
    """Raw per-sample measurements accumulated over one zone."""

    areas: list[float] = field(default_factory=list)   # face area / frame area
    boxes: list = field(default_factory=list)          # (x, y, w, h) face boxes
    busy: list[float] = field(default_factory=list)    # busy-cell fraction
    taken: int = 0                                      # frames actually read


# =========================================================================== #
# Per-frame measurement.
# =========================================================================== #
def _largest_face(frame, cascade: "cv2.CascadeClassifier", cfg: dict):
    """Bounding box (x, y, w, h) of the largest Haar face, or None.

    Same detector + params as ``face_track`` so a face this stage calls
    prominent is the same face the reframe/exclusion stages will act on.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    min_side = int(cfg["haar_min_size_frac"] * frame.shape[0])
    faces = cascade.detectMultiScale(
        gray, scaleFactor=cfg["haar_scale_factor"],
        minNeighbors=cfg["haar_min_neighbors"], minSize=(min_side, min_side))
    if len(faces) == 0:
        return None
    x, y, w, h = max(faces, key=lambda r: int(r[2]) * int(r[3]))
    return (int(x), int(y), int(w), int(h))


def _busy_cell_fraction(frame, cfg: dict) -> float:
    """Fraction of grid cells whose Canny-edge density is text/UI-like.

    Detail spread is the screen-share discriminator: a screen lights up many
    cells; a talking head only the few over the face/hair.
    """
    h, w = frame.shape[:2]
    target_w = cfg["edge_downscale_w"]
    scale = target_w / float(w) if w > target_w else 1.0
    small = frame
    if scale < 1.0:
        small = cv2.resize(frame, (int(w * scale), int(h * scale)))
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, cfg["canny_lo"], cfg["canny_hi"])
    cols, rows = cfg["grid_cols"], cfg["grid_rows"]
    gh, gw = edges.shape[0] // rows, edges.shape[1] // cols
    if gh == 0 or gw == 0:
        return 0.0
    busy = 0
    for r in range(rows):
        for c in range(cols):
            cell = edges[r * gh:(r + 1) * gh, c * gw:(c + 1) * gw]
            if not cell.size:
                continue
            if int((cell > 0).sum()) / cell.size >= cfg["cell_edge_frac"]:
                busy += 1
    return busy / float(rows * cols)


# =========================================================================== #
# Per-zone aggregation + classification.
# =========================================================================== #
def analyze_zone(cap: "cv2.VideoCapture", zone: dict, ctx: ZoneContext) -> dict:
    """Sample a zone, fuse face + screen signals, and classify its visual state."""
    frame_w, frame_h = ctx.frame_size
    samples = ZoneSamples()
    for t in _sample_times(float(zone["outStart"]), float(zone["outEnd"]),
                           ctx.cfg["samples_per_zone"]):
        frame = _read_at(cap, t)
        if frame is None:
            continue
        samples.taken += 1
        samples.busy.append(_busy_cell_fraction(frame, ctx.cfg))
        box = _largest_face(frame, ctx.cascade, ctx.cfg)
        if box is not None:
            samples.boxes.append(box)
            samples.areas.append((box[2] * box[3]) / float(frame_w * frame_h))
    return _summarize_zone(zone, ctx, samples)


def _summarize_zone(zone: dict, ctx: ZoneContext, s: ZoneSamples) -> dict:
    """Turn per-sample measurements into one classified zone entry."""
    face_rate = round(len(s.areas) / s.taken, 3) if s.taken else 0.0
    face_area = statistics.median(s.areas) if s.areas else 0.0
    busy_frac = statistics.median(s.busy) if s.busy else 0.0
    state, confidence = _classify(face_area, busy_frac, face_rate, ctx.cfg)
    return {
        "outStart": round(float(zone["outStart"]), 3),
        "outEnd": round(float(zone["outEnd"]), 3),
        "state": state,
        "confidence": confidence,
        "faceBBoxNorm": _median_bbox_norm(s.boxes, ctx.frame_size),
        "signals": {"faceRate": face_rate, "faceAreaFrac": round(face_area, 4),
                    "busyFrac": round(busy_frac, 3), "samples": s.taken},
    }


def _classify(face_area: float, busy_frac: float, face_rate: float,
              cfg: dict) -> tuple[str, str]:
    """Fuse the two signals into (state, confidence). See module docstring."""
    has_face = face_rate >= cfg["face_present_rate"]
    prominent = has_face and face_area >= cfg["face_prominent_area"]
    busy = busy_frac >= cfg["screen_busy_frac"]
    if busy and not has_face:
        conf = "high" if busy_frac >= 1.3 * cfg["screen_busy_frac"] else "medium"
        return "screen-share", conf
    if busy and has_face:
        return "mixed", "medium"
    if prominent and not busy:
        conf = "high" if face_area >= 2 * cfg["face_prominent_area"] else "medium"
        return "talking-head", conf
    if has_face:                       # small, stable face on a calm frame
        return "talking-head", "medium"
    return "talking-head", "low"       # no face + no screen detail: ambiguous


def _median_bbox_norm(boxes: list, frame_size: tuple[int, int]) -> Optional[list]:
    """Normalised [x, y, w, h] (0..1) median face box, or None when no face."""
    if not boxes:
        return None
    frame_w, frame_h = frame_size
    xs = statistics.median(b[0] for b in boxes) / frame_w
    ys = statistics.median(b[1] for b in boxes) / frame_h
    ws = statistics.median(b[2] for b in boxes) / frame_w
    hs = statistics.median(b[3] for b in boxes) / frame_h
    return [round(xs, 4), round(ys, 4), round(ws, 4), round(hs, 4)]


# =========================================================================== #
# Orchestration + IO.
# =========================================================================== #
def classify_zones(video_path: str, zones: list[dict]) -> list[dict]:
    """Classify the visual state of every zone of ``video_path``."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {video_path}")
    try:
        frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if frame_w <= 0 or frame_h <= 0:
            raise RuntimeError("video reports non-positive dimensions")
        ctx = ZoneContext((frame_w, frame_h), _load_cascade(), _resolve_cfg())
        return [analyze_zone(cap, z, ctx) for z in zones]
    finally:
        cap.release()


def load_zones(data: object) -> list[dict]:
    """Coerce a raw list / {'treatmentMap': ...} / {'zones': ...} to zones."""
    if isinstance(data, dict):
        data = data.get("treatmentMap") or data.get("zones") or data
    if not isinstance(data, list):
        raise ValueError("zones JSON must be a list, or carry treatmentMap/zones")
    zones = [z for z in data if isinstance(z, dict)
             and "outStart" in z and "outEnd" in z]
    if not zones:
        raise ValueError("no zones with outStart/outEnd found")
    return zones


def main() -> None:
    if len(sys.argv) not in (3, 4):
        print(json.dumps({"error": "Usage: visual_state.py <video.mp4> "
                                    "<zones.json> [out.json]"}))
        sys.exit(1)
    try:
        with open(sys.argv[2]) as handle:
            zones = load_zones(json.load(handle))
        result = classify_zones(sys.argv[1], zones)
        if len(sys.argv) == 4:
            with open(sys.argv[3], "w") as handle:
                json.dump(result, handle, indent=2)
            counts = {s: sum(1 for r in result if r["state"] == s)
                      for s in ("talking-head", "screen-share", "mixed")}
            print(json.dumps({"status": "done", "zones": len(result), **counts}))
        else:
            print(json.dumps(result, indent=2))
    except (OSError, json.JSONDecodeError, ValueError, RuntimeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
