#!/usr/bin/env python3
"""eye_trace — gaze-continuity placement bias + audit math (LIAM move 4).

EDITCRAFT_LESSONS.md §7.1 (EC2 R1 taught 9:26-9:57): at a hard cut or a
graphic insertion the incoming focal point should land near the outgoing
frame's gaze point; violations only as deliberate FLAGGED jolts.

MEASURED NULL (LIAM-4-MOVES move 4, 2026-07-11; n=24 large graphic
entrances 2D + n=299 small horizontal): face→graphic-landing correlation
rx=+0.05 / ry=−0.16, mean 2D distance 0.351 normalized screen units vs a
shuffled null of 0.348 (0% improvement) — the pros land graphics at
DESIGNED ANCHORS, not at the face. So this module is deliberately weak:

* ``region_bias`` is an ADDITIVE near-tie breaker on the free-space region
  score (never overrides emptiness/fit legality) — weight in
  ``MOTION["eye_trace"]["bias_weight"]``.
* ``evaluate_rows`` powers the Audit B ADVISORY WARN (never FAIL) when a
  graphic lands further than ``warn_dist_frac`` from the gaze point and
  the entry is not flagged as a deliberate jolt (``jolt_flag_key``).

GAZE SOURCE (previous-shot focal xy): the planner-known focal point wins —
``entry["gazeXY"]`` = normalized ``[x, y]`` (e.g. a cursor on screen-share
footage); else the ``faceBBoxNorm`` center (a talking head's outgoing gaze
anchor — the a-roll face persists across the graphic's entrance); else
None (no gaze known → bias and audit both skip, since gaze is advisory).

DISTANCE METRIC: Euclidean in normalized screen units (x/canvas_w,
y/canvas_h) — the SAME metric the measurement used (mean 0.351), so the
config threshold compares like-for-like. Max possible distance = √2.

Pure module: no cv2/ffmpeg — unit-tested in tests/test_eye_trace.py.
"""

from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from producer_config import MOTION  # noqa: E402

CFG = MOTION["eye_trace"]
_MAX_DIST = math.sqrt(2.0)          # corner-to-corner in normalized units


def _valid_norm_pair(raw: object) -> bool:
    """True for a 2-number normalized [x, y] pair inside [0, 1]."""
    return (isinstance(raw, (list, tuple)) and len(raw) == 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                    and 0.0 <= float(v) <= 1.0 for v in raw))


def gaze_xy(entry: dict) -> tuple[float, float] | None:
    """The previous-shot gaze point for one graphics entry, normalized (x, y).

    Precedence (the read path the config names): a planner-known
    ``gazeXY`` focal point wins; else the ``faceBBoxNorm`` center; else
    None (gaze unknown — advisory features disengage, nothing fails).
    A PRESENT-but-malformed ``gazeXY`` raises: the planner stated a focal
    point and got the shape wrong — never silently ignore it (house rule).
    """
    raw = entry.get("gazeXY")
    if raw is not None:
        if not _valid_norm_pair(raw):
            raise ValueError(
                f"gazeXY must be a 2-number normalized [x, y] in [0,1]; "
                f"got {raw!r}")
        return float(raw[0]), float(raw[1])
    bbox = entry.get("faceBBoxNorm")
    if (isinstance(bbox, (list, tuple)) and len(bbox) == 4
            and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                    and 0.0 <= float(v) <= 1.0 for v in bbox)):
        x, y, w, h = (float(v) for v in bbox)
        return x + w / 2.0, y + h / 2.0
    return None


def dist_frac(point_px: tuple, gaze: tuple, canvas: tuple) -> float:
    """Normalized 2D distance from a canvas-px point to the gaze point.

    ``point_px`` = (x, y) px; ``gaze`` = normalized (x, y); ``canvas`` =
    (w, h) px. Euclidean in normalized screen units — the measurement's
    metric (pro cloud mean 0.351, shuffled null 0.348).
    """
    w, h = canvas
    dx = point_px[0] / w - gaze[0]
    dy = point_px[1] / h - gaze[1]
    return math.hypot(dx, dy)


def bbox_dist_frac(bbox_px: tuple, gaze: tuple, canvas: tuple) -> float:
    """``dist_frac`` of a placed bbox's CENTER — the landing point audited."""
    x0, y0, x1, y1 = bbox_px
    return dist_frac(((x0 + x1) / 2.0, (y0 + y1) / 2.0), gaze, canvas)


def region_bias(center_px: tuple, gaze: tuple | None, canvas: tuple) -> float:
    """The ADDITIVE gaze-proximity term for one region's placement score.

    0 when no gaze is known. Otherwise ``bias_weight`` scaled by proximity
    (1 at the gaze point, 0 at the far corner) — a near-tie breaker on
    free-space scores (~0.1-0.5), never an override: legality (fit +
    ``prefer_emptiness``) is checked upstream and unchanged.
    """
    if gaze is None:
        return 0.0
    frac = dist_frac(center_px, gaze, canvas)
    return CFG["bias_weight"] * (1.0 - min(frac / _MAX_DIST, 1.0))


def placement_row(entry: dict, meta: dict, canvas: tuple) -> dict:
    """One ``graphics_placements.json`` sidecar row for a composited graphic.

    Fuses the entry's gaze read with the placement meta's landed bbox
    (v2/explicit paths record ``placedBBox``; the v1 fallback doesn't —
    the row then carries ``gazeDistFrac: None`` and the audit skips it).
    ``canvas`` = the DELIVERY (w, h) px the bbox is expressed on.
    """
    gaze = gaze_xy(entry)
    placed = meta.get("placedBBox")
    frac = (round(bbox_dist_frac(tuple(placed), gaze, canvas), 4)
            if gaze is not None and placed else None)
    return {"kind": entry.get("kind"),
            "anchor": entry.get("anchor", "free-band"),
            "outStart": float(entry["outStart"]),
            "outEnd": float(entry["outEnd"]),
            "region": meta.get("region"),
            "placedBBox": list(placed) if placed else None,
            "canvas": [int(canvas[0]), int(canvas[1])],
            "gaze": [round(g, 4) for g in gaze] if gaze else None,
            "gazeDistFrac": frac,
            "deliberateJolt": bool(entry.get(CFG["jolt_flag_key"], False))}


def evaluate_rows(rows: list) -> tuple[int, list[dict]]:
    """Audit the placements-sidecar rows → ``(checked, violations)``.

    Each row (written by graphics_stage) carries ``gazeDistFrac`` (None
    when no gaze was known / no landed bbox), ``deliberateJolt`` (the
    entry's ``jolt_flag_key`` flag) and identity fields. A row violates
    when its distance exceeds ``warn_dist_frac`` AND it is not a flagged
    deliberate jolt. Advisory by design (measured null): the caller maps
    violations to WARN, never FAIL. ``audit: "off"`` short-circuits.
    """
    if CFG.get("audit") == "off":
        return 0, []
    checked, violations = 0, []
    for row in rows:
        frac = row.get("gazeDistFrac")
        if frac is None:
            continue
        checked += 1
        if float(frac) <= CFG["warn_dist_frac"] or row.get("deliberateJolt"):
            continue
        violations.append(row)
    return checked, violations
