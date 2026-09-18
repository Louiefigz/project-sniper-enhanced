#!/usr/bin/env python3
"""Face-bridge longform retarget for the Nate Herk editorial profile.

The generic proposer still discovers transcript moments.  This module prevents
those moments from becoming floating glass widgets: every kept candidate is
retargeted into either the cream presenter-beside-panel chassis or the dark
presenter-in-PIP chassis.  Final information-form selection remains owned by
the profile-aware semantic allocator.
"""
from __future__ import annotations

from planner import graphics_planner_style as overlay_rich

_CREAM = {
    "glass-rail": "nateherk-rail",
    "whiteboard-list": "nateherk-rail",
    "list-build": "nateherk-rail",
    "glass-lower-third": "nateherk-rail",
    "nateherk-rail": "nateherk-rail",
    "nateherk-bullet-bars": "nateherk-bullet-bars",
}
_DARK = {
    "fragment-payoff": "nateherk-takeover",
    "kinetic-quote-wide": "nateherk-takeover",
    "section-takeover": "nateherk-takeover",
    "statement-card": "nateherk-takeover",
    "whiteboard-map": "nateherk-pipeline",
    "agenda-slide": "nateherk-pipeline",
    "stat-card": "nateherk-scoreboard",
    "widget-gauge": "nateherk-scoreboard",
    "versus-split": "nateherk-takeover",
    "whiteboard-connector": "nateherk-ledger-dark",
    "nateherk-takeover": "nateherk-takeover",
    "nateherk-ledger-dark": "nateherk-ledger-dark",
    "nateherk-scoreboard": "nateherk-scoreboard",
    "nateherk-pipeline": "nateherk-pipeline",
}


def _retarget_candidate(candidate: dict) -> dict:
    prior = str(candidate.get("kind") or "")
    if prior in _CREAM:
        return {**candidate, "kind": _CREAM[prior], "anchor": "beside-face",
                "needsCopy": True,
                "reason": f"face-bridge cream chassis: {candidate.get('reason', '')}"}
    if prior in _DARK:
        kind = _DARK[prior]
        spec = {**(candidate.get("spec") or {})}
        if kind != "nateherk-takeover":
            spec["presenterFrame"] = True
        return {**candidate, "kind": kind, "anchor": "own-screen",
                "spec": spec, "needsCopy": True,
                "reason": f"face-bridge dark chassis: {candidate.get('reason', '')}"}
    # Unknown generic overlays do not belong to this grammar.  Retain the
    # discovery as a rejected row rather than silently leaking a third chassis.
    return {**candidate, "_faceBridgeRejected": True}


def retarget(candidates: list[dict], ctx) -> tuple[list[dict], list[dict]]:
    """Discover with overlay-rich rules, then enforce the two-chassis world."""
    kept, rejected = overlay_rich.retarget(candidates, ctx)
    mapped, extra_rejected = [], []
    for candidate in kept:
        result = _retarget_candidate(candidate)
        if result.pop("_faceBridgeRejected", False):
            extra_rejected.append({**result, "trigger": result.get("trigger", "style"),
                                   "reason": "face-bridge profile has no legal "
                                             f"two-chassis mapping for {result.get('kind')!r}"})
        else:
            mapped.append(result)
    return mapped, [*rejected, *extra_rejected]
