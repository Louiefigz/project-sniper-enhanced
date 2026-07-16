#!/usr/bin/env python3
"""plan_lint_smooth — SMOOTH LONGFORM ENFORCEMENT (defect report 2026-07-10).

Longform grammar is eased ramps and glides everywhere; 0-frame footage pops
are SHORTS grammar. Measured: ours had 11 bare single-frame footage pops in
81.4s (8.1/min) + hard punch-cuts DURING rail windows; the reference has ZERO
in 187s — every footage move IS an eased panel entrance/exit glide, and hard
steps live only on cut seams. Called from ``plan_lint_motion.check_motion``
(same Report accumulator; split out for the 300-line logic budget). Rules:

* POP BOUNDARIES — every punchIns window's boundary scale step (computed from
  punch_in's own pure mirrors, so lint and renderer can't drift) above
  ``scale_jump_tol`` must land ON a cut seam (a step reads intentional AT a
  cut, G6). Off-seam = ERROR.
* EASED FLOORS — a longform push must ease in over >= ``min_ease_s``; a
  declared release shorter than the floor is a flick, not a glide.
* UNDER-PANEL GUARD (defect 4) — a discontinuous footage step while a
  NON-own-screen panel is on screen = ERROR even on-seam (the face jumps
  against a fixed graphic); on-seam steps within ``graphic_guard_s`` of a
  panel edge draw a WARN (double event).
* RAIL RECOMPOSE (defect 1) — a rail-kind window with no synced
  ``role:"recompose"`` punch window leaves the subject off-center under the
  panel: WARN naming motion/recompose.py (the planner stamps it).
* LAYOUT DISCIPLINE (defect 7) — more than ``max_layout_families`` canonical
  layout families in one longform reads as N one-off graphics: WARN.
* FLASH TRANSITIONS (defect 8) — flash/leak seam covers are shorts grammar;
  the reference longform uses zero in 187s: WARN per plan.
* GAP-FILLER ZOOM PAIRS (LL-007, operator review v2 showpiece) — a punch-in
  that releases back to wide within ``gap_pair_max_s`` with NO graphic
  window overlapping and NO emphasis trigger/evidence annotation exists only
  to keep the screen alive: WARN (zooms mark emphasis beats or serve
  recompose moves — extend a panel / add a graphic instead, LESSON-007).
"""

from __future__ import annotations

from typing import Any

from graphics.exit_on_cut import seams_from_plan
from motion import recompose
from motion.punch_in import (PunchWindow, parse_windows, push_scale_at,
                             ramp_scale_at)
from producer_config import MOTION

_SMOOTH = MOTION["longform_smooth"]
_FAMILIES = MOTION["layout_families"]
_EPS = 1e-3


def check_smooth(plan: dict, out_dur: float, mode: str, rep: Any) -> None:
    """All smooth-longform checks (called from plan_lint_motion.check_motion)."""
    if mode != "longform":
        return
    graphics = plan.get("graphicsTrack") or []
    _check_recompose_fields(graphics, rep)
    _check_pop_boundaries(plan, out_dur, graphics, rep)
    _check_rail_recompose(plan, graphics, out_dur, rep)
    _check_layout_families(graphics, rep)
    _warn_flash_transitions(plan, rep)
    _warn_gap_filler_zooms(plan, graphics, rep)


# --------------------------------------------------------------------------- #
# Pop boundaries — no discontinuous footage scale off a cut seam.
# --------------------------------------------------------------------------- #
def _edge_scales(w: PunchWindow) -> tuple[float, float]:
    """The scale the window renders at its first/last instant — punch_in's own
    pure mirrors, so a change to the render math changes this lint with it."""
    if w.is_ramp:
        return ramp_scale_at(w, w.out_start), ramp_scale_at(w, w.out_end)
    if w.is_push:
        return push_scale_at(w, w.out_start), push_scale_at(w, w.out_end)
    return w.zoom, w.zoom          # static punch / bracket hold: hard edges


def _boundary_jumps(windows: list[PunchWindow]) -> list[tuple[float, float]]:
    """(t, |Δscale|) at every window boundary vs its neighbor or the wide
    baseline (1.0). Contiguous windows are compared against each other once."""
    jumps: list[tuple[float, float]] = []
    edges = [(w, *_edge_scales(w)) for w in windows]
    for i, (w, s_in, e_in) in enumerate(edges):
        left = 1.0
        if i > 0 and abs(w.out_start - edges[i - 1][0].out_end) <= _EPS:
            left = edges[i - 1][2]
        jumps.append((w.out_start, abs(s_in - left)))
        right = 1.0
        if i + 1 < len(edges) \
                and abs(edges[i + 1][0].out_start - w.out_end) <= _EPS:
            continue               # the next window's start event owns the seam
        jumps.append((w.out_end, abs(e_in - right)))
    return jumps


def _on_seam(t: float, seams: list[float]) -> bool:
    return any(abs(t - s) <= _SMOOTH["seam_tol_s"] for s in seams)


def _panel_windows(graphics: list[dict]) -> list[tuple[float, float]]:
    """Windows where footage is VISIBLE beside a live panel (non-own-screen)."""
    return [(float(g.get("outStart", -1)), float(g.get("outEnd", -1)))
            for g in graphics if g.get("anchor", "free-band") != "own-screen"]


def _check_pop_boundaries(plan: dict, out_dur: float, graphics: list[dict],
                          rep: Any) -> None:
    """Discontinuous footage-scale steps must land on cut seams — and never
    under a live panel. Eased floors for pushes ride along."""
    raw = plan.get("punchIns") or []
    if not raw:
        return
    try:
        windows = parse_windows(raw)
    except (ValueError, KeyError, TypeError):
        return                     # malformed windows are check_punch_ins' job
    _check_ease_floors(windows, rep)
    seams = seams_from_plan(plan) if plan.get("cutTrack") else []
    seams = [0.0] + seams + [out_dur]
    panels = _panel_windows(graphics)
    edges = [e for g in graphics
             for e in (float(g.get("outStart", -1)), float(g.get("outEnd", -1)))]
    for t, jump in _boundary_jumps(windows):
        if jump <= _SMOOTH["scale_jump_tol"]:
            continue
        _judge_jump((t, jump), seams, (panels, edges), rep)


def _judge_jump(event: tuple[float, float], seams: list[float],
                graphics: tuple[list, list], rep: Any) -> None:
    """One discontinuous boundary: off-seam = ERROR; on-seam under a live
    panel = ERROR (defect 4); on-seam near a panel edge = WARN."""
    t, jump = event
    panels, edges = graphics
    if not _on_seam(t, seams):
        rep.error(f"punchIns: 0-frame footage step (Δscale {jump:.2f}) at "
                  f"{t:.2f}s is off every cut seam — pops are shorts grammar; "
                  f"ease it (attackS/releaseS >= {_SMOOTH['min_ease_s']}s) or "
                  "land it on a cut (longform smooth grammar)")
        return
    if any(s + _EPS < t < e - _EPS for s, e in panels):
        rep.error(f"punchIns: footage pops at {t:.2f}s while a panel is on "
                  "screen — the face jumps against a fixed graphic (defect "
                  "4); while a panel is up, footage moves must be eased ramps "
                  "only (or move WITH the panel)")
        return
    if any(abs(t - e) <= _SMOOTH["graphic_guard_s"] for e in edges):
        rep.warn(f"punchIns: hard step at {t:.2f}s lands within "
                 f"{_SMOOTH['graphic_guard_s']}s of a graphic entrance/exit — "
                 "two visual events stack; prefer one overlapping eased move")


def _check_ease_floors(windows: list[PunchWindow], rep: Any) -> None:
    """Longform pushes ease over >= min_ease_s; a shorter declared edge is a
    flick (the defect's 'eased punches are NOT eased at onset')."""
    floor = _SMOOTH["min_ease_s"]
    for w in windows:
        if not w.is_push:
            continue
        if w.attack_s < floor - _EPS:
            rep.error(f"punchIns push at {w.out_start:.2f}s: attackS "
                      f"{w.attack_s:g}s under the longform ease floor "
                      f"({floor}s) — use a static punch ON a cut for a hard "
                      "step")
        if 0.0 < w.release_s < floor - _EPS:
            rep.error(f"punchIns push at {w.out_start:.2f}s: releaseS "
                      f"{w.release_s:g}s under the longform ease floor "
                      f"({floor}s)")


# --------------------------------------------------------------------------- #
# Rail recompose (defect 1) + recompose field shape.
# --------------------------------------------------------------------------- #
def _check_recompose_fields(graphics: list[dict], rep: Any) -> None:
    """``recompose`` on a graphics entry: object with a valid clearX (or
    ``false`` to opt out); never on own-screen (footage fully covered)."""
    for i, g in enumerate(graphics):
        spec = g.get("recompose")
        if spec is None or spec is False:
            continue
        tag = f"graphicsTrack[{i}]"
        if g.get("anchor", "free-band") == "own-screen":
            rep.error(f"{tag}: recompose on an own-screen takeover — the "
                      "footage is covered, there is nothing to re-center")
            continue
        if not isinstance(spec, dict):
            rep.error(f"{tag}: recompose must be an object "
                      f"{{clearX[, leadS, moveS]}} or false (got {spec!r})")
            continue
        _check_recompose_numbers(tag, spec, rep)


def _check_recompose_numbers(tag: str, spec: dict, rep: Any) -> None:
    """clearX bounds + leadS/moveS bands for one recompose declaration."""
    cx = spec.get("clearX")
    if (not isinstance(cx, (list, tuple)) or len(cx) != 2
            or any(isinstance(v, bool) or not isinstance(v, (int, float))
                   for v in cx)
            or not (0.0 <= float(cx[0]) < float(cx[1]) <= 1.0)):
        rep.error(f"{tag}: recompose.clearX must be [x0, x1] with "
                  f"0 <= x0 < x1 <= 1 (got {cx!r})")
    lead = spec.get("leadS")
    if lead is not None and (isinstance(lead, bool)
                             or not isinstance(lead, (int, float))
                             or not (0.0 <= float(lead) <= 0.5)):
        rep.error(f"{tag}: recompose.leadS must be a number in [0, 0.5]s")
    move = spec.get("moveS")
    if move is not None and (isinstance(move, bool)
                             or not isinstance(move, (int, float))
                             or not (_SMOOTH["min_ease_s"] <= float(move)
                                     <= 1.5)):
        rep.error(f"{tag}: recompose.moveS must be a number in "
                  f"[{_SMOOTH['min_ease_s']}, 1.5]s")


def _check_rail_recompose(plan: dict, graphics: list[dict], out_dur: float,
                          rep: Any) -> None:
    """Fail closed unless every occluding rail has its measured transform."""
    punch_ins = plan.get("punchIns") or []
    for i, g in enumerate(graphics):
        issue = recompose.window_issue(g, plan, punch_ins, out_dur)
        if issue:
            rep.error(f"graphicsTrack[{i}]: {g.get('kind')} rail recompose "
                      f"is not delivery-safe: {issue}; run "
                      "motion/recompose.py with measured faceBBoxNorm")
            continue
        # An explicit beside-face panel must carry a measured recompose even when
        # its renderer is not yet in the geometry registry. Floating free-band
        # overlays (logos/kinetic text) do not occlude a vertical stage and must
        # not force a camera move merely because they are transparent overlays.
        if (g.get("anchor", "free-band") == "beside-face"
                and not recompose._wants_recompose(g)):
            rep.error(f"graphicsTrack[{i}]: {g.get('kind')} is a beside-face panel "
                      "beside the face with no measured recompose — make it an "
                      "own-screen full-frame cutaway or add a synced recompose "
                      "(the footage would otherwise sit off-centre under it)")


# --------------------------------------------------------------------------- #
# Layout discipline (defect 7) + flash transitions (defect 8).
# --------------------------------------------------------------------------- #
def _check_layout_families(graphics: list[dict], rep: Any) -> None:
    """The pro alternates TWO canonical layouts + one lower panel for 187s;
    six one-off layout systems in 81s reads undesigned."""
    families = sorted({_FAMILIES[k] for k in
                       (str(g.get("kind", "")) for g in graphics)
                       if k in _FAMILIES})
    cap = _SMOOTH["max_layout_families"]
    if len(families) > cap:
        rep.warn(f"{len(families)} layout families in one longform "
                 f"({', '.join(families)}) — above the {cap}-family "
                 "discipline cap; the reference alternates rail + takeover "
                 "(+ one lower panel) with pixel-identical slots (defect 7)")


def _warn_flash_transitions(plan: dict, rep: Any) -> None:
    """Flashy seam covers (flash/leak) are off the measured longform grammar —
    the reference joins everything with panel sweeps and under-panel cuts
    (defect 8). WARN, not error: flash/leak stay legal where already measured.
    (Stock xfade kinds are a hard ERROR in plan_lint_motion — LL-014.)"""
    events = [ev for ev in plan.get("transitions") or []
              if ev.get("kind") in ("white-flash", "light-leak")]
    if events:
        times = ", ".join(f"{float(ev.get('outTime', -1)):.1f}s"
                          for ev in events)
        rep.warn(f"{len(events)} flash/leak transition(s) at {times} — "
                 "off-grammar for longform (the reference uses zero in 187s; "
                 "cover joins with a panel sweep or an under-panel cut)")


# --------------------------------------------------------------------------- #
# Gap-filler zoom pairs (LL-007) — zooms are not gap-fillers.
# --------------------------------------------------------------------------- #
def _annotated(w: dict) -> bool:
    """True when the window carries emphasis evidence: a non-empty
    ``evidence`` quote or a non-mechanical ``trigger``. The zoom proposer
    stamps both on every semantic candidate; a hand-authored emphasis punch
    must too. A bare ``reason`` is NOT evidence — pacing-fill rows carry one
    and are exactly the gap-fillers this rule exists to catch."""
    if str(w.get("evidence") or "").strip():
        return True
    return str(w.get("trigger") or "").strip() not in ("", "aliveness-creep")


def _zoom_pair_spans(wins: list[dict]) -> list[tuple[float, float, bool]]:
    """(start, end, annotated) for every in→out zoom pair that RESOLVES back
    to wide: a non-ramp window (static punch / eased push / bracket) is a
    pair by itself — its scale departs at outStart and returns at outEnd —
    unless it hands off to a contiguous next zoom; a contiguous ramp-OUT is
    its explicit release and joins the pair."""
    pairs: list[tuple[float, float, bool]] = []
    for i, w in enumerate(wins):
        if w.get("ramp") is not None:
            continue                       # lone ramps are creeps, not pairs
        s, e = float(w["outStart"]), float(w["outEnd"])
        ann = _annotated(w)
        nxt = wins[i + 1] if i + 1 < len(wins) else None
        if nxt is not None \
                and float(nxt["outStart"]) - e <= _SMOOTH["seam_tol_s"]:
            if (nxt.get("ramp") or {}).get("direction") != "out":
                continue                   # hands off to another zoom — no
                                           # return to wide at this boundary
            e = float(nxt["outEnd"])       # punch + contiguous release ramp
            ann = ann or _annotated(nxt)
        pairs.append((s, e, ann))
    return pairs


def _warn_gap_filler_zooms(plan: dict, graphics: list[dict], rep: Any) -> None:
    """LL-007: a zoom-in followed by its release within ``gap_pair_max_s``,
    overlapping NO graphic window and carrying NO emphasis annotation,
    exists only to keep the screen alive (the v2 14-17s pair filled the
    12.47→19.60 graphics gap) — prefer a graphic / panel extension."""
    wins = sorted((w for w in plan.get("punchIns") or []
                   if w.get("role") not in ("aliveness", "recompose")
                   and isinstance(w.get("outStart"), (int, float))
                   and isinstance(w.get("outEnd"), (int, float))),
                  key=lambda w: float(w["outStart"]))
    if not wins:
        return
    cap = _SMOOTH["gap_pair_max_s"]
    g_spans = [(float(g.get("outStart", -1)), float(g.get("outEnd", -1)))
               for g in graphics]
    for s, e, annotated in _zoom_pair_spans(wins):
        if e - s > cap or annotated:
            continue
        if any(gs < e and s < ge for gs, ge in g_spans):
            continue                       # the zoom serves a graphic moment
        rep.warn(f"punchIns: zoom-in at {s:.2f}s releases by {e:.2f}s "
                 f"(within {cap:g}s) with no graphic window overlapping and "
                 "no emphasis trigger/evidence — zoom pair fills a gap; "
                 "prefer a graphic/panel extension (LL-007)")
