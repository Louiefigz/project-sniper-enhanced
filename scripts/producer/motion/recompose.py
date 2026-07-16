#!/usr/bin/env python3
"""Face-anchored rail recompose with deterministic measured geometry.

Every registered free-band rail recenters the measured face in its remaining
clear region. The move becomes a synced ``role:"recompose"`` punch window:
minimal pan-enabling zoom, face-targeted center, and eased attack/release.
``faceBBoxNorm`` is mandatory and baseline framing is composed before solving;
missing geometry or a transform mismatch fails closed.

CLI:
    recompose.py <edit_plan.json> [--out out.json] [--face x,y,w,h]
stamps rail/panel kinds (longform) with a default ``recompose`` and rebuilds
the synced ``role:"recompose"`` punch windows in ``plan.punchIns``
(idempotent: existing recompose windows are replaced). NDJSON status lines.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from producer_config import MOTION  # noqa: E402

_CFG = MOTION["recompose"]
_EPS = 1e-6


def emit(**fields) -> None:
    """One JSON status object per line on stdout (NDJSON, like the siblings)."""
    print(json.dumps(fields), flush=True)


def clear_center(clear_x: object) -> float:
    """Midpoint of the clear (non-panel) region ``[x0, x1]`` — the pro lands
    the face there (remaining-space center) in every rail window."""
    if (not isinstance(clear_x, (list, tuple)) or len(clear_x) != 2
            or any(isinstance(v, bool) or not isinstance(v, (int, float))
                   for v in clear_x)):
        raise ValueError(f"recompose.clearX must be [x0, x1] (got {clear_x!r})")
    x0, x1 = float(clear_x[0]), float(clear_x[1])
    if not (0.0 <= x0 < x1 <= 1.0):
        raise ValueError(f"recompose.clearX [{x0},{x1}] must satisfy "
                         "0 <= x0 < x1 <= 1")
    return (x0 + x1) / 2.0


def solve_recompose(face_cx: float, target_x: float) -> tuple[float, float]:
    """(zoom, centerX) that land the face at ``target_x`` — the punch-window
    parameters for the glide.

    The crop feasibility bounds (crop stays inside the scaled frame at the
    hold) give ``z >= max(target/fx, (1-target)/(1-fx))``; the margin keeps
    the crop off the exact frame edge. A zoom past the punch band means the
    face is too far from the clear region to recompose subtly — fail loud,
    the framing (or the panel side) is the problem."""
    if not (0.0 + _EPS < face_cx < 1.0 - _EPS):
        raise ValueError(f"face centerX {face_cx} is at the frame edge — "
                         "cannot recompose")
    z_min = max(1.0, target_x / face_cx, (1.0 - target_x) / (1.0 - face_cx))
    zoom = max(_CFG["zoom_floor"], z_min * _CFG["zoom_margin"])
    if zoom > _CFG["zoom_cap"] + _EPS:
        raise ValueError(
            f"recompose needs zoom {zoom:.3f} to land face {face_cx:.3f} on "
            f"{target_x:.3f} — past the {_CFG['zoom_cap']} cap; the panel "
            "side/width vs the framing is wrong (fix upstream)")
    return round(zoom, 4), round(face_cx - (target_x - 0.5) / zoom, 4)


def solve_recompose_bounded(face_cx: float,
                            target_x: float) -> tuple[float, float]:
    """Solve exactly when possible, else use the closest tasteful crop.

    A jump cut can put the presenter a few percent farther left inside one
    continuing rail.  If exact centering would exceed the structural zoom cap,
    pin the crop at its legal edge and accept at most a small configured miss.
    A larger miss still fails closed so the planner must change the layout.
    """
    try:
        return solve_recompose(face_cx, target_x)
    except ValueError as original:
        zoom = float(_CFG["zoom_cap"])
        low = 1.0 - (1.0 - face_cx) * zoom
        high = face_cx * zoom
        landed = min(max(target_x, low), high)
        error = abs(landed - target_x)
        if error > float(_CFG["max_landing_error_frac"]) + _EPS:
            raise original
        offset = face_cx * zoom - landed
        center_x = (offset + 0.5) / zoom
        return round(zoom, 4), round(center_x, 4)


def solve_center_y(face_cy: float, zoom: float) -> float:
    """centerY that keeps the face's VERTICAL position as unchanged as the
    crop allows (the move is a horizontal pan, not a vertical drift). Ideal
    is ``fy - (fy - 0.5)/z``; the clamp keeps the crop inside the frame."""
    ideal = face_cy - (face_cy - 0.5) / zoom
    lo, hi = 0.5 / zoom, 1.0 - 0.5 / zoom
    return round(min(max(ideal, lo), hi), 4)


def face_out_x(face_cx: float, zoom: float, center_x: float) -> float:
    """Where the face lands on the OUTPUT frame at the hold — the pure mirror
    of punch_in's crop math (``fo = fx*z - clip(cx*z - 0.5, 0, z-1)``)."""
    off = min(max(center_x * zoom - 0.5, 0.0), zoom - 1.0)
    return face_cx * zoom - off


def _baseline_face(face: tuple[float, float], plan: dict) -> tuple[float, float]:
    """Measured face position after the in-house baseline transform."""
    look = plan.get("baselineLook") or {}
    zoom = float(look.get("zoom", 1.0))
    cx = float(look.get("centerX", 0.5))
    cy = float(look.get("centerY", 0.5))
    return face_out_x(face[0], zoom, cx), face_out_x(face[1], zoom, cy)


def _face_center(entry: dict, plan: dict,
                 face_bbox: object = None) -> tuple[float, float]:
    """Face center from the entry's bbox → the plan's → the explicit param.

    ``faceBBoxNorm`` is ``[x, y, w, h]`` in 0..1. No source = ValueError —
    a recompose without a measured face is a guess (no fallback matching)."""
    bbox = entry.get("faceBBoxNorm") or plan.get("faceBBoxNorm") or face_bbox
    if (not isinstance(bbox, (list, tuple)) or len(bbox) != 4
            or any(isinstance(v, bool) or not isinstance(v, (int, float))
                   for v in bbox)):
        raise ValueError(
            "recompose requires faceBBoxNorm [x,y,w,h] on the entry, the "
            f"plan, or --face (got {bbox!r}) — measure it (motion/face_track)")
    x, y, w, h = (float(v) for v in bbox)
    return x + w / 2.0, y + h / 2.0


def window_for_entry(entry: dict, plan: dict, out_dur: float,
                     face_bbox: object = None) -> dict:
    """The ``role:"recompose"`` punch window synced to one graphics entry.

    Starts ``leadS`` before the panel (the pro's glide starts ~3 frames before
    the rail is visible), eases in over ``moveS`` (overlapping the rail
    growth), holds through the window, and eases back out over the last
    ``moveS`` as the panel exits."""
    spec = entry.get("recompose")
    if not isinstance(spec, dict):
        raise ValueError(f"entry recompose must be an object (got {spec!r})")
    lead = float(spec.get("leadS", _CFG["lead_s"]))
    move = float(spec.get("moveS", _CFG["move_s"]))
    gs, ge = float(entry["outStart"]), float(entry["outEnd"])
    ws, we = max(0.0, gs - lead), min(ge, out_dur)
    if 2 * move > (we - ws) + _EPS:
        raise ValueError(f"recompose window [{ws:.2f},{we:.2f}] too short for "
                         f"an eased in+out of {move}s each")
    fx, fy = _baseline_face(_face_center(entry, plan, face_bbox), plan)
    zoom, cx = solve_recompose_bounded(fx, clear_center(spec["clearX"]))
    return {"outStart": round(ws, 3), "outEnd": round(we, 3), "zoom": zoom,
            "attackS": move, "releaseS": move, "centerX": cx,
            "centerY": solve_center_y(fy, zoom), "role": "recompose",
            "syncGraphic": round(gs, 3),
            "rationale": f"face-anchored recompose for {entry.get('kind')} "
                         f"at {gs:.2f}s (defect 1: re-center in clear region)"}


def _wants_recompose(entry: dict) -> bool:
    """True for a declared panel move or a registered occluding rail."""
    if entry.get("anchor", "free-band") == "own-screen":
        return False
    return (isinstance(entry.get("recompose"), dict)
            or requires_recompose(entry))


def requires_recompose(entry: dict) -> bool:
    """Whether a free-band entry occupies registered rail geometry."""
    kind = str(entry.get("kind", ""))
    return entry.get("anchor", "free-band") != "own-screen" \
        and kind in _CFG["geometry"]


def _default_clear_x(entry: dict) -> list[float]:
    """Clear region opposite the rail's registered settled geometry."""
    kind = str(entry.get("kind", ""))
    geometry = _CFG["geometry"].get(kind)
    if not isinstance(geometry, dict):
        raise ValueError(f"{kind!r} has no deterministic rail geometry")
    side_rule = str(geometry.get("side", ""))
    side = (str((entry.get("spec") or {}).get(
        "side", geometry.get("default_side", "left")))
        if side_rule == "spec" else side_rule)
    if side not in ("left", "right"):
        raise ValueError(f"{kind}: rail side {side!r} is not left/right")
    railw = float(geometry["width_frac"])
    if side == "right":
        return [0.0, round(1.0 - railw, 4)]
    return [round(railw, 4), 1.0]


def stamp_recompose(plan: dict) -> int:
    """Stamp a default ``recompose`` onto un-stamped rail/panel entries
    (longform auto-set, defect 1). Returns the number stamped; idempotent."""
    stamped = 0
    for entry in plan.get("graphicsTrack") or []:
        if not _wants_recompose(entry):
            continue
        if entry.get("recompose") is False and requires_recompose(entry):
            raise ValueError(f"{entry.get('kind')}: recompose:false cannot "
                             "disable measured rail clearance")
        if isinstance(entry.get("recompose"), dict):
            continue
        entry["recompose"] = {"clearX": _default_clear_x(entry)}
        stamped += 1
    return stamped


def window_issue(entry: dict, plan: dict, punch_ins: list[dict],
                 out_dur: float) -> str | None:
    """Return why a required rail lacks its exact measured transform."""
    if not _wants_recompose(entry):
        return None
    if entry.get("recompose") is False:
        return "recompose:false cannot disable measured rail clearance"
    if not isinstance(entry.get("recompose"), dict):
        return "missing auto-stamped recompose geometry"
    try:
        expected = window_for_entry(entry, plan, out_dur)
    except (KeyError, TypeError, ValueError) as exc:
        return str(exc)
    sync = float(expected["syncGraphic"])
    found = [row for row in punch_ins if row.get("role") == "recompose"
             and abs(float(row.get("syncGraphic", -1)) - sync) <= _EPS]
    if len(found) != 1:
        return f"needs exactly one synced measured transform; found {len(found)}"
    fields = ("outStart", "outEnd", "zoom", "attackS", "releaseS",
              "centerX", "centerY", "syncGraphic")
    drift = [key for key in fields
             if abs(float(found[0].get(key, -1))
                    - float(expected[key])) > 1e-3]
    return f"measured transform differs in {', '.join(drift)}" if drift else None


def _overlap_guard(windows: list[dict], others: list[dict]) -> None:
    """A recompose window colliding with another punch window is defect 4
    (footage pops while a rail is up) — fail loud, the brain resolves it."""
    for w in windows:
        for o in others:
            if (float(w["outStart"]) < float(o.get("outEnd", -1))
                    and float(o.get("outStart", -1)) < float(w["outEnd"])):
                raise ValueError(
                    f"recompose window [{w['outStart']},{w['outEnd']}] overlaps "
                    f"punch window [{o.get('outStart')},{o.get('outEnd')}] — "
                    "footage must not punch while a panel is up (defect 4); "
                    "drop or move that punch")


def apply_recompose(plan: dict, out_dur: float,
                    face_bbox: object = None) -> dict:
    """Stamp + rebuild every synced recompose punch window in ``plan.punchIns``.

    Longform-only (the move is longform grammar). Existing ``role:"recompose"``
    windows are replaced (idempotent). Returns a summary dict; mutates plan."""
    mode = (plan.get("target") or {}).get("mode")
    if mode != "longform":
        raise ValueError(f"recompose is longform grammar (target.mode={mode!r})")
    stamped = stamp_recompose(plan)
    windows = [window_for_entry(g, plan, out_dur, face_bbox)
               for g in plan.get("graphicsTrack") or [] if _wants_recompose(g)]
    before = plan.get("punchIns") or []
    kept = [w for w in before if w.get("role") != "recompose"]
    _overlap_guard(windows, kept)
    plan["punchIns"] = sorted(kept + windows,
                              key=lambda w: float(w.get("outStart", 0)))
    return {"stamped": stamped, "windows": len(windows),
            "replaced": len(before) - len(kept)}


def measure_face_bbox(video: str, out_dur: float) -> list | None:
    """A single global median face box over the whole take, via motion/visual_state
    (the SAME detector the graphics planner reads). Returns ``faceBBoxNorm``
    ``[x, y, w, h]`` in 0..1, or ``None`` when no face is measurable. May raise on
    a missing detector (no cv2) or a probe failure — a caller that wants to fail
    closed catches it and lets the downstream ``apply_recompose`` refuse rather
    than fabricate geometry."""
    from motion.visual_state import classify_zones
    zones = classify_zones(video, [{"outStart": 0.0, "outEnd": float(out_dur)}])
    return zones[0].get("faceBBoxNorm") if zones else None


def stamp_entry_face_bboxes(plan: dict, video: str) -> int:
    """Measure every rail in its own output window and stamp its face box.

    A global take-wide median is not precise enough across jump cuts: the face
    can move several percent of frame width while the authored clear-region
    target stays fixed.  Re-measuring the exact rail windows makes the solver's
    input match the pixels that will actually sit under each panel.
    """
    rails = [row for row in plan.get("graphicsTrack") or []
             if isinstance(row, dict) and requires_recompose(row)]
    if not rails:
        return 0
    from motion.visual_state import classify_zones
    zones = [{"outStart": float(row["outStart"]),
              "outEnd": float(row["outEnd"])} for row in rails]
    measured = classify_zones(video, zones)
    if len(measured) != len(rails):
        raise ValueError("entry face measurement did not return every rail window")
    for index, (entry, zone) in enumerate(zip(rails, measured)):
        bbox = zone.get("faceBBoxNorm")
        if not isinstance(bbox, list) or len(bbox) != 4:
            raise ValueError(f"rail window {index} has no measurable faceBBoxNorm")
        entry["faceBBoxNorm"] = bbox
        entry["faceBBoxSource"] = "measured-entry-window"
    return len(rails)


def stamp_face_bbox(plan: dict, video: str, out_dur: float) -> list | None:
    """When a longform plan carries a rail that REQUIRES recompose but no
    ``faceBBoxNorm``, MEASURE one from ``video`` and stamp it plan-wide so the
    gate, the render, and the Palmier checkpoint all recenter instead of aborting
    on an un-measured plan. Idempotent: a no-op when a face box is already present
    (plan or every required rail) or no rail needs recompose. Returns the bbox in
    play, else ``None`` (no rail needs it, or the face was unmeasurable — the
    downstream ``apply_recompose`` then fails closed, never fabricates)."""
    existing = plan.get("faceBBoxNorm")
    if existing:
        return existing
    rails = [row for row in plan.get("graphicsTrack") or []
             if isinstance(row, dict) and requires_recompose(row)]
    if not rails or all(row.get("faceBBoxNorm") for row in rails):
        return None
    try:
        bbox = measure_face_bbox(video, out_dur)
    except Exception:  # noqa: BLE001 — missing cv2 / probe failure: fail closed downstream
        return None
    if bbox:
        plan["faceBBoxNorm"] = bbox
    return bbox


def _parse_face(raw: str | None) -> list[float] | None:
    if raw is None:
        return None
    parts = [float(p) for p in raw.split(",")]
    if len(parts) != 4:
        raise ValueError("--face must be x,y,w,h (normalized bbox)")
    return parts


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Face-anchored recompose: stamp rail/panel entries and "
                    "emit synced role:'recompose' punch windows (defect 1)")
    ap.add_argument("plan")
    ap.add_argument("--out", help="output path (default: in place)")
    ap.add_argument("--face", help="faceBBoxNorm x,y,w,h when the plan/"
                                   "entries carry none")
    ap.add_argument("--video", help="source MP4 to MEASURE every rail's exact "
                                    "faceBBoxNorm window when --face is not given "
                                    "(the pre-gate authoring step the brain runs)")
    args = ap.parse_args()
    try:
        with open(args.plan) as f:
            plan = json.load(f)
        out_dur = sum((float(r["end"]) - float(r["start"]))
                      / (float(r.get("speed", 1.0)) or 1.0)
                      for r in plan.get("cutTrack") or [])
        face = _parse_face(args.face)
        if face is None and args.video:
            measured = stamp_entry_face_bboxes(plan, args.video)
            emit(stage="recompose", status="faces_measured",
                 railWindows=measured, source="measured-entry-window")
        summary = apply_recompose(plan, out_dur, face)
        dst = args.out or args.plan
        with open(dst, "w") as f:
            json.dump(plan, f, indent=2)
        emit(stage="recompose", status="done", out=dst, **summary)
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        emit(error=str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
