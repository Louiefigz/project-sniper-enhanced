#!/usr/bin/env python3
"""graphics_planner_density — the density + doctrine TRIM for MG-4 proposals.

The "which candidates survive" half of the auto-graphics planner (assembly lives
in ``graphics_planner``, per-trigger decisions in ``graphics_planner_rules``).
Split out to keep each file within the 300-logic-line budget.

Greedy, rank-first pruning: the strongest candidate wins any overlap, then R12's
one-mark-once (the same brand mark / entity may not reappear inside a window) and
the MOTION zone density budgets thin the rest. Also builds the doctrine-shaped
treatment-map SUGGESTION. Nothing here mutates a plan — it ranks a PROPOSAL.
"""

from __future__ import annotations

from producer_config import MOTION
from planner import graphics_planner_rules as rules

_PLANNER = MOTION["planner"]


# =========================================================================== #
# Zone budgets.
# =========================================================================== #
def zone_for(t: float, zones: list[dict]) -> dict | None:
    """The treatment zone containing output-time ``t`` (None = untreated)."""
    for z in zones:
        if float(z["outStart"]) <= t < float(z["outEnd"]):
            return z
    return None


def budget_allowed(zone: dict) -> int:
    """Graphics a zone permits by its density budget (min 1)."""
    per10 = MOTION["zone_budget_per_10s"].get(zone.get("budget"), 1)
    span = max(0.1, float(zone["outEnd"]) - float(zone["outStart"]))
    return max(1, round(per10 * span / 10.0))


# =========================================================================== #
# Trim.
# =========================================================================== #
def trim(candidates: list[dict], zones: list[dict]) -> tuple[list[dict], list[dict]]:
    """Greedy rank-first accept: strongest wins overlaps; enforce R12 + budgets."""
    ranked = sorted(candidates, key=lambda c: (-rules.conf_rank(c["confidence"]),
                                               c["outStart"]))
    gap = _PLANNER["min_gap_s"]
    window = _PLANNER["one_mark_window_s"]
    accepted: list[dict] = []
    rejected: list[dict] = []
    per_zone: dict[int, int] = {}
    for cand in ranked:
        clash = _overlap(cand, accepted, gap)
        if clash is not None:
            rejected.append(reject_cand(cand, f"overlaps a stronger graphic at "
                                        f"{clash:.1f}s (min gap {gap}s)"))
            continue
        mark = _mark_clash(cand, accepted, window)
        if mark is not None:
            rejected.append(reject_cand(cand, f"R12 one-mark-once: {mark[0]} "
                                        f"already shown at {mark[1]:.1f}s "
                                        f"(within {window}s)"))
            continue
        zone = zone_for(cand["outStart"], zones)
        if zone is not None and per_zone.get(id(zone), 0) >= budget_allowed(zone):
            span = float(zone["outEnd"]) - float(zone["outStart"])
            rejected.append(reject_cand(cand, f"zone budget {zone.get('budget')!r} "
                                        f"full (~{budget_allowed(zone)} / {span:.0f}s)"))
            continue
        per_zone[id(zone)] = per_zone.get(id(zone), 0) + 1
        accepted.append(cand)
    accepted.sort(key=lambda c: c["outStart"])
    return accepted, rejected


def _overlap(cand: dict, accepted: list[dict], gap: float) -> float | None:
    """The outStart of an accepted graphic this candidate collides with (±gap)."""
    for a in accepted:
        if cand["outStart"] < a["outEnd"] + gap and a["outStart"] < cand["outEnd"] + gap:
            return a["outStart"]
    return None


def _mark_clash(cand: dict, accepted: list[dict], window: float):
    """(mark, time) of a same-mark graphic within ``window`` s, or None (R12).

    A "mark" is a brand icon file OR, for a mark-less entity, its text key — so a
    repeated entity ("MCP ... MCP") is thinned to one graphic just like a
    repeated icon (two OpenAI knots for one sentence — exactly what R12 forbids).
    """
    marks = set(cand.get("_marks") or [])
    if not marks:
        return None
    for a in accepted:
        shared = marks & set(a.get("_marks") or [])
        if shared and abs(a["outStart"] - cand["outStart"]) <= window:
            return sorted(shared)[0], a["outStart"]
    return None


def reject_cand(cand: dict, why: str) -> dict:
    """A rejected-row for a candidate dropped during the trim."""
    return {"trigger": cand["trigger"], "kind": cand["kind"],
            "outStart": cand["outStart"], "confidence": cand["confidence"],
            "evidence": cand["evidence"], "reason": why}


# =========================================================================== #
# Treatment-map suggestion.
# =========================================================================== #
def suggest_treatment_map(mode: str, out_dur: float, state_fn) -> list[dict]:
    """A doctrine-shaped treatment map: one kinetic zone (short) or intro+body
    (longform, per MOTION.longform_zone_defaults)."""
    state, _ = state_fn(min(1.0, out_dur / 2))
    visual_state = state or "talking-head"
    if mode != "longform":
        return [{"outStart": 0.0, "outEnd": round(out_dur, 3),
                 "treatment": _PLANNER["short_zone_treatment"],
                 "budget": _PLANNER["short_zone_budget"],
                 "visualState": visual_state}]
    defaults = MOTION["longform_zone_defaults"]
    intro_end = round(min(defaults["intro_kinetic_s"], out_dur), 3)
    zones = [{"outStart": 0.0, "outEnd": intro_end,
              "treatment": defaults["intro_treatment"],
              "budget": defaults["intro_budget"]}]
    if out_dur > intro_end:
        zones.append({"outStart": intro_end, "outEnd": round(out_dur, 3),
                      "treatment": defaults["body_treatment"],
                      "budget": defaults["body_budget"]})
    return zones
