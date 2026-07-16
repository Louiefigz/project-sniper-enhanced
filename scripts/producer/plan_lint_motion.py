#!/usr/bin/env python3
"""plan_lint_motion — MG-track lint checks (graphics, treatment map, audio).

Split from plan_lint.py to respect the 300-line logic budget; same Report
accumulator pattern, wired into ``plan_lint.lint()``. Doctrine sources:
PRODUCER_MOTION_GRAPHICS_PLAN.md §1.5/§2.1/§3.1 and PRODUCER_PLAN.md §4.5.
"""

from __future__ import annotations

import math
import os
from typing import Any

from audio.sfx_library import resolve as resolve_sfx
from edit_scope import resolve_lanes, resolve_scope
from graphics.exit_on_cut import (effective_out_end, entry_errors,
                                  exit_grammar_issues, seams_from_plan)
from graphics.form_allocation import GATE_ILLEGAL_KINDS
from graphics.template_contract import entry_errors as template_entry_errors
from motion.zoom_pull import lint_event as lint_zoom_pull
from graphics.pip_hole import entry_has_hole
from plan_lint_nateherk import check_nateherk_entry
from plan_lint_smooth import check_smooth
from plan_lint_visual import check_row_lands, check_variety, check_visual
from planner.graphics_planner_longform import own_screen_cap, resolve_style
from planner.pacing import active_retention_gaps, nonhead_share, pacing_report
from planner.word_lock import off_boundary_s, word_boundaries
from producer_config import (CANVAS_BY_ASPECT, MODES, MOTION, PLACEMENT_SCALE,
                             SAFE_BOX)

# Face-relative anchors (R3/R4) — legal only where there's a face, and each needs
# a measured faceBBoxNorm to translate against (graphics_stage reads it per-entry).
_FACE_ANCHORS = MOTION.get("face_anchors", ("headroom", "chest", "beside-face"))


def _zone_for(t: float, zones: list[dict]) -> dict | None:
    """The treatment zone containing output-time ``t`` (None = untreated)."""
    for z in zones:
        if float(z["outStart"]) <= t < float(z["outEnd"]):
            return z
    return None


def _valid_bbox(bbox: Any) -> bool:
    """True if ``bbox`` is a 4-number ``[x, y, w, h]`` list, each in 0..1."""
    return (isinstance(bbox, (list, tuple)) and len(bbox) == 4
            and all(isinstance(v, (int, float)) and 0.0 <= float(v) <= 1.0
                    for v in bbox))


def _resolve_face_bbox(entry: dict, zone: dict | None, global_bbox: Any) -> Any:
    """faceBBoxNorm for a face-relative entry: entry → its zone → global plan.

    Returns the first non-None source (validity checked by the caller). The
    compositor reads the ENTRY-level value, so a zone/global hit is flagged as a
    warning to stamp it onto the entry.
    """
    for src in (entry.get("faceBBoxNorm"), (zone or {}).get("faceBBoxNorm"),
                global_bbox):
        if src is not None:
            return src
    return None


def check_treatment_map(plan: dict, out_dur: float, rep: Any) -> list[dict]:
    """Zones ordered, in-range, non-overlapping, with valid vocabulary."""
    zones = plan.get("treatmentMap") or []
    prev_end = 0.0
    for i, z in enumerate(zones):
        tag = f"treatmentMap[{i}]"
        s, e = float(z.get("outStart", -1)), float(z.get("outEnd", -1))
        if not (0 <= s < e <= out_dur + 0.05):
            rep.error(f"{tag}: window [{s},{e}] outside output duration {out_dur:.1f}s")
        if s < prev_end - 0.01:
            rep.error(f"{tag}: overlaps the previous zone")
        prev_end = max(prev_end, e)
        if z.get("treatment") not in MOTION["treatments"]:
            rep.error(f"{tag}: treatment {z.get('treatment')!r} not in {MOTION['treatments']}")
        state = z.get("visualState")
        if state is not None and state not in MOTION["visual_states"]:
            rep.error(f"{tag}: visualState {state!r} not in {MOTION['visual_states']}")
        budget = z.get("budget")
        if budget is not None and budget not in MOTION["zone_budget_per_10s"]:
            rep.error(f"{tag}: budget {budget!r} not in "
                      f"{sorted(MOTION['zone_budget_per_10s'])}")
    return zones


def _check_graphic_entry(entry: tuple[int, dict],
                         bounds: tuple[float, str, Any],
                         zones: list[dict], rep: Any) -> None:
    """Window, hold, anchor + visual-state legality for one graphics entry."""
    i, g = entry
    out_dur, mode, global_bbox = bounds
    tag = f"graphicsTrack[{i}]"
    s, e = float(g.get("outStart", -1)), float(g.get("outEnd", -1))
    if not (0 <= s < e <= out_dur + 0.05):
        rep.error(f"{tag}: window [{s},{e}] outside output duration {out_dur:.1f}s")
        return
    hold = e - s
    anchor = g.get("anchor", "free-band")
    if anchor not in MOTION["anchors"]:
        rep.error(f"{tag}: anchor {anchor!r} not in {MOTION['anchors']}")
    hold_min = MOTION["hold_min_s"].get(mode, 1.0)
    hold_max = MOTION["hold_max_s"].get(mode, 6.0)
    takeover_max = MOTION["takeover_max_s"].get(mode, 2.5)
    if hold < hold_min or hold > hold_max:
        rep.error(f"{tag}: hold {hold:.2f}s outside "
                  f"[{hold_min},{hold_max}]s")
    # Hole-comps (NATEHERK item 9, graphics/pip_hole.py) ARE wired: the
    # renderer fills the comp's transparent face hole with footage. The
    # speaker stays present, so they ride hold_max_s, not the takeover
    # ceiling. Gates (longform-only + own-screen) live in plan_lint_nateherk.
    kind = str(g.get("kind", ""))
    hole_wired = entry_has_hole(g)
    # canvas-pip-list keeps the speaker present as a PiP inset (R24) — not a
    # full takeover, so it rides hold_max_s, not the takeover ceiling.
    pip_kept = (kind in GATE_ILLEGAL_KINDS
                or bool(g.get("needsPip"))) and not hole_wired
    if pip_kept:
        # GUARDRAIL: pip_takeover.py (speaker-inset renderer) is unwired → empty
        # face hole. Block until wired; author a full-frame statement-card
        # instead — or a hole-comp (nateherk-takeover), whose static face
        # fill IS wired (graphics/pip_hole.py).
        rep.error(f"{tag}: needs pip_takeover (canvas-pip-list/needsPip) but that "
                  "renderer is unwired — renders an empty speaker hole; use a "
                  "full-frame statement-card")
    check_nateherk_entry(tag, g, mode, rep)
    if anchor == "own-screen" and hold > takeover_max and not (pip_kept or hole_wired):
        rep.error(f"{tag}: own-screen takeover {hold:.2f}s exceeds "
                  f"{takeover_max}s ({mode})")
    _check_module_lands(tag, g, hold, rep)
    if not g.get("reason"):
        rep.error(f"{tag}: missing reason — graphics must be purposeful")
    # exitOnCut / takeoverBase vocabulary (G4/G5) — shared with the renderers
    # via graphics.exit_on_cut so lint and composite can never drift.
    for err in entry_errors(g, tag):
        rep.error(err)
    if not kind:
        rep.error(f"{tag}: missing kind")
    else:
        for error in template_entry_errors(g):
            rep.error(f"{tag}: {error}")
    # A list/map cutaway must carry copy: an unfilled needsCopy BEAT
    # (graphics_planner_sequences) reaching the plan would render an EMPTY card.
    # The brain/LLM writes items via graphics_copy.fill_list_spec before merge.
    if kind in ("whiteboard-list", "whiteboard-map", "canvas-pip-list"):
        slot = "node" if kind == "whiteboard-map" else "item"
        has_items = any(str(k).startswith(slot) for k in (g.get("spec") or {}))
        if g.get("needsCopy") or not has_items:
            rep.error(f"{tag}: {kind} has no {slot}s — an unfilled needsCopy beat "
                      "reached the plan; the brain writes copy via "
                      "graphics_copy.fill_list_spec in the skill flow before merge")
    _ICONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "..", "..", "templates", "motion", "icons")
    for key, val in (g.get("spec") or {}).items():
        # Icon slots must resolve on disk — a typo renders a broken <img>
        # instead of failing the plan (icon-library author's flag). Validated
        # through the comps' OWN bare-name rule (".svg" appended when the
        # value has no dot — every icon comp's iconSrc), so the combined
        # resolver's vocabulary ("github", "lucide/check",
        # icon_library.resolve_name) passes the same gate the comp resolves.
        if not (key.startswith("icon") and val):
            continue
        fname = str(val)
        fname += "" if "." in fname else ".svg"
        if not os.path.exists(os.path.join(_ICONS_DIR, fname)):
            rep.error(f"{tag}: spec.{key} icon file {val!r} not in "
                      "templates/motion/icons/ — fetch it via icon_library.py")
    _check_placement(tag, g, mode, rep)
    zone = _zone_for(s, zones)
    _check_anchor_zone_legality((tag, anchor, s), g, zone, (global_bbox, rep))


def _check_module_lands(tag: str, g: dict, hold: float, rep: Any) -> None:
    """``spec.moduleLands`` — narration-paced module builds (NATEHERK_STUDY.md
    §5 item 4): the comp schedules each module's build at its land, so lands
    must be finite, strictly increasing, >= the spacing floor apart, and inside
    the hold. Absent key = no build schedule = no checks (additive field)."""
    lands = (g.get("spec") or {}).get("moduleLands")
    if lands is None:
        return
    if not isinstance(lands, list) or not lands:
        rep.error(f"{tag}: spec.moduleLands must be a non-empty array of "
                  "comp-relative seconds")
        return
    gap = MOTION["module_lands"]["min_spacing_s"]
    prev = None
    for k, t in enumerate(lands):
        if isinstance(t, bool) or not isinstance(t, (int, float)) \
                or not math.isfinite(float(t)):
            rep.error(f"{tag}: spec.moduleLands[{k}] must be a finite number "
                      f"(got {t!r})")
            return
        if not (0.0 <= float(t) <= hold + 0.05):
            rep.error(f"{tag}: spec.moduleLands[{k}] {float(t):g}s is outside "
                      f"the hold [0,{hold:.2f}]s — a module must land while "
                      "the card is on screen")
        if prev is not None and float(t) - prev < gap:
            rep.error(f"{tag}: spec.moduleLands[{k}] {float(t):g}s lands "
                      f"{float(t) - prev:.2f}s after the previous — lands must "
                      f"be strictly increasing and >= {gap}s apart")
        prev = float(t)


def _placement_point(tag: str, p: Any, rep: Any) -> tuple[float, float] | None:
    """Shape-check an explicit placement; return (x, y) or None after erroring."""
    if not isinstance(p, dict):
        rep.error(f"{tag}: placement must be an object {{x, y}} in comp-canvas px")
        return None
    for name in ("x", "y"):
        v = p.get(name)
        if isinstance(v, bool) or not isinstance(v, (int, float)) \
                or not math.isfinite(float(v)):
            rep.error(f"{tag}: placement.{name} must be a finite number "
                      f"(got {v!r})")
            return None
    return float(p["x"]), float(p["y"])


def _placement_scale_lint(tag: str, p: dict, rep: Any) -> float | None:
    """Shape+bounds-check ``placement.scale``; 1.0 when absent, None after erroring.

    Same band the renderer enforces (producer_config.PLACEMENT_SCALE) so lint
    and graphics_stage._placement_scale can never drift.
    """
    s = p.get("scale")
    if s is None:
        return 1.0
    if isinstance(s, bool) or not isinstance(s, (int, float)) \
            or not math.isfinite(float(s)):
        rep.error(f"{tag}: placement.scale must be a finite number (got {s!r})")
        return None
    lo, hi = PLACEMENT_SCALE["min"], PLACEMENT_SCALE["max"]
    if not lo <= float(s) <= hi:
        rep.error(f"{tag}: placement.scale {float(s):g} outside [{lo},{hi}] — "
                  "downscale stays crisp, upscale softens past the band")
        return None
    return float(s)


def _placed_box(g: dict, xy: tuple[float, float],
                scale: float) -> tuple[float, float, float, float]:
    """The box SAFE_BOX tests: the SCALED content extent pinned at the point.

    Uses the entry's measured/authored ``contentBBox`` ([x0,y0,x1,y1] comp px —
    the stage/editor stamp it from the rendered clip) scaled by ``scale`` with
    the top-left held at the pin. Without one, the extent is unknowable at lint
    time, so the box degenerates to the point — exactly the pre-scale check.
    """
    x, y = xy
    bbox = g.get("contentBBox")
    if _valid_px_bbox(bbox):
        cw = (float(bbox[2]) - float(bbox[0])) * scale
        ch = (float(bbox[3]) - float(bbox[1])) * scale
        return (x, y, x + max(0.0, cw), y + max(0.0, ch))
    return (x, y, x, y)


def _valid_px_bbox(bbox: Any) -> bool:
    """True for a 4-finite-number [x0, y0, x1, y1] pixel box."""
    return (isinstance(bbox, (list, tuple)) and len(bbox) == 4
            and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                    and math.isfinite(float(v)) for v in bbox))


def _check_placement(tag: str, g: dict, mode: str, rep: Any) -> None:
    """Explicit ``placement`` contract: {x, y[, scale]} finite comp-canvas px.

    The point pins the comp's rendered CONTENT top-left on the delivery canvas
    (graphics_stage._explicit_offset); optional ``scale`` resizes the clip
    uniformly about that pin — outside the PLACEMENT_SCALE band = ERROR.
    Off-canvas point = ERROR. Shorts only: SAFE_BOX tests the SCALED content
    box (``_placed_box``) — WARNING naming the violated edge, taste the
    operator may override. own-screen is a full-frame takeover — never
    draggable/placed/scaled. (The stage emits the true placedBBox.)
    """
    p = g.get("placement")
    if p is None:
        return
    if g.get("anchor", "free-band") == "own-screen":
        rep.error(f"{tag}: own-screen takeovers are full-frame — placement "
                  "is illegal")
        return
    xy = _placement_point(tag, p, rep)
    if xy is None:
        return
    x, y = xy
    canvas = CANVAS_BY_ASPECT[MODES.get(mode, {}).get("aspect", "9:16")]
    w, h = canvas["width"], canvas["height"]
    if not (0 <= x < w and 0 <= y < h):
        rep.error(f"{tag}: placement ({x:g},{y:g}) is outside the {w}x{h} "
                  "delivery canvas")
        return
    scale = _placement_scale_lint(tag, p, rep)
    if scale is None or mode != "short":
        return
    x0, y0, x1, y1 = _placed_box(g, xy, scale)
    edges = (("left", x0 < SAFE_BOX["left"]), ("top", y0 < SAFE_BOX["top"]),
             ("right", x1 > w - SAFE_BOX["right"]),
             ("bottom", y1 > h - SAFE_BOX["bottom"]))
    for edge, violated in edges:
        if violated:
            rep.warn(f"{tag}: placement ({x:g},{y:g}) crosses the SAFE_BOX "
                     f"{edge} edge — platform UI may cover it (operator taste "
                     "override allowed)")


def _check_anchor_zone_legality(ident: tuple[str, str, float], g: dict,
                                zone: dict | None,
                                ctx: tuple[Any, Any]) -> None:
    """Anchor × visual-state legality + face-relative faceBBoxNorm requirement."""
    tag, anchor, s = ident
    global_bbox, rep = ctx
    state = zone.get("visualState") if zone else None
    is_face = anchor in _FACE_ANCHORS
    if is_face:
        # Face-relative anchors (R3/R4) need a face — illegal over a screen-share
        # — and REQUIRE a faceBBoxNorm the compositor reads per-entry.
        if state == "screen-share":
            rep.error(f"{tag}: face-relative anchor {anchor!r} is illegal in a "
                      "screen-share zone (no face to anchor to)")
        bbox = _resolve_face_bbox(g, zone, global_bbox)
        if bbox is None:
            rep.error(f"{tag}: anchor {anchor!r} requires faceBBoxNorm (on the "
                      "entry, its zone, or a global plan key)")
        elif not _valid_bbox(bbox):
            rep.error(f"{tag}: faceBBoxNorm must be 4 numbers in 0..1")
        elif g.get("faceBBoxNorm") is None:
            rep.warn(f"{tag}: faceBBoxNorm resolved from the zone/plan, not the "
                     "entry — the compositor reads it per-entry; stamp it there")
    if zone is None:
        return
    # Visual-state doctrine (operator 2026-07-05): the screen is the star. Only
    # own-screen cutaways and focus-shift (base blurs back) may play over it.
    if (state == "screen-share" and not is_face
            and anchor not in ("own-screen", "focus-shift")):
        rep.error(f"{tag}: overlay graphics forbidden in a screen-share zone — "
                  "use anchor 'own-screen' (cutaway) or 'focus-shift' (blur) instead")
    if zone.get("treatment") == "clean":
        rep.error(f"{tag}: zone at {s:.1f}s is 'clean' — no graphics")


def check_graphics_track(plan: dict, out_dur: float, mode: str, rep: Any) -> None:
    """Per-entry rules + takeover count + per-zone density budgets."""
    graphics = plan.get("graphicsTrack") or []
    zones = plan.get("treatmentMap") or []
    global_bbox = plan.get("faceBBoxNorm")
    takeovers = 0
    for i, g in enumerate(graphics):
        _check_graphic_entry((i, g), (out_dur, mode, global_bbox), zones, rep)
        if g.get("anchor") == "own-screen":
            takeovers += 1
    _warn_exit_on_cut_clamps(plan, graphics, mode, rep)
    _check_exit_grammar(plan, graphics, mode, rep)
    cap = MOTION["takeover_max_count"].get(mode, 2)
    if mode == "longform":
        # Cap at the proposer's OWN hook-aware own-screen budget (retention
        # doctrine, graphics_planner_longform.own_screen_cap), floored at the
        # flat count — single source of truth so a valid proposal can't fail its
        # own lint. The old out_dur/300 scaling (~1/100s) was far stricter than
        # both the proposer (~1/42s) and the pro reference (~1/46s,
        # INTRO_MACHINE_VS_PRO_AUDIT §2).
        cap = max(cap, own_screen_cap(out_dur))
    if takeovers > cap:
        rep.error(f"{takeovers} own-screen takeovers (max {cap} in {mode})")
    for z in zones:
        budget = z.get("budget")
        if budget not in MOTION["zone_budget_per_10s"]:
            continue
        span = max(0.1, float(z["outEnd"]) - float(z["outStart"]))
        allowed = MOTION["zone_budget_per_10s"][budget] * span / 10.0
        count = sum(1 for g in graphics
                    if _zone_for(float(g.get("outStart", -1)), [z]) is not None)
        if count > max(1, round(allowed)):
            rep.error(f"zone at {z['outStart']}s: {count} graphics exceeds "
                      f"'{budget}' budget (~{max(1, round(allowed))} allowed)")


def _check_exit_grammar(plan: dict, graphics: list[dict], mode: str,
                        rep: Any) -> None:
    """``spec.exit`` vocabulary + the T-D blur-recede clamp rule (NATEHERK
    §5 item 2). The math lives in graphics.exit_on_cut.exit_grammar_issues —
    the same module the renderers clamp through, so lint can't drift."""
    entries = [(i, g) for i, g in enumerate(graphics)
               if (g.get("spec") or {}).get("exit") is not None]
    if not entries:
        return
    seams = seams_from_plan(plan) if plan.get("cutTrack") else []
    hold_min = MOTION["hold_min_s"].get(mode, 1.0)
    for i, g in entries:
        errs, warns = exit_grammar_issues(g, f"graphicsTrack[{i}]", seams,
                                          hold_min)
        for msg in errs:
            rep.error(msg)
        for msg in warns:
            rep.warn(msg)


def _warn_exit_on_cut_clamps(plan: dict, graphics: list[dict], mode: str,
                             rep: Any) -> None:
    """Preview the exit-on-cut clamp (G4): warn when it collapses a hold.

    The renderer clamps each ``exitOnCut`` entry's outEnd to the next cutTrack
    seam (graphics.exit_on_cut — the same math, single source). A clamp that
    lands the effective hold under the mode's hold floor means the next cut
    sits almost immediately after outStart — taste warning, not a wall.
    """
    entries = [(i, g) for i, g in enumerate(graphics)
               if g.get("exitOnCut") is True]
    if not entries or not plan.get("cutTrack"):
        return
    seams = seams_from_plan(plan)
    hold_min = MOTION["hold_min_s"].get(mode, 1.0)
    for i, g in entries:
        start = float(g.get("outStart", 0))
        end = effective_out_end(g, seams)
        if end < float(g.get("outEnd", 0)) and (end - start) < hold_min:
            rep.warn(f"graphicsTrack[{i}]: exitOnCut clamps the window to "
                     f"{end - start:.2f}s (< hold_min {hold_min}s) — the next "
                     "cut lands almost immediately after outStart")


def check_punch_ins(plan: dict, out_dur: float, mode: str, rep: Any) -> None:
    """The ZOOM track: per-window type validation + cadence budget + bracket cap.

    Punch-ins/outs, animated ramps and in→out brackets are CUT treatments
    (rendered by punch_in.py), so they live in the top-level ``punchIns`` section,
    NOT graphicsTrack. A STATIC punch holds ``zoom`` (in MOTION["punch_in"]'s
    1.05-1.25 band); a RAMP carries ``ramp: {direction, ratePctPerS}`` (rate in
    MOTION["zoom"]'s 0.3-1.8%/s band); a BRACKET carries ``bracket: true, holdS``
    and may reach the bigger ``step_max`` zoom. Beyond per-window bounds, the
    density must fit the MODE's cadence budget (R13: shorts uniform + cut-driven,
    long-form front-loaded hook/body) and brackets are capped per video. See
    REFERENCE_STYLE_STUDY.md R13 + LONGFORM_VISUAL_STUDY.md §2.
    """
    windows = plan.get("punchIns") or []
    zoom_hi = _punch_zoom_max(plan, mode)
    spans: list[tuple[float, float]] = []
    for i, w in enumerate(windows):
        tag = f"punchIns[{i}]"
        s, e = float(w.get("outStart", -1)), float(w.get("outEnd", -1))
        if not (0 <= s < e <= out_dur + 0.05):
            rep.error(f"{tag}: window [{s},{e}] outside output duration {out_dur:.1f}s")
        # role:"recompose" windows solve for the clear-region landing and may
        # need more pan-enabling zoom than the punch band (a centered face
        # landing 0.6651 needs z≈1.32) — they validate against the recompose
        # band ceiling instead (MOTION["recompose"]["zoom_cap"]).
        hi = (MOTION["recompose"]["zoom_cap"]
              if w.get("role") == "recompose" else zoom_hi)
        _check_punch_window(tag, w, (e - s, hi), rep)
        if any(s < pe and ps < e for ps, pe in spans):
            rep.error(f"{tag}: overlaps another punch-in window")
        spans.append((s, e))
    _check_bracket_cap(windows, rep)
    _check_zoom_cadence(_semantic_zooms(windows, plan, rep), out_dur, mode, rep)


# A recompose must land ON a cut seam — or glide INTO a graphic entrance
# (defect 1: the panel is the perceived event, the footage moves WITH it) —
# to ride free of the cadence budget.
RECOMPOSE_SEAM_TOL_S = 0.15
# A graphic-synced recompose starts up to leadS (0.12) BEFORE the panel; the
# entrance must land inside the window's opening glide for the exemption.
RECOMPOSE_GRAPHIC_LEAD_S = 0.6


def _semantic_zooms(windows: list[dict], plan: dict, rep: Any) -> list[dict]:
    """Drop cut-landing / graphic-synced ``role:"recompose"`` windows from
    the cadence count.

    PRO_INTRO_ENVELOPE: the pro alternates framing on (nearly) every cut —
    punch-cut alternation. Those recomposes are not new zoom EVENTS (the cut is
    the event), so they are exempt from the semantic cadence budget exactly like
    the aliveness carpet — but ONLY when they land on a cutTrack seam OR open a
    graphics window (defect 1: the face-anchored rail recompose moves WITH the
    panel; the panel is the event). A recompose floating mid-shot is a real
    mid-shot zoom: it stays in the count and gets a WARN naming the drift.
    """
    recomposes = [w for w in windows if w.get("role") == "recompose"]
    if not recomposes:
        return windows
    seams = seams_from_plan(plan)
    g_starts = [float(g.get("outStart", -1))
                for g in plan.get("graphicsTrack") or []]
    kept: list[dict] = []
    for w in windows:
        if w.get("role") != "recompose":
            kept.append(w)
            continue
        s = float(w.get("outStart", -1))
        if any(abs(s - seam) <= RECOMPOSE_SEAM_TOL_S for seam in seams):
            continue                      # on-seam: exempt (the cut is the event)
        if any(s - RECOMPOSE_SEAM_TOL_S <= gs <= s + RECOMPOSE_GRAPHIC_LEAD_S
               for gs in g_starts):
            continue                      # panel-synced: the panel is the event
        rep.warn(f"punchIns recompose at {s:.2f}s is not on a cut seam "
                 f"(±{RECOMPOSE_SEAM_TOL_S}s) nor synced to a graphic "
                 "entrance — counted against the zoom cadence")
        kept.append(w)
    return kept


def _punch_zoom_max(plan: dict, mode: str) -> float:
    """Style-aware punch ceiling (G17). A pace profile may carry
    ``punch_zoom_max`` (``pacing_jadenly``: 1.45 — the measured C5 step band
    tops out at x1.44, DaG @17.0, JADEN_STYLE.md §2/§10 G17); every other
    pace keeps the doctrine default ``MOTION['punch_in']['zoom_max']``."""
    profile = _pacing_profile(plan.get("target") or {}, mode) or {}
    return float(profile.get("punch_zoom_max", MOTION["punch_in"]["zoom_max"]))


def _check_punch_window(tag: str, w: dict, bounds: tuple[float, float],
                        rep: Any) -> None:
    """Validate one punchIns entry by its type (ramp / bracket / static).

    ``bounds`` = (window duration, static/push zoom ceiling) — the ceiling is
    pace-aware (G17, ``_punch_zoom_max``); brackets keep their own step_max.
    """
    dur, zoom_hi = bounds
    for ckey in ("centerX", "centerY"):
        c = w.get(ckey)
        if c is not None and not (isinstance(c, (int, float)) and 0.0 <= float(c) <= 1.0):
            rep.error(f"{tag}: {ckey} must be a number in [0,1]")
    attack = w.get("attackS")
    if attack is not None and not (isinstance(attack, (int, float))
                                   and 0.0 < float(attack) <= dur + 1e-6):
        rep.error(f"{tag}: attackS must be a number in (0,{dur:.2f}]s "
                  "(an eased-attack push eases in then holds within its window)")
    release = w.get("releaseS")
    if release is not None:
        atk = float(attack) if isinstance(attack, (int, float)) else 0.0
        if not (isinstance(release, (int, float)) and not isinstance(release, bool)
                and 0.0 <= float(release)
                and atk + float(release) <= dur + 1e-6):
            rep.error(f"{tag}: releaseS must be a number >= 0 with attackS + "
                      f"releaseS <= the {dur:.2f}s window (the eased release "
                      "tail resolves the push back to wide)")
        elif attack is None:
            rep.error(f"{tag}: releaseS requires attackS (a release is the "
                      "eased tail of a push window)")
    lo = MOTION["punch_in"]["zoom_min"]
    if w.get("ramp") is not None:
        _check_ramp(tag, w["ramp"], rep)
    elif w.get("bracket"):
        _check_bracket(tag, w, dur, rep)
    else:
        z = w.get("zoom")
        if not isinstance(z, (int, float)) or not (lo <= float(z) <= zoom_hi):
            rep.error(f"{tag}: zoom must be a number in [{lo},{zoom_hi}]")


def _check_ramp(tag: str, ramp: Any, rep: Any) -> None:
    """Validate a ramp field: direction + rate within the doctrine band."""
    lo, hi = MOTION["zoom"]["magnitude"]["ramp_rate_range"]
    if not isinstance(ramp, dict):
        rep.error(f"{tag}: ramp must be an object {{direction, ratePctPerS}}")
        return
    if ramp.get("direction") not in ("in", "out"):
        rep.error(f"{tag}: ramp.direction must be 'in' or 'out'")
    rate = ramp.get("ratePctPerS")
    if not isinstance(rate, (int, float)) or not (lo <= float(rate) <= hi):
        rep.error(f"{tag}: ramp.ratePctPerS must be a number in [{lo},{hi}]%/s")


def _check_bracket(tag: str, w: dict, dur: float, rep: Any) -> None:
    """Validate a bracket: bigger in-zoom allowed, holdS leaves a release tail."""
    lo = MOTION["punch_in"]["zoom_min"]
    bracket_hi = MOTION["zoom"]["magnitude"]["step_max"]
    z = w.get("zoom")
    if not isinstance(z, (int, float)) or not (lo <= float(z) <= bracket_hi):
        rep.error(f"{tag}: bracket zoom must be a number in [{lo},{bracket_hi}]")
    hold = w.get("holdS")
    if not isinstance(hold, (int, float)) or not (0.0 < float(hold) < dur):
        rep.error(f"{tag}: bracket holdS must be a number in (0,{dur:.2f})s "
                  "(the window must leave a release tail to resolve to wide)")


def _check_bracket_cap(windows: list[dict], rep: Any) -> None:
    """Brackets are the signature move — capped per video (study Rule 3)."""
    cap = MOTION["zoom"]["bracket_max_per_video"]
    n = sum(1 for w in windows if w.get("bracket"))
    if n > cap:
        rep.error(f"{n} in→out brackets exceeds the {cap}/video cap — brackets "
                  "are reserved for the biggest lines")


def _check_zoom_cadence(windows: list[dict], out_dur: float, mode: str,
                        rep: Any) -> None:
    """Zoom density vs the MODE's cadence budget (R13): shorts a uniform, cut-
    driven ceiling; long-form the front-loaded hook/body split."""
    by_mode = MOTION["zoom"]["by_mode"].get(mode)
    if not by_mode:
        return
    # Aliveness creeps are a continuous background layer, not semantic "events" —
    # they carpet the freeze and are exempt from the zoom cadence budget.
    windows = [w for w in windows if w.get("role") != "aliveness"]
    cad = by_mode["cadence"]
    if "per_min" in cad:                          # shorts: uniform + cut-driven
        allowed = max(1, round(cad["per_min"] * out_dur / 60.0))
        if len(windows) > allowed:
            rep.error(f"{len(windows)} zoom events exceed the ~{allowed} short-mode "
                      f"budget ({cad['per_min']}/min) — R13 rhythmic cadence")
        return
    _check_hook_body_cadence(windows, out_dur, cad, rep)


def _check_hook_body_cadence(windows: list[dict], out_dur: float, cad: dict,
                             rep: Any) -> None:
    """Long-form: the hook front-loads zooms (5/min); the body cruises (2/min)."""
    hook_s = cad["hook_s"]
    counts = {"hook": 0, "body": 0}
    for w in windows:
        counts["hook" if float(w.get("outStart", -1)) < hook_s else "body"] += 1
    regions = (("hook", min(hook_s, out_dur), cad["hook_per_min"], "first"),
               ("body", max(0.0, out_dur - hook_s), cad["body_per_min"], "after"))
    for name, span, per_min, where in regions:
        if span <= 0:
            continue
        allowed = max(1, round(per_min * span / 60.0))
        if counts[name] > allowed:
            rep.error(f"{counts[name]} zoom events {where} the first {hook_s:.0f}s "
                      f"exceed the ~{allowed} budget ({per_min}/min) — long-form "
                      "hook/body cadence")


def check_corrections(plan: dict, rep: Any) -> None:
    """captions.corrections is a non-empty-str → non-empty-str map."""
    corrections = (plan.get("captions") or {}).get("corrections")
    if corrections is None:
        return
    if not isinstance(corrections, dict):
        rep.error("captions.corrections must be an object {heard: corrected}")
        return
    for k, v in corrections.items():
        if not (isinstance(k, str) and k.strip() and isinstance(v, str) and v.strip()):
            rep.error(f"captions.corrections entry {k!r}: both sides must be "
                      "non-empty strings")


def check_motion(plan: dict, out_dur: float, mode: str, rep: Any) -> None:
    """All MG-track checks (called from plan_lint.lint)."""
    try:
        resolve_style(None, plan)
    except ValueError as exc:
        rep.error(f"graphics style decision: {exc}")
    check_treatment_map(plan, out_dur, rep)
    check_graphics_track(plan, out_dur, mode, rep)
    # audioGain moved to plan_lint_audio (parse_windows — the executor's own
    # validator, so lint and audio_gain.py can never drift).
    check_punch_ins(plan, out_dur, mode, rep)
    check_corrections(plan, rep)
    check_transitions(plan, out_dur, mode, rep)
    check_baseline_look(plan, rep)
    check_pacing(plan, out_dur, mode, rep)
    # Smooth longform grammar (defect report 2026-07-10): pop boundaries,
    # under-panel guard, rail recompose, layout discipline, flash warns.
    check_smooth(plan, out_dur, mode, rep)
    # Learning-loop visual rules (showpiece QC 2026-07-10, FAILURE_LEDGER
    # LL-002/LL-004/LL-005): empty-chrome staging, accent contrast, balance.
    check_visual(plan, rep)
    # LL-011 (operator doctrine, mandatory): progressive point reveal —
    # multi-item list comps on longform need per-item word-locked lands.
    check_row_lands(plan, mode, rep)
    # LL-016 (NATEHERK_CARDS §2): produced/full longform fails on consecutive
    # same-kind windows or a proportional distinct-kind floor miss.
    check_variety(plan, mode, rep, out_dur)


def _check_transition_kind_sfx(ev: dict, tag: str, mode: str, rep: Any) -> None:
    """Kind vocabulary (flash/leak/zoom-pull — the xfade family is BANNED in
    all modes, LL-014) + the SFX slot (bool, or a named one-shot from
    audio/sfx_library). A zoom-pull runs the executor's own validator
    (``motion.zoom_pull.lint_event``: longform-only, measured bands,
    a-roll<->b-roll seam-role advisory) — lint and primitive cannot drift;
    density stays with ``check_transitions`` (zoom-pulls are budget-counted
    like every seam cover)."""
    cfg = MOTION["transitions"]
    kind = ev.get("kind")
    if isinstance(kind, str) and kind.startswith("xfade:"):
        rep.error(f"{tag}: {kind!r} — operator-rejected: use the studied "
                  "longform transition grammar (FAILURE_LEDGER LL-014): panel "
                  "sweeps, face-bridged recomposition, under-panel cuts, "
                  "blur-recede, seam-role zoom-pulls; never stock "
                  "wipes/slides/dissolves")
    elif kind not in cfg["kinds"]:
        rep.error(f"{tag}: kind {kind!r} not in {cfg['kinds']}")
    elif kind == "zoom-pull":
        errors, warns = lint_zoom_pull(ev, tag, mode)
        for msg in errors:
            rep.error(msg)
        for msg in warns:
            rep.warn(msg)
    sfx = ev.get("sfx", False)
    if isinstance(sfx, str):
        try:                        # the executor's own resolver — no drift
            resolve_sfx(sfx)
        except ValueError as exc:
            rep.error(f"{tag}: {exc}")
    elif not isinstance(sfx, bool):
        rep.error(f"{tag}: sfx must be a boolean or a named SFX "
                  "(audio/sfx_library)")


def check_transitions(plan: dict, out_dur: float, mode: str, rep: Any) -> None:
    """Seam-cover transitions: kind vocabulary, range, order/spacing, density.

    Transitions are CUT treatments rendered by transitions.py, so they live in
    the top-level ``transitions`` list ({outTime, kind, sfx?}). Doctrine (R15,
    INTRO_MACHINE_VS_PRO_AUDIT §3): flashes/washes cover world-changes only —
    more than ~2/min reads strobe, not grammar. Any ``xfade:*`` kind is a
    hard ERROR in every mode (operator-rejected, LL-014).
    """
    cfg = MOTION["transitions"]
    events = plan.get("transitions") or []
    prev = None
    for i, ev in enumerate(events):
        tag = f"transitions[{i}]"
        t = ev.get("outTime")
        if not isinstance(t, (int, float)) or not (0.5 <= float(t) <= out_dur - 0.5):
            rep.error(f"{tag}: outTime must be a number in [0.5,{out_dur - 0.5:.1f}]s")
            continue
        _check_transition_kind_sfx(ev, tag, mode, rep)
        if prev is not None and float(t) - prev < cfg["min_spacing_s"]:
            rep.error(f"{tag}: seams must be sorted and >= {cfg['min_spacing_s']}s "
                      f"apart (prev {prev}s, this {t}s)")
        prev = float(t)
    if events and out_dur > 0:
        allowed = max(1, round(cfg["max_per_min"] * out_dur / 60.0))
        if len(events) > allowed:
            rep.error(f"{len(events)} transitions exceed the ~{allowed} budget "
                      f"({cfg['max_per_min']}/min) — flashes cover world-changes, "
                      "not every cut")


def check_word_lock(plan: dict, words_out: list[dict], rep: Any) -> None:
    """WARN on seams sitting off the kept-word grid (NATEHERK_STUDY.md T-G).

    Every transition in the reference lands on a narration phrase boundary
    (4/4 VTT spot checks), so ``transitions[].outTime`` and
    ``graphicsTrack[].outStart`` further than
    ``MOTION['word_lock']['warn_off_boundary_s']`` (150ms) from the nearest
    KEPT-word boundary draw a WARN. Deterministic: ``words_out`` are the kept
    words in OUTPUT time — callers without a transcript skip this check
    (plan_lint runs it only when given a transcripts dir). Fix at plan time
    with ``planner.word_lock.snap_to_word_boundary`` / ``snap_plan_seams``.
    """
    tol = MOTION["word_lock"]["warn_off_boundary_s"]
    boundaries = word_boundaries(words_out)
    if not boundaries:
        return
    seams = [(f"transitions[{i}]: outTime", ev.get("outTime"))
             for i, ev in enumerate(plan.get("transitions") or [])]
    seams += [(f"graphicsTrack[{i}]: outStart", g.get("outStart"))
              for i, g in enumerate(plan.get("graphicsTrack") or [])]
    for tag, t in seams:
        if isinstance(t, bool) or not isinstance(t, (int, float)):
            continue                       # malformed times are the ERRORs' job
        off = off_boundary_s(float(t), boundaries)
        if off > tol:
            rep.warn(f"{tag} {float(t):g}s sits {off * 1000:.0f}ms from the "
                     f"nearest kept-word boundary (> {tol * 1000:.0f}ms) — "
                     "word-lock the seam (planner.word_lock.snap_to_word_"
                     "boundary; NATEHERK_STUDY T-G)")


# Editorial bounds for the plan-level ``baselineLook`` key (R16: the pro's
# baseline is a tight chest-up recrop + warm grade; rendered by
# baseline_look.py, whose hard-safety ceiling is wider at 2.0).
BASELINE_LOOK_ZOOM = (1.0, 1.5)
BASELINE_LOOK_CENTER = (0.2, 0.8)


def check_baseline_look(plan: dict, rep: Any) -> None:
    """The baseline-look key: zoom + crop center inside the editorial bands.

    ``baselineLook`` is a WHOLE-VIDEO treatment (baseline_look.py), not a
    window, so there is nothing temporal to validate — just the magnitude
    bands: zoom 1.0-1.5 (above 1.5 a 4K source crops below native 1080p
    density) and centers 0.2-0.8 (outside them the clamp pins the window to a
    frame edge and the recompose intent is lost). Every key is optional (the
    primitive's defaults are the pro-measured framing).
    """
    look = plan.get("baselineLook")
    if look is None:
        return
    if not isinstance(look, dict):
        rep.error("baselineLook must be an object {zoom, centerX, centerY, grade}")
        return
    zlo, zhi = BASELINE_LOOK_ZOOM
    z = look.get("zoom")
    if z is not None and (not isinstance(z, (int, float))
                          or not (zlo <= float(z) <= zhi)):
        rep.error(f"baselineLook.zoom must be a number in [{zlo},{zhi}] "
                  "(above 1.5 a 4K source drops below native 1080p density)")
    clo, chi = BASELINE_LOOK_CENTER
    for key in ("centerX", "centerY"):
        c = look.get(key)
        if c is not None and (not isinstance(c, (int, float))
                              or not (clo <= float(c) <= chi)):
            rep.error(f"baselineLook.{key} must be a number in [{clo},{chi}] "
                      "(outside it the crop pins to a frame edge)")
    if look.get("grade") not in (None, "warm", "none"):
        rep.error("baselineLook.grade must be 'warm' or 'none'")


def check_pacing(plan: dict, out_dur: float, mode: str, rep: Any) -> None:
    """Upstream visual-rhythm coordinator — WARN on an under-paced plan.

    Pacing belongs in the planner, not QC (docs/studies/PACING_RHYTHM_STUDY.md): a plan
    that flatlines is caught HERE, before render, so the brain can act on it.
    Every finding is a WARN, never an ERROR — pacing is guidance, not a wall.

    Gated to the engagement stack: a clean-cut plan (its ``target.treatment``
    has motion + graphics both False) is cuts-only by design, so this check does
    not apply and returns immediately. Otherwise it flags a low overall
    change-rate (P1), each still stretch past ``max_still_gap_s`` (P1: no shot
    past ~20s long-form / ~8s shorts without a change), and a hook that is not
    front-loaded enough (P2).
    """
    target = plan.get("target") or {}
    try:
        lanes = resolve_lanes(target)
    except ValueError:
        return
    if not any(lanes[lane] == "auto" for lane in
               ("motion", "graphics", "transitions", "broll")):
        return
    cfg = _pacing_profile(target, mode)
    if not cfg:
        return
    _warn_pacing(pacing_report(plan, out_dur, mode, cfg), cfg, rep)
    _warn_intro_envelope(plan, out_dur, cfg, rep)
    _check_intro_activity(plan, out_dur, cfg, rep)


def _check_intro_activity(plan: dict, out_dur: float, cfg: dict,
                          rep: Any) -> None:
    """Produced/full longform must keep its first 2–3 minutes visually active."""
    target = plan.get("target") or {}
    try:
        lanes = resolve_lanes(target)
        active = (target.get("mode") == "longform"
                  and resolve_scope(target) in ("produced", "full")
                  and any(lanes[lane] == "auto" for lane in
                          ("motion", "graphics", "transitions", "broll")))
    except ValueError:
        return  # target validation owns malformed intent
    if not active:
        return
    window = min(float(cfg.get("intro_window_s", 0.0)), out_dur)
    ceiling = float(cfg.get("hook_still_gap_s", 4.0))
    for start, end in active_retention_gaps(plan, window, ceiling):
        rep.error(f"pacing: produced intro has no perceived visual change from "
                  f"{start:.1f}s to {end:.1f}s ({end - start:.1f}s), above the "
                  f"{ceiling:.0f}s retention ceiling — add a cut, reframe, "
                  "graphic/internal build, b-roll, or transition")


def _warn_intro_envelope(plan: dict, out_dur: float, cfg: dict, rep: Any) -> None:
    """PRO_INTRO_ENVELOPE share floors, with a fail-closed first-minute wall.

    Measured on the pro reference (docs/findings/PRO_INTRO_ENVELOPE.md): the
    intro window carries a non-head visual ~32% of its seconds and ~50% inside
    the first 60s. A plan can pass every still-gap ceiling with punches alone
    and still read bare — the share floors catch that lane-mix failure.
    """
    window = min(float(cfg.get("intro_window_s", 0.0)), out_dur)
    floor = cfg.get("intro_min_nonhead_share")
    if window <= 0 or floor is None:
        return
    share = nonhead_share(plan, window)
    if share < float(floor):
        rep.warn(f"pacing: non-head visuals cover {share:.0%} of the "
                 f"{window:.0f}s intro — below the {float(floor):.0%} envelope "
                 "floor (add graphics / receipts / b-roll, not just punches)")
    hook60_floor = cfg.get("hook60_min_nonhead_share")
    hook60 = min(60.0, out_dur)
    if hook60_floor is not None and hook60 > 0:
        share60 = nonhead_share(plan, hook60)
        if share60 < float(hook60_floor):
            message = (f"pacing: non-head visuals cover {share60:.0%} of the first "
                       f"{hook60:.0f}s — below the {float(hook60_floor):.0%} "
                       "envelope floor (add graphics / receipts / b-roll; the "
                       "pro's first minute is ~50% dressed)")
            target = plan.get("target") or {}
            try:
                lanes = resolve_lanes(target)
                heavy = (target.get("mode") == "longform"
                         and resolve_scope(target) in ("produced", "full")
                         and any(lanes[lane] == "auto"
                                 for lane in ("graphics", "broll")))
            except ValueError:
                heavy = False  # target validation owns malformed scope values
            if heavy:
                rep.error(message + "; produced/full cannot waive this — select "
                          "trim/light explicitly for a clean/minimal treatment")
            else:
                rep.warn(message)


def _pacing_profile(target: dict, mode: str) -> dict | None:
    """The visual-rhythm floors for this plan — TEMPO-aware, not just mode.

    ``target.pace`` names a tempo profile, mapped to the mode's
    ``pacing_<pace>`` dict (dashes -> underscores): ``"talking-head"`` is the
    slow continuous-take profile (a yapping single-speaker short paces like
    long-form, not a fast produced reel); ``"jadenly"`` is the locked-tripod
    punch-cut profile (scripts/producer/docs/findings/JADEN_STYLE.md — ~17
    visible cuts/min, 12s still ceiling, states-driven cadence); ``"caleb"``
    is the SIMPLE-CUTS restraint pole (docs/studies/CALEB_STYLE.md — 0-cut reels are
    on-style, retention carried by verbatim caption churn, floors
    effectively off); ``"angela"`` is the takeover-alternation profile
    (docs/studies/ANGELA_STYLE.md — cuts are section punctuation, zero punch-ins,
    graphics-carried cadence with a relaxed hook front-load). An
    absent/unknown pace uses the mode's default fast
    floor (unchanged legacy behavior). Pace is a separate axis from treatment:
    a talking-head short is still produced (has graphics), just slow."""
    mode_cfg = MODES.get(mode, {})
    pace = str(target.get("pace") or "").replace("-", "_")
    profile = mode_cfg.get(f"pacing_{pace}") if pace else None
    return profile if profile is not None else mode_cfg.get("pacing")


def _warn_pacing(report: dict, cfg: dict, rep: Any) -> None:
    """Emit the rate / still-gap / hook-front-load warnings from a report."""
    rate, floor = report["changes_per_min"], cfg["min_changes_per_min"]
    if rate < floor:
        rep.warn(f"pacing: {rate:.1f} visual changes/min below the {floor}/min "
                 "floor — the cut is under-paced (add cuts / graphics / b-roll)")
    for s, e in report["gaps"]:
        in_hook = e <= report["hook_window"]
        ceiling = report["hook_gap"] if in_hook else report["body_gap"]
        region = "hook" if in_hook else "body"
        rep.warn(f"pacing: no discrete visual change from {s:.1f}s to {e:.1f}s "
                 f"({e - s:.1f}s) exceeds the {region} still-gap ceiling "
                 f"({ceiling:.0f}s) — add a cut / b-roll / graphic / punch "
                 "(aliveness creep alone doesn't count)")
    ratio, want = report["hook_ratio"], cfg["hook_front_load"]
    if ratio < want:
        rep.warn(f"pacing: hook front-load {ratio:.2f}x below {want}x — the "
                 "opening is not denser than the body (front-load the hook)")
