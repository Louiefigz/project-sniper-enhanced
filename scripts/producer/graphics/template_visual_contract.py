#!/usr/bin/env python3
"""Visible-completeness rules for long-form motion templates.

Rendering a valid file is not enough.  A planned window must contain a real
identity where the layout promises one and must remain on screen after its
last content reveal long enough to read before its exit animation begins.
"""
from __future__ import annotations

import math
import os
import re
from typing import Any

_BRAND_COLOR_ASSETS = {
    "openai": "openai-color.svg",
    "claude": "claude-color.svg",
    "gemini": "gemini-color.svg",
}

# kind -> (absolute floor, reveal settle, readable dwell, exit runway)
# Comps that HOLD their final frame by design and exit via a hard clear at a
# cut seam (the enable-window stops the overlay; nothing leaks past outEnd).
# The render proof waives the terminal-clear oracle for these kinds ONLY --
# fade-exit comps keep the strict check (a fade cut short pops off visibly).
HOLD_TO_CUT_KINDS = frozenset({
    "statement-card", "kinetic-quote", "kinetic-quote-wide",
    "nateherk-takeover", "section-takeover", "glass-takeover-bg",
    "angela-takeover-deck", "benchmark-takeover",
})

_TIMING_POLICY = {
    "glass-rail": (3.0, 0.46, 1.25, 0.42),
    "icon-badge-wide": (3.0, 0.16, 1.25, 0.42),
    "statement-card": (2.5, 0.45, 1.25, 0.15),
    "nateherk-rail": (4.0, 0.45, 1.25, 0.0),
    "nateherk-bullet-bars": (4.0, 0.50, 1.25, 0.0),
    "avatar-bio-card": (5.0, 0.70, 1.50, 0.0),
    "whiteboard-connector": (3.0, 0.30, 1.25, 0.42),
    "nateherk-ledger-dark": (4.0, 0.50, 1.25, 0.0),
}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def _series(value: Any) -> list[float]:
    if isinstance(value, (list, tuple)):
        values = list(value)
    elif isinstance(value, str):
        values = [part.strip() for part in re.split(r"[|,]", value)]
    else:
        values = []
    result = []
    for item in values:
        try:
            parsed = float(item)
        except (TypeError, ValueError):
            continue
        if math.isfinite(parsed):
            result.append(parsed)
    return result


def _paired_at_values(spec: dict) -> list[float]:
    values = []
    for key, value in spec.items():
        match = re.fullmatch(r"at(\d+)", str(key))
        parsed = _number(value)
        if match is None or parsed is None:
            continue
        index = match.group(1)
        paired = next((spec.get(f"{prefix}{index}")
                       for prefix in ("icon", "item", "title", "line")
                       if f"{prefix}{index}" in spec), None)
        if paired is None or str(paired).strip():
            values.append(parsed)
    return values


def _latest_reveal(spec: dict) -> float:
    values = _paired_at_values(spec)
    for key in ("rowLands", "moduleLands", "statementLands"):
        values.extend(_series(spec.get(key)))
    if str(spec.get("line2", "")).strip():
        value = _number(spec.get("at3", spec.get("at2")))
        if value is not None:
            values.append(value)
    if str(spec.get("payoff", "")).strip():
        value = _number(spec.get("payoffAt"))
        if value is not None:
            values.append(value)
    return max(values, default=0.0)


def _brand_errors(kind: str, spec: dict) -> list[str]:
    if kind != "icon-badge-wide":
        return []
    errors = []
    for key in ("icon1", "icon2", "icon3"):
        selected = str(spec.get(key, "") or "").strip()
        stem = os.path.splitext(os.path.basename(selected))[0]
        brand = stem.removesuffix("-color")
        required = _BRAND_COLOR_ASSETS.get(brand)
        if required and os.path.basename(selected) != required:
            errors.append(
                f"spec.{key} names {brand} but uses {selected!r}; named brand "
                f"identities require the distinct approved asset {required!r}")
    return errors


def _identity_errors(kind: str, spec: dict) -> list[str]:
    if kind != "avatar-bio-card":
        return []
    avatar = str(spec.get("avatarSrc", "") or "").strip()
    initials = str(spec.get("initials", "") or "").strip()
    if avatar or initials:
        return []
    return ["avatar-bio-card requires explicit spec.avatarSrc or spec.initials; "
            "an empty portrait circle is not a completed credibility graphic"]


def _copy_geometry_errors(kind: str, spec: dict) -> list[str]:
    """Keep credential copy inside the two-line arc-safe text region."""
    if kind != "avatar-bio-card":
        return []
    line2 = " ".join(str(spec.get("line2", "") or "").split())
    if len(line2) <= 64:
        return []
    return ["avatar-bio-card spec.line2 exceeds the 64-character two-line "
            "safe region; shorten the credential or use a text-led template"]


def _timing_errors(entry: dict, kind: str, spec: dict) -> list[str]:
    policy = _TIMING_POLICY.get(kind)
    if policy is None:
        return []
    try:
        hold = float(entry["outEnd"]) - float(entry["outStart"])
    except (KeyError, TypeError, ValueError):
        return []
    floor, settle, dwell, exit_runway = policy
    reveal = _latest_reveal(spec)
    required = max(floor, reveal + settle + dwell + exit_runway)
    if hold + 1e-6 >= required:
        return []
    return [
        f"visible hold {hold:.2f}s is shorter than the {required:.2f}s "
        f"completion floor for {kind} (last reveal {reveal:.2f}s + "
        f"{settle:.2f}s settle + {dwell:.2f}s readable dwell + "
        f"{exit_runway:.2f}s exit runway)"
    ]


def visual_entry_errors(entry: dict) -> list[str]:
    """Return deterministic identity and visible-timing defects."""
    kind = str(entry.get("kind", ""))
    spec = entry.get("spec")
    if not isinstance(spec, dict):
        return []
    return [*_brand_errors(kind, spec), *_identity_errors(kind, spec),
            *_copy_geometry_errors(kind, spec),
            *_timing_errors(entry, kind, spec)]
