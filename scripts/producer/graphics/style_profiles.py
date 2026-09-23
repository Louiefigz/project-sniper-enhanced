#!/usr/bin/env python3
"""Historical profile readers; global creator-style execution is retired."""
from __future__ import annotations

from typing import Any

from graphics.visual_source_policy import target_source_errors

FACE_BRIDGE_PROFILE = "module-editorial-v1"

# Data catalog: information form -> executable renderer contract.  Several
# forms intentionally share one modular renderer kind.  Variety lives in the
# information anatomy (contentMode/grid), not in duplicating HTML chassis.
STYLE_PROFILES: dict[str, dict[str, Any]] = {}


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
    """Reject retired global reference grammars at their old entry point."""
    return target_source_errors(target)



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
