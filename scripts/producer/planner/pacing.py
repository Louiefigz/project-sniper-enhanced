#!/usr/bin/env python3
"""pacing — upstream visual-rhythm analysis for the PRODUCER planner.

Pacing belongs in the planner, not in QC: a plan that flatlines (a long
talking-head stretch with no visual change, or a hook that isn't front-loaded)
should be caught at the LINT gate, BEFORE render, so the brain can act on it.

This module is PURE (no I/O). It reduces a produced plan's output-time tracks to
the set of discrete VISUAL-CHANGE instants and derives the rhythm metrics the
lint warns on. A "visual change" is any of: a cut boundary (cutTrack), a graphic /
b-roll / title-card entrance, a seam transition, or a non-aliveness punch-in.
The continuous aliveness creep is background motion, NOT a discrete change, so it
is excluded. Thresholds come from ``producer_config`` (see docs/PACING_RHYTHM_
STUDY.md: long-form ~7 changes/min / ~4.6s shots / hook ×1.7; shorts ~17/min /
~2.7s / hook ×2.0 — the config floors sit deliberately below these medians).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from producer_config import HOOK_CONTRACT_WINDOW_S, MODES  # noqa: E402

# Two changes landing within this window (a cut + a graphic on the same beat) are
# one visual event, not two — collapse them so the rate isn't double-counted.
DEDUP_S = 0.15

# Fallback when a mode preset carries no hook window (study P2: first ~60s).
DEFAULT_HOOK_WINDOW_S = 60.0

# Suggested-fill grammar is MODE-KEYED (FAILURE_LEDGER LL-007, operator review
# v2 showpiece): a zoom authored purely to keep the screen alive reads as a
# pointless in→out pair (the v2 14-17s zoom existed only to fill the
# 12.47→19.60 graphics gap). LONGFORM fills therefore propose a GRAPHIC —
# extend the adjacent panel's hold or add one on the spoken beat — NEVER a
# punch. SHORTS keep the punch grammar (R13: zoom IS the cut). The brain still
# writes the WHAT (deterministic-not-agentic: code proposes, model decides).
_FILL_KIND = {"longform": "graphic"}
_FILL_KIND_DEFAULT = "punch"
FILL_HOLD_S = 1.5


def _cut_change_times(cut_track: list[dict]) -> list[float]:
    """Internal cut boundaries as cumulative output offsets.

    Each segment's output length is ``(end - start) / speed``; the running sum
    after each segment is a cut instant, EXCLUDING the final total (the video
    end, not a change) and t=0 (never emitted — the sum starts past the first
    segment). A single-segment track therefore contributes no cut changes.

    Args:
        cut_track: The plan's cutTrack (segments ``{sourceId, start, end, speed}``).

    Returns:
        Output-time seconds of each internal cut boundary, in order.
    """
    offsets: list[float] = []
    running = 0.0
    for seg in cut_track:
        speed = float(seg.get("speed", 1.0)) or 1.0
        running += (float(seg["end"]) - float(seg["start"])) / speed
        offsets.append(running)
    return offsets[:-1]


def _track_starts(entries: list[dict], field: str) -> list[float]:
    """Output-time value of ``field`` for every entry that carries it."""
    return [float(e[field]) for e in entries if field in e]


def _dedup(sorted_times: list[float]) -> list[float]:
    """Collapse instants within ``DEDUP_S`` of the last kept one (input sorted)."""
    kept: list[float] = []
    for t in sorted_times:
        if not kept or t - kept[-1] > DEDUP_S:
            kept.append(t)
    return kept


def visual_change_times(plan: dict) -> list[float]:
    """Sorted, deduped output-time instants where a visual change occurs.

    Unions cut boundaries with every track entrance (graphics / b-roll / title
    cards / treatment-state boundaries / transitions / non-aliveness punch-ins).
    Aliveness punch-ins are the continuous background creep and are excluded.
    Instants within ``DEDUP_S`` are
    merged (a cut + graphic on the same beat = one change).

    Args:
        plan: The edit plan (its output-time tracks).

    Returns:
        Ascending list of deduped visual-change instants (output seconds).
    """
    times = list(_cut_change_times(plan.get("cutTrack") or []))
    for key in ("graphicsTrack", "brollTrack", "titleCards"):
        times += _track_starts(plan.get(key) or [], "outStart")
    # Treatment-zone boundaries change the base visual state (talking head,
    # screen share, board, etc.) and are therefore retention events too.
    times += [t for t in _track_starts(plan.get("treatmentMap") or [], "outStart")
              if t > 0.0]
    times += _staged_land_times(plan.get("graphicsTrack") or [])
    times += _track_starts(plan.get("transitions") or [], "outTime")
    times += [float(p["outStart"]) for p in plan.get("punchIns") or []
              if p.get("role") != "aliveness" and "outStart" in p]
    return _dedup(sorted(times))


_AT_KEY = re.compile(r"^at\d+$")

# MODULE-pack land carriers (§5 items 2/4): ``spec.moduleLands`` (narration-
# paced module builds — a list of comp-relative seconds, validated by
# plan_lint_motion) and ``spec.statementLands`` (statement-card v2 swap times,
# a number or "a,b" string per the comp contract). Each land is a REAL discrete
# on-screen change exactly like the ``atN`` staged lands.
_LAND_KEYS = ("moduleLands", "statementLands")


def _land_values(val: object) -> list[float]:
    """Comp-relative land seconds from a lands field (list, number, or a
    pipe/comma-separated string). Malformed input counts NOTHING here —
    rejecting it is the lint's job, not the rhythm model's."""
    if isinstance(val, bool):
        return []
    if isinstance(val, (int, float)):
        return [float(val)]
    if isinstance(val, (list, tuple)):
        return [float(x) for x in val
                if isinstance(x, (int, float)) and not isinstance(x, bool)]
    if isinstance(val, str) and val.strip():
        try:
            return [float(tok) for tok in re.split(r"[|,]", val)]
        except ValueError:
            return []
    return []


def _staged_land_times(graphics: list[dict]) -> list[float]:
    """Internal build-state lands of staged comps, in output time.

    A staged comp's ``spec.atN`` keys are its element land times relative to
    the entry's outStart (the whiteboard/list/map/kinetic contract), and the
    MODULE-pack ``spec.moduleLands`` / ``spec.statementLands`` carry the same
    meaning (narration-paced module builds / statement swaps). Each land is a
    REAL discrete on-screen change (PRO_INTRO_ENVELOPE: pro graphics carry
    2-6 build states), so pacing counts them — an entry-start-only model reads
    a continuously-building comp as dead air.
    """
    lands: list[float] = []
    for g in graphics:
        start = g.get("outStart")
        if not isinstance(start, (int, float)):
            continue
        end = float(g.get("outEnd", float("inf")))
        spec = g.get("spec") or {}
        rel: list[float] = []
        for key, val in spec.items():
            if _AT_KEY.match(str(key)) and isinstance(val, (int, float)):
                rel.append(float(val))
        for key in _LAND_KEYS:
            rel.extend(_land_values(spec.get(key)))
        for r in rel:
            t = float(start) + r
            if t < end:
                lands.append(t)
    return lands


def _still_stretches(times: list[float], out_dur: float) -> list[tuple[float, float]]:
    """Consecutive change-to-change spans, bookended by 0 and ``out_dur``."""
    bounds = [0.0] + times + [out_dur]
    return [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]


# A still-stretch fully inside one of these spans (± this tolerance) is judged
# by the BODY still-gap ceiling even inside the hook window.
_PANEL_HOLD_TOL_S = 0.2


def _panel_hold_spans(plan: dict) -> list[tuple[float, float]]:
    """Live-panel holds: non-own-screen graphics windows whose footage carries
    a synced ``role:"recompose"`` punch window (motion/recompose.py).

    During one, the live face plays BESIDE the panel and the footage glides
    eased with it — the hold is visually active, not still. Measured on the
    reference (2026-07-10): all 8 rail windows hold 6.2-18.4s with ZERO
    discrete changes inside, and the smooth grammar (``plan_lint_smooth``)
    FORBIDS a punch under a live panel — so the hook still-gap ceiling cannot
    be satisfied there by any legal fill. These spans are judged by the body
    ceiling instead (never exempted outright: a hold past the body ceiling
    still flags).
    """
    recs = [w for w in plan.get("punchIns") or []
            if w.get("role") == "recompose"]
    spans: list[tuple[float, float]] = []
    for g in plan.get("graphicsTrack") or []:
        if g.get("anchor", "free-band") == "own-screen":
            continue
        gs, ge = float(g.get("outStart", -1)), float(g.get("outEnd", -1))
        if ge <= gs:
            continue
        for w in recs:
            if (float(w.get("outStart", 1e9)) <= gs + 1e-3
                    and float(w.get("outEnd", -1)) >= ge - 0.05):
                spans.append((gs, ge))
                break
    return spans


def _gap_ceiling(stretch: tuple[float, float],
                 panel_holds: list[tuple[float, float]],
                 region_cfg: tuple[float, float, float]) -> float:
    """The still-gap ceiling for one stretch: hook / body by region, body for
    a stretch riding entirely inside a recomposed panel hold."""
    s, e = stretch
    hook_window, hook_gap, body_gap = region_cfg
    if any(ps - _PANEL_HOLD_TOL_S <= s and e <= pe + _PANEL_HOLD_TOL_S
           for ps, pe in panel_holds):
        return body_gap
    return hook_gap if e <= hook_window else body_gap


def active_retention_gaps(plan: dict, window_s: float,
                          max_gap_s: float) -> list[tuple[float, float]]:
    """Quiet spans in an intro after counting every authored visual-state event.

    Reframed live-panel holds are continuously active and remain the one
    measured exception. Static cards still need staged lands; continuous
    aliveness creep does not turn a flat section into a retention event.
    """
    times = [time for time in visual_change_times(plan) if time < window_s]
    holds = _panel_hold_spans(plan)
    holds += [(float(zone.get("outStart", 0.0)),
               float(zone.get("outEnd", 0.0)))
              for zone in plan.get("treatmentMap") or []
              if zone.get("visualState") in ("screen-share", "mixed")]
    gaps: list[tuple[float, float]] = []
    for start, end in _still_stretches(times, window_s):
        active = any(left - _PANEL_HOLD_TOL_S <= start
                     and end <= right + _PANEL_HOLD_TOL_S
                     for left, right in holds)
        if not active and end - start > max_gap_s:
            gaps.append((start, end))
    return gaps


def nonhead_share(plan: dict, window_s: float) -> float:
    """Fraction of ``[0, window_s)`` covered by a non-head visual.

    Unions the graphicsTrack + brollTrack windows (the seconds a designed
    graphic, overlay, or b-roll is on screen — the PRO_INTRO_ENVELOPE's
    "non-head share"). Overlapping windows are merged so stacked entries
    (a dim matte under a kinetic quote) count once.

    Args:
        plan: The edit plan.
        window_s: Region length in output seconds (e.g. the intro window).

    Returns:
        Covered fraction in [0, 1]; 0.0 for an empty/degenerate window.
    """
    if window_s <= 0:
        return 0.0
    spans: list[tuple[float, float]] = []
    for key in ("graphicsTrack", "brollTrack"):
        for e in plan.get(key) or []:
            s, t = float(e.get("outStart", -1)), float(e.get("outEnd", -1))
            s, t = max(0.0, s), min(window_s, t)
            if t > s:
                spans.append((s, t))
    spans.sort()
    covered, cursor = 0.0, 0.0
    for s, t in spans:
        s = max(s, cursor)
        if t > s:
            covered += t - s
            cursor = t
    return covered / window_s


def _hook_body_rates(times: list[float], out_dur: float,
                     hook_window: float) -> tuple[float, float, float]:
    """Change rate (per min) in the hook window vs the body, and their ratio.

    ``hook_ratio`` is ``inf`` when every change is front-loaded (no body rate to
    divide by) and ``0.0`` when there are no changes at all (the rate check owns
    that case); the front-load gate treats both correctly.
    """
    hook_span = min(hook_window, out_dur)
    body_span = max(0.0, out_dur - hook_window)
    hook_count = sum(1 for t in times if t < hook_window)
    body_count = len(times) - hook_count
    hook_rate = hook_count / hook_span * 60.0 if hook_span > 0 else 0.0
    body_rate = body_count / body_span * 60.0 if body_span > 0 else 0.0
    if body_rate > 0:
        ratio = hook_rate / body_rate
    elif hook_rate > 0:
        ratio = float("inf")
    else:
        ratio = 0.0
    return hook_rate, body_rate, ratio


def _retention_window(plan: dict, out_dur: float, mode: str,
                      preset: dict) -> float:
    """Pacing window, widening short longform excerpts to the full 60s hook.

    ``MODES.longform.hook_window_s`` is a 30s zoom-cadence signal, while the
    Hook Contract owns the first 60s. A <=60s longform output (or one explicitly
    marked ``excerpt``) is all hook, so applying the body ceiling after 30s lets
    a sparse back half pass. Keep ordinary longform pacing unchanged.
    """
    configured = float(preset.get("hook_window_s", DEFAULT_HOOK_WINDOW_S))
    contract = float(HOOK_CONTRACT_WINDOW_S.get(mode, configured))
    target = plan.get("target") or {}
    all_intro = mode == "longform" and (bool(target.get("excerpt"))
                                         or out_dur <= contract + 0.05)
    return max(configured, contract) if all_intro else configured


def pacing_report(plan: dict, out_dur: float, mode: str,
                  pacing_cfg: dict | None = None) -> dict:
    """Rhythm metrics for a plan against its pacing thresholds.

    Args:
        plan: The edit plan.
        out_dur: Predicted output duration (seconds).
        mode: ``"longform"`` or ``"short"`` (unknown falls back to defaults).
        pacing_cfg: The resolved pacing profile (e.g. the talking-head tempo). When
            omitted, the mode's default fast floor is used — so ``gaps`` are judged
            against the SAME ceiling the caller warns with, not a stale mode value.

    Returns:
        ``changes_per_min``, ``longest_gap_s`` (the longest still stretch),
        ``gaps`` (the (start, end) stretches that EXCEED ``max_still_gap_s``), and
        ``hook_rate`` / ``body_rate`` / ``hook_ratio``.
    """
    preset = MODES.get(mode, {})
    cfg = pacing_cfg if pacing_cfg is not None else preset.get("pacing", {})
    body_gap = float(cfg.get("max_still_gap_s", 20.0))
    hook_gap = float(cfg.get("hook_still_gap_s", body_gap))   # tight intro; else no split
    hook_window = _retention_window(plan, out_dur, mode, preset)
    times = visual_change_times(plan)
    stretches = _still_stretches(times, out_dur)
    region_times = list(times)
    if 0.0 < hook_window < out_dur:
        region_times.append(hook_window)
    region_stretches = _still_stretches(sorted(region_times), out_dur)
    # Region-aware (docs/studies/PRODUCTION_ENVELOPE_STUDY.md): a stretch ENTIRELY inside
    # the hook window is judged against the tight hook ceiling (front-load);
    # a stretch crossing the boundary is split there, so its hook portion cannot
    # hide under the looser body ceiling — the hook stays dense, the body breathes.
    # RECOMPOSED PANEL HOLDS use the body ceiling even inside the hook: the
    # live face + panel + eased recompose ARE the visual activity (measured
    # on the reference 2026-07-10: 8/8 rail windows hold 6.2-18.4s with ZERO
    # discrete changes inside), and plan_lint_smooth FORBIDS punching under a
    # live panel — the hook ceiling would demand an impossible fill.
    panel_holds = _panel_hold_spans(plan)
    gaps = [(s, e) for s, e in region_stretches
            if (e - s) > _gap_ceiling((s, e), panel_holds,
                                      (hook_window, hook_gap, body_gap))]
    longest = max((e - s for s, e in stretches), default=0.0)
    hook_rate, body_rate, hook_ratio = _hook_body_rates(times, out_dur, hook_window)
    dur = out_dur if out_dur > 0 else 1e-9
    return {
        "changes_per_min": len(times) / dur * 60.0,
        "longest_gap_s": longest,
        "gaps": gaps,
        "hook_window": hook_window,
        "hook_gap": hook_gap,
        "body_gap": body_gap,
        "hook_rate": hook_rate,
        "body_rate": body_rate,
        "hook_ratio": hook_ratio,
    }


def _fill_reason(kind: str, ceiling: float, region: str) -> str:
    """The fill proposal's instruction — punch grammar (shorts) or the
    LL-007 graphic/panel-extension grammar (longform)."""
    if kind == "punch":
        return (f"pacing fill ({region}): break the still-gap to the "
                f"{ceiling:.0f}s {region} ceiling — punch on the nearest "
                "emphasis beat, or b-roll / a graphic if the words warrant it")
    return (f"pacing fill ({region}): break the still-gap to the "
            f"{ceiling:.0f}s {region} ceiling — extend the adjacent panel's "
            "hold or add a graphic on the spoken beat; never author a zoom "
            "just to keep the screen alive (LL-007)")


def _fill_row(at: float, end: float, style: tuple[float, str, str]) -> dict:
    """One fill proposal at ``at`` (clamped inside its gap); ``style`` =
    (ceiling, region, kind)."""
    ceiling, region, kind = style
    return {
        "at": round(at, 3),
        "outStart": round(at, 3),
        "outEnd": round(min(at + FILL_HOLD_S, end), 3),
        "kind": kind,
        "needsOperator": True,
        "reason": _fill_reason(kind, ceiling, region),
    }


def _walk_fills(s: float, e: float, region_cfg: tuple[float, float, float],
                kind: str) -> list[dict]:
    """Greedily break ``[s, e]`` so no run since the last change exceeds the
    ceiling AT that point — ``hook_gap`` before ``hook_window``, ``body_gap``
    after (``region_cfg`` = these three). Carrying the last change ACROSS the
    boundary is what stops a long body run from opening right where the dense
    hook ends (PRODUCTION_ENVELOPE_STUDY). ``kind`` is the mode's fill grammar.
    """
    hook_window, hook_gap, body_gap = region_cfg
    out: list[dict] = []
    last = s
    while True:
        in_hook = last < hook_window
        ceiling = hook_gap if in_hook else body_gap
        nxt = last + ceiling
        if nxt >= e - 1e-9:
            break
        out.append(_fill_row(nxt, e, (ceiling, "hook" if in_hook else "body",
                                      kind)))
        last = nxt
    return out


def suggest_fills(plan: dict, out_dur: float, mode: str) -> list[dict]:
    """Propose discrete visual-change fills to break each under-paced still-gap.

    REGION-AWARE (the front-load fix): a still-stretch is split at the hook
    boundary and each part densified to its OWN ceiling — the hook to
    ``hook_still_gap_s`` (~4s), the body to ``max_still_gap_s`` (~20s). This is
    what makes the first ``hook_window_s`` the DENSEST region of the cut instead
    of merely warning that it isn't. The fill KIND is mode-keyed (``_FILL_KIND``,
    LL-007): a SHORT fill is a punch — the universal, asset-free change (R13:
    zoom IS the cut) — but a LONGFORM fill proposes a GRAPHIC (extend the
    adjacent panel's hold or add one on the spoken beat); a zoom authored purely
    to keep the screen alive reads as a pointless in→out pair. This module is
    pure and cannot read the transcript, so the brain writes the WHAT. Every
    fill carries ``needsOperator``: these are PROPOSALS, not applied edits
    (deterministic-not-agentic — code proposes, the model decides).

    Args:
        plan: The edit plan.
        out_dur: Predicted output duration (seconds).
        mode: ``"longform"`` or ``"short"``.

    Returns:
        Fill proposals ``{at, outStart, outEnd, kind, needsOperator, reason}``,
        each landing inside the gap it breaks, in output order.
    """
    preset = MODES.get(mode, {})
    cfg = preset.get("pacing", {})
    body_gap = float(cfg.get("max_still_gap_s", 20.0))
    hook_gap = float(cfg.get("hook_still_gap_s", body_gap))
    hook_window = _retention_window(plan, out_dur, mode, preset)
    region_cfg = (hook_window, hook_gap, body_gap)
    kind = _FILL_KIND.get(mode, _FILL_KIND_DEFAULT)
    panel_holds = _panel_hold_spans(plan)
    fills: list[dict] = []
    for s, e in _still_stretches(visual_change_times(plan), out_dur):
        in_hold = any(ps - _PANEL_HOLD_TOL_S <= s and e <= pe + _PANEL_HOLD_TOL_S
                      for ps, pe in panel_holds)
        if in_hold and e - s <= body_gap:
            # A recomposed panel hold within the body ceiling needs no fill —
            # and a punch fill under a live panel is forbidden anyway
            # (plan_lint_smooth defect-4 guard).
            continue
        fills.extend(_walk_fills(s, e, region_cfg, kind))
    fills.sort(key=lambda f: f["at"])
    return fills


def _output_duration(cut_track: list[dict]) -> float:
    """Full predicted output length (sum of every segment's output length).

    Local (not ``plan_lint.output_duration_s``) to keep this module free of the
    lint import cycle (plan_lint → plan_lint_motion → pacing).
    """
    total = 0.0
    for seg in cut_track:
        speed = float(seg.get("speed", 1.0)) or 1.0
        total += (float(seg["end"]) - float(seg["start"])) / speed
    return total


def _cli_report(plan: dict) -> dict:
    """JSON-serialisable pacing report + fill suggestions for the CLI."""
    mode = (plan.get("target") or {}).get("mode", "short")
    out_dur = _output_duration(plan.get("cutTrack") or [])
    rep = pacing_report(plan, out_dur, mode)
    ratio = rep["hook_ratio"]
    return {
        "mode": mode,
        "outputDurationS": round(out_dur, 3),
        "changesPerMin": round(rep["changes_per_min"], 2),
        "longestGapS": round(rep["longest_gap_s"], 1),
        "gaps": [[round(s, 1), round(e, 1)] for s, e in rep["gaps"]],
        "hookRatio": "inf" if ratio == float("inf") else round(ratio, 2),
        "suggestedFills": suggest_fills(plan, out_dur, mode),
    }


def main() -> int:
    """CLI: print a plan's rhythm report + gap-fill suggestions (the brain's
    planning-loop instrument — run it, close each gap, re-run until clean)."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("plan", help="path to the edit plan JSON")
    args = ap.parse_args()
    with open(args.plan) as fh:
        plan = json.load(fh)
    print(json.dumps(_cli_report(plan), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
