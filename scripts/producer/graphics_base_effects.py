#!/usr/bin/env python3
"""Graphics fields that alter the otherwise graphics-free base render.

Most graphics are true post-base overlays. Two current behaviors are not:

* long-form rails synthesize ``role="recompose"`` punch windows before the
  base is encoded; and
* legacy captions are burned into the base, so takeover/suppression windows
  must remove their cues before that encode.

Keeping this projection separate preserves fast graphics-only edits while
preventing unsafe base reuse for those cross-lane cases.
"""
from __future__ import annotations

import json
from typing import Any


def legacy_caption_suppression_windows(
    plan: dict[str, Any],
) -> list[tuple[float, float]]:
    """Return sorted legacy-caption suppression windows from graphics."""
    windows = []
    for row in plan.get("graphicsTrack") or []:
        if not isinstance(row, dict):
            continue
        suppress = (
            row.get("anchor", "free-band") == "own-screen"
            or row.get("suppressCaptions") is True
        )
        if suppress:
            windows.append((float(row["outStart"]), float(row["outEnd"])))
    return sorted(windows)


def _recompose_effect(row: dict[str, Any]) -> dict[str, Any] | None:
    """Return only fields consumed while synthesizing a base punch window."""
    from motion.recompose import requires_recompose

    declared = isinstance(row.get("recompose"), dict)
    if not declared and not requires_recompose(row):
        return None
    spec = row.get("spec") if isinstance(row.get("spec"), dict) else {}
    return {
        "kind": row.get("kind"),
        "anchor": row.get("anchor", "free-band"),
        "outStart": row.get("outStart"),
        "outEnd": row.get("outEnd"),
        "recompose": row.get("recompose"),
        "faceBBoxNorm": row.get("faceBBoxNorm"),
        "specSide": spec.get("side"),
    }


def _canonical_sort(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Make irrelevant graphics insertion/order unable to dirty the base."""
    return sorted(
        rows,
        key=lambda row: json.dumps(
            row, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        ),
    )


def _recompose_effects(plan: dict[str, Any]) -> list[dict[str, Any]]:
    effects = []
    for row in plan.get("graphicsTrack") or []:
        if not isinstance(row, dict):
            continue
        effect = _recompose_effect(row)
        if effect is not None:
            effects.append(effect)
    return effects


def graphics_base_effect_projection(plan: dict[str, Any]) -> dict[str, Any]:
    """Compile the exact graphics subset capable of changing base bytes."""
    suppression = [
        {"outStart": start, "outEnd": end}
        for start, end in legacy_caption_suppression_windows(plan)
    ]
    mode = (plan.get("target") or {}).get("mode")
    recompositions = _recompose_effects(plan) if mode == "longform" else []
    return {
        "legacyCaptionSuppression": suppression,
        "longformRecompose": _canonical_sort(recompositions),
    }
