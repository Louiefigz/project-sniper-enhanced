#!/usr/bin/env python3
"""Resolved local-asset contract for icon-driven motion templates."""
from __future__ import annotations

import os
import re

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PIPELINE_ROOT = os.environ.get(
    "SNIPER_PIPELINE_ROOT",
    os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", "..")))
ICONS_DIR = os.path.join(PIPELINE_ROOT, "templates", "motion", "icons")

_ICON_KEY = re.compile(r"icon\d*\Z")
_ASSET_ONLY_SLOTS = {
    "icon-badge-wide": ("icon1", "icon2", "icon3"),
    "logo-card": ("iconFile",),
    "stroke-draw-badge": ("icon",),
}


def _is_icon_key(key: str, row: dict) -> bool:
    return row.get("type") == "string" \
        and (key == "iconFile" or _ICON_KEY.fullmatch(key) is not None)


def icon_keys(declared: dict[str, dict]) -> list[str]:
    """Declared icon selectors in source catalog order."""
    return [key for key, row in declared.items() if _is_icon_key(key, row)]


def asset_contract(kind: str, declared: dict[str, dict]) -> dict:
    """Planner-facing explicit-input requirements for asset-only templates."""
    return {"assetOnly": kind in _ASSET_ONLY_SLOTS,
            "selectorVariables": icon_keys(declared),
            "requiredExplicitSelectors": list(_ASSET_ONLY_SLOTS.get(kind, ()))}


def effective_asset_spec(spec: dict, declared: dict[str, dict]) -> dict:
    """Bind omitted declared asset defaults while preserving explicit blanks."""
    keys = icon_keys(declared)
    if declared.get("image", {}).get("type") == "string":
        keys.append("image")
    defaults = {key: declared[key]["default"] for key in keys if "default" in declared[key]}
    return {**defaults, **spec}


def _selector_path(value: str) -> str | None:
    raw = value.strip()
    if (not raw or raw != value or os.path.isabs(raw)
            or ".." in raw.split("/") or any(char in raw for char in "?#%")
            or any(ord(char) < 32 for char in raw)):
        return None
    relative = raw if "." in os.path.basename(raw) else raw + ".svg"
    if os.path.splitext(relative)[1] != ".svg":
        return None
    root = os.path.realpath(ICONS_DIR)
    lexical = os.path.join(root, relative)
    candidate = os.path.realpath(lexical)
    try:
        inside = os.path.commonpath((root, candidate)) == root
    except ValueError:
        return None
    exact = candidate == lexical
    return candidate if inside and exact and os.path.isfile(candidate) else None


def selector_errors(kind: str, spec: dict,
                    declared: dict[str, dict]) -> list[str]:
    """Reject demo defaults, blanks, traversal, and unresolved icon identities."""
    errors: list[str] = []
    required = _ASSET_ONLY_SLOTS.get(kind, ())
    missing = [key for key in required if key not in spec]
    if missing:
        errors.append("asset-only template must explicitly override " +
                      ", ".join(f"spec.{key}" for key in missing))
    selected = []
    effective = effective_asset_spec(spec, declared)
    for key in icon_keys(declared):
        value = effective.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            errors.append(f"spec.{key} must be a string asset selector")
            continue
        if not value.strip():
            continue
        selected.append(key)
        if _selector_path(value) is None:
            errors.append(f"spec.{key} asset {value!r} does not resolve under "
                          "templates/motion/icons")
    if required and not selected:
        errors.append("asset-only template needs at least one non-empty resolved selector")
    return errors


def resolved_selectors(spec: dict, declared: dict[str, dict]) -> list[dict]:
    """Resolved selectors after selector_errors has accepted the entry."""
    rows = []
    for key in icon_keys(declared):
        if key not in spec:
            continue
        value = spec.get(key)
        if not isinstance(value, str):
            raise ValueError(f"spec.{key} must be a string asset selector")
        if not value.strip():
            continue
        path = _selector_path(value) if isinstance(value, str) else None
        if path is None:
            raise ValueError(f"spec.{key} asset {value!r} does not resolve under templates/motion/icons")
        rows.append({"field": key, "selector": value, "path": path})
    return rows
