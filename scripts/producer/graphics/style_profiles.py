#!/usr/bin/env python3
"""Executable visual-grammar profiles for semantic longform graphics.

Profiles keep editorial taste out of free-form prompts.  The model may classify
the transcript into a semantic shape, but code owns the information form,
chassis, renderer kind, payload contract, and release thresholds.
"""
from __future__ import annotations

from typing import Any

FACE_BRIDGE_PROFILE = "nateherk-editorial-v1"

# Data catalog: information form -> executable renderer contract.  Several
# forms intentionally share one modular renderer kind.  Variety lives in the
# information anatomy (contentMode/grid), not in duplicating HTML chassis.
_FACE_BRIDGE_FORMS: dict[str, dict[str, Any]] = {
    "tool-logo-orbit": {
        "kind": "icon-badge-wide", "chassis": "overlay",
        "anchor": "free-band", "shapes": ("tool-list",),
        "required": ("icon1", "icon2", "icon3", "at1", "at2", "at3"),
        "fixedSpec": {},
    },
    "credential-plaque": {
        "kind": "avatar-bio-card", "chassis": "dark-full",
        "anchor": "own-screen", "shapes": ("credibility",),
        "required": ("initials", "line1", "line2", "at1", "at2", "at3"),
        "fixedSpec": {},
    },
    "evidence-map": {
        "kind": "whiteboard-map", "chassis": "cream-full",
        "anchor": "own-screen", "shapes": ("evidence", "process"),
        "required": ("title", "node1", "node2", "node3",
                     "at1", "at2", "at3"),
        "fixedSpec": {},
    },
    "status-queue": {
        "kind": "nateherk-rail", "chassis": "cream",
        "shapes": ("process", "evidence", "list"),
        "required": ("eyebrow", "headlineLines", "rows", "moduleLands"),
        "fixedSpec": {"contentMode": "status"},
    },
    "dated-timeline": {
        "kind": "nateherk-rail", "chassis": "cream",
        "shapes": ("chronology", "process"),
        "required": ("eyebrow", "headlineLines", "rows", "moduleLands"),
        "fixedSpec": {"contentMode": "timeline"},
    },
    "step-sequence": {
        "kind": "nateherk-rail", "chassis": "cream",
        "shapes": ("process", "list"),
        "required": ("eyebrow", "headlineLines", "rows", "moduleLands"),
        "fixedSpec": {"contentMode": "steps"},
    },
    "resolved-checklist": {
        "kind": "nateherk-rail", "chassis": "cream",
        "shapes": ("qa", "list", "process"),
        "required": ("eyebrow", "headlineLines", "rows", "footChip",
                     "moduleLands"),
        "fixedSpec": {"contentMode": "checklist"},
    },
    "kv-rail": {
        "kind": "nateherk-rail", "chassis": "cream",
        "shapes": ("configuration", "evidence"),
        "required": ("eyebrow", "headlineLines", "rows", "moduleLands"),
        "fixedSpec": {"contentMode": "kv"},
    },
    "config-ledger": {
        "kind": "nateherk-ledger-dark", "chassis": "dark",
        "shapes": ("configuration", "evidence", "credibility"),
        "required": ("eyebrow", "headlineLines", "rows", "gridItems",
                     "moduleLands"),
        "fixedSpec": {"grid": "chips", "presenterFrame": True},
    },
    "parallel-grid": {
        "kind": "nateherk-ledger-dark", "chassis": "dark",
        "shapes": ("parallel-process", "process"),
        "required": ("eyebrow", "headlineLines", "barLabel", "barValue",
                     "gridItems", "footChip", "moduleLands"),
        "fixedSpec": {"grid": "columns", "presenterFrame": True},
    },
    "comparison-bars": {
        "kind": "nateherk-takeover", "chassis": "dark",
        "shapes": ("comparison",),
        "required": ("eyebrow", "headlineLines", "heroLabel", "heroValue",
                     "heroPct", "compareLabel", "compareValue", "comparePct",
                     "deltaChip", "evidenceSource", "moduleLands"),
        "fixedSpec": {},
    },
    "hero-scoreboard": {
        "kind": "nateherk-scoreboard", "chassis": "dark",
        "shapes": ("scale", "comparison", "limit"),
        "required": ("eyebrow", "heroValue", "heroLabel", "tiles",
                     "limitText", "moduleLands"),
        "fixedSpec": {"presenterFrame": True},
    },
    "threshold-bars": {
        "kind": "nateherk-bullet-bars", "chassis": "cream",
        "anchor": "beside-face",
        "shapes": ("limit", "scale"),
        "required": ("eyebrow", "headlineLines", "axisLabel", "bars",
                     "verdict", "moduleLands"),
        "fixedSpec": {},
    },
    "node-pipeline": {
        "kind": "nateherk-pipeline", "chassis": "dark",
        "shapes": ("process", "chapter", "mechanism"),
        "required": ("eyebrow", "headlineLines", "nodes", "moduleLands"),
        "fixedSpec": {"presenterFrame": True},
    },
    "thesis-statement": {
        "kind": "fragment-payoff", "chassis": "overlay",
        "anchor": "free-band",
        "shapes": ("thesis", "chapter"),
        "required": ("fragment", "payoff", "payoffAt"),
        "fixedSpec": {},
    },
}

_FACE_BRIDGE_PREFERENCES = {
    "tool-list": ("tool-logo-orbit", "resolved-checklist", "step-sequence"),
    "audience-list": ("step-sequence", "resolved-checklist", "status-queue"),
    "chronology": ("dated-timeline",),
    "parallel-process": ("parallel-grid", "node-pipeline"),
    "configuration": ("config-ledger", "kv-rail"),
    "comparison": ("comparison-bars", "hero-scoreboard", "threshold-bars"),
    "limit": ("threshold-bars", "hero-scoreboard"),
    "scale": ("hero-scoreboard", "threshold-bars"),
    "qa": ("resolved-checklist", "parallel-grid"),
    "mechanism": ("node-pipeline", "step-sequence"),
    "process": ("status-queue", "step-sequence", "node-pipeline",
                "parallel-grid", "dated-timeline"),
    "evidence": ("evidence-map", "config-ledger", "kv-rail", "status-queue"),
    "credibility": ("credential-plaque", "config-ledger", "kv-rail"),
    "list": ("step-sequence", "resolved-checklist", "status-queue"),
    "chapter": ("node-pipeline", "thesis-statement"),
    "thesis": ("thesis-statement",),
}

STYLE_PROFILES: dict[str, dict[str, Any]] = {
    FACE_BRIDGE_PROFILE: {
        "graphicsStyle": "face-bridge",
        "forms": _FACE_BRIDGE_FORMS,
        "shapePreferences": _FACE_BRIDGE_PREFERENCES,
        "denseWindowStartS": 13.5,
        "denseWindowEndS": 187.0,
        "minimumCoverageRatio": 0.85,
        # The current modular pack exposes 15 executable information forms.
        # Raise toward the 19/20 reference ratio as scanner/UI-diff/domain
        # diagram forms land; never fake diversity by renaming one anatomy.
        "minimumDistinctFormRatio": 0.60,
        "maximumZoom": 1.15,
        "maximumRendererUses": 2,
        "forbidAdjacentRendererReuse": True,
        "darkPresenterRect": (1344, 60, 534, 960),
        "semanticWindow": "full",
    },
}


def profile(name: str | None) -> dict[str, Any] | None:
    """Return one immutable-style profile catalog entry."""
    return STYLE_PROFILES.get(str(name or ""))


def profile_name(target: dict | None) -> str | None:
    """Resolve the selected profile only for the face-bridge grammar."""
    target = target or {}
    if target.get("graphicsStyle") != "face-bridge":
        return None
    value = target.get("visualProfile")
    return str(value) if isinstance(value, str) and value else None


def target_errors(target: dict | None) -> list[str]:
    """Validate the typed style/profile relationship."""
    target = target or {}
    style = target.get("graphicsStyle")
    name = target.get("visualProfile")
    if style != "face-bridge":
        if name is not None:
            return ["target.visualProfile is only valid with graphicsStyle "
                    "'face-bridge'"]
        return []
    if not isinstance(name, str) or not name:
        return ["face-bridge requires target.visualProfile"]
    found = profile(name)
    if found is None:
        return [f"unknown target.visualProfile {name!r}"]
    if found["graphicsStyle"] != style:
        return [f"visual profile {name!r} does not implement {style!r}"]
    return []


def forms_for_shape(name: str | None, shape: str) -> list[str]:
    """Ranked information forms for one semantic shape."""
    found = profile(name)
    if found is None:
        return []
    return list(found["shapePreferences"].get(shape) or ())


def form_contract(name: str | None, information_form: str) -> dict | None:
    """Renderer/payload contract for one information form."""
    found = profile(name)
    if found is None:
        return None
    value = found["forms"].get(information_form)
    return dict(value) if isinstance(value, dict) else None


def compatible_kinds(name: str | None, forms: list[str]) -> list[str]:
    """Stable de-duplicated renderer kinds for information forms."""
    kinds = []
    for item in forms:
        contract = form_contract(name, item)
        kind = contract.get("kind") if contract else None
        if isinstance(kind, str) and kind not in kinds:
            kinds.append(kind)
    return kinds
