"""Physical compatibility and pacing for verified HyperFrames catalog ports.

Visual source selection never substitutes an old house design. Native projects
use the complete upstream inventory and current-job reference/custom evidence.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable
from graphics.comp_capabilities import is_aspect_legal_kind, measured_aspect
from graphics.visual_source_policy import integrated_kinds
from planner.graphics_planner_density import reject_cand
from planner import graphics_planner_rules as rules

NATURAL_ASPECT = {"short": "9:16", "longform": "16:9"}
STYLES = ("catalog-first",)
DEFAULT_STYLE = "catalog-first"
HOOK_WINDOW_S = 120.0
OWN_SCREEN = {
    "hook": {"per_s": 27.5, "min_spacing_s": 10.0},
    "body": {"per_s": 45.0, "min_spacing_s": 15.0},
    "edge_start_s": 3.0, "edge_end_s": 5.0,
}


def kind_canvas() -> dict[str, str]:
    """Return measured canvases only for admitted upstream ports."""
    return {kind: measured_aspect(kind) or "unavailable" for kind in integrated_kinds()}


@dataclass(frozen=True)
class Ctx:
    """Retarget context: the output-time words + target parameters."""
    words: list
    mode: str
    aspect: str
    state_fn: Callable
    out_dur: float
    style: str = DEFAULT_STYLE      # graphics_style axis (see resolve_style)



def canvas_ok(kind: str, aspect: str) -> bool:
    """MG-4.3: a kind is proposable only on its own canvas ('any' = both).

    The fresh MEASURED matrix is authoritative. Declared dimensions drifted
    from rendered canvases through the 2026-07-23 mint cycles
    (LL-036/LL-037), so unavailable/unmeasured/error kinds are not proposed.
    """
    return is_aspect_legal_kind(kind, aspect)



def effective_canvas(kind: str) -> str:
    """The canvas the filter judged ``kind`` by (measured wins, for messages)."""
    return measured_aspect(kind) or "unavailable"



def natural_aspect(mode: str) -> str:
    return NATURAL_ASPECT.get(mode, "9:16")



def resolve_aspect(aspect: str | None, plan: dict, mode: str) -> str:
    """Param > plan.target.aspect > the mode's natural aspect."""
    if aspect:
        return aspect
    return (plan.get("target") or {}).get("aspect") or natural_aspect(mode)



def resolve_style(style: str | None, plan: dict) -> str:
    """The default visual source is upstream; prior style presets are retired."""
    from graphics.style_profiles import target_errors
    target = dict(plan.get("target") or {})
    if style is not None:
        target["graphicsStyle"] = style
    issues = target_errors(target)
    if issues:
        raise ValueError(issues[0])
    return "catalog-first"



def retarget(candidates: list[dict], ctx: Ctx) -> tuple[list[dict], list[dict]]:
    """Filter physical compatibility without replacing a selected catalog design."""
    from graphics.visual_source_policy import integrated_kinds
    kept = [row for row in candidates if row["kind"] in integrated_kinds()
            and canvas_ok(row["kind"], ctx.aspect)]
    return kept, [dict(row, reason="Native catalog selection/adaptation required")
                  for row in candidates if row not in kept]



def trim_own_screen(accepted: list[dict], mode: str,
                    out_dur: float) -> tuple[list[dict], list[dict]]:
    """Cap own-screen cutaways: hook window (first HOOK_WINDOW_S) runs
    ~1/27.5s with 10s spacing (operator retention doctrine + audit §2), the
    body 1/45s with 15s spacing; never in the first 3s / last 5s. Greedy
    rank-first, like density.trim."""
    if mode != "longform":
        return accepted, []
    own = [c for c in accepted if c.get("anchor") == "own-screen"]
    ranked = sorted(own, key=lambda c: (-rules.conf_rank(c["confidence"]),
                                        c["outStart"]))
    state = {"starts": [], "counts": {"hook": 0, "body": 0},
             "budgets": _own_screen_budgets(out_dur), "out_dur": out_dur}
    keep_ids: set[int] = set()
    rejected: list[dict] = []
    for cand in ranked:
        why = _own_screen_verdict(cand, state)
        if why:
            rejected.append(reject_cand(cand, why))
            continue
        state["counts"][_window(cand["outStart"])] += 1
        state["starts"].append(cand["outStart"])
        keep_ids.add(id(cand))
    kept = [c for c in accepted
            if c.get("anchor") != "own-screen" or id(c) in keep_ids]
    return kept, rejected



def _own_screen_budgets(out_dur: float) -> dict[str, int]:
    hook_len = min(out_dur, HOOK_WINDOW_S)
    body_len = max(0.0, out_dur - HOOK_WINDOW_S)
    body = int(body_len // OWN_SCREEN["body"]["per_s"])
    return {"hook": max(1, int(hook_len // OWN_SCREEN["hook"]["per_s"])),
            "body": max(1, body) if body_len > 0 else 0}



def own_screen_cap(out_dur: float) -> int:
    """Total own-screen cutaway budget for a longform of ``out_dur`` — hook +
    body (the SAME budget ``trim_own_screen`` enforces). Exposed so plan_lint
    caps takeovers with the proposer's retention-doctrine budget rather than a
    stricter flat/linear count that the proposer would routinely exceed."""
    return sum(_own_screen_budgets(out_dur).values())



def _window(t: float) -> str:
    return "hook" if t < HOOK_WINDOW_S else "body"



def _own_screen_verdict(cand: dict, state: dict) -> str | None:
    """Reject reason for an own-screen candidate, or None to accept."""
    start, win = cand["outStart"], _window(cand["outStart"])
    if start < OWN_SCREEN["edge_start_s"]:
        return f"own-screen inside the first {OWN_SCREEN['edge_start_s']:.0f}s"
    if cand["outEnd"] > state["out_dur"] - OWN_SCREEN["edge_end_s"]:
        return f"own-screen inside the last {OWN_SCREEN['edge_end_s']:.0f}s"
    spacing = OWN_SCREEN[win]["min_spacing_s"]
    near = [s for s in state["starts"] if abs(s - start) < spacing]
    if near:
        return (f"own-screen {abs(near[0] - start):.1f}s from the cutaway at "
                f"{near[0]:.1f}s (< {spacing:.0f}s {win}-window spacing)")
    if state["counts"][win] >= state["budgets"][win]:
        per = OWN_SCREEN[win]["per_s"]
        return (f"own-screen {win}-window budget full "
                f"({state['budgets'][win]} ≈ 1 per {per:.0f}s)")
    return None



def density_note() -> str:
    """One table line: which own-screen budget applied where (for the brain)."""
    hook, body = OWN_SCREEN["hook"], OWN_SCREEN["body"]
    return (f"own-screen density: hook 0-{HOOK_WINDOW_S:.0f}s = "
            f"1/{hook['per_s']:.0f}s, {hook['min_spacing_s']:.0f}s spacing "
            "(operator retention doctrine + audit §2); body = "
            f"1/{body['per_s']:.0f}s, {body['min_spacing_s']:.0f}s spacing; "
            f"edges {OWN_SCREEN['edge_start_s']:.0f}s/"
            f"{OWN_SCREEN['edge_end_s']:.0f}s")
