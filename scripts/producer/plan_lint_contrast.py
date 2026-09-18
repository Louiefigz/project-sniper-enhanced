"""Existing LL-004 arithmetic plus exact source-bound local text plate checks."""
from __future__ import annotations

from typing import Any

from graphics.template_text_contrast import (
    effective_text_roles, text_plate_contract, text_treatment,
)
from producer_config import MOTION


def _srgb_channel(v: int) -> float:
    c = v / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _hex_rgb(color: str) -> tuple[int, int, int] | None:
    s = str(color).strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) != 6 or any(ch not in "0123456789abcdefABCDEF" for ch in s):
        return None
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def luminance(color: str) -> float | None:
    """WCAG relative luminance of a hex color, never a guessed named color."""
    rgb = _hex_rgb(color)
    if rgb is None:
        return None
    r, g, b = (_srgb_channel(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg: str, bg: str) -> float | None:
    """WCAG contrast ratio between two hex colors (None if unparseable)."""
    lf, lb = luminance(fg), luminance(bg)
    if lf is None or lb is None:
        return None
    return (max(lf, lb) + 0.05) / (min(lf, lb) + 0.05)


def _plate_check(index: int, graphic: dict, rep: Any) -> bool:
    """Return whether this kind has an explicit plate/legacy contrast result."""
    try:
        contract = text_plate_contract(str(graphic.get("kind", "")))
        if contract is None:
            return False
        if text_treatment(graphic, contract) == "scrim":
            rep.warn(f"graphicsTrack[{index}]: section-marker legacy scrim contrast "
                     "is unmeasured: translucent footage-dependent backing; "
                     "use explicit readability='plates' for checked text roles")
            return True
        roles = effective_text_roles(graphic, contract)
        if not roles:
            raise ValueError("no intended text roles to measure")
        for role in roles:
            ratio = contrast_ratio(role["foreground"], role["background"])
            if ratio is None or ratio < MOTION["contrast"]["min_ratio"]:
                rep.error(f"graphicsTrack[{index}]: {role['id']} foreground "
                          f"{role['foreground']} on qualified plate {role['background']} "
                          f"is {ratio:.2f}:1 — below the {MOTION['contrast']['min_ratio']:g}:1 "
                          "large-text floor; preserve intent and choose a reviewed color")
    except (OSError, ValueError, KeyError) as error:
        rep.error(f"graphicsTrack[{index}]: text contrast evidence unavailable: {error}")
    return True


def check_contrast(plan: dict, rep: Any) -> None:
    """LL-004 known backgrounds only; explicit source-bound roles or legacy warning."""
    cfg = MOTION["contrast"]
    floor = float(cfg["min_ratio"])
    for i, g in enumerate(plan.get("graphicsTrack") or []):
        if _plate_check(i, g, rep):
            continue
        bg_by_variant = cfg["kind_bg"].get(str(g.get("kind", "")))
        if bg_by_variant is None:
            continue
        spec = g.get("spec") or {}
        bg = bg_by_variant.get(str(spec.get("bg", "")))
        if bg is None:
            continue
        for key in ("accent", "accentColor"):
            if key not in spec:
                continue
            ratio = contrast_ratio(str(spec[key]), bg)
            if ratio is not None and ratio < floor:
                rep.error(
                    f"graphicsTrack[{i}]: spec.{key} {spec[key]!r} on the "
                    f"{g.get('kind')} bg {bg} is {ratio:.1f}:1 — below the "
                    f"{floor:g}:1 large-text floor (LL-004: pick a brighter "
                    "accent for dark cards / darker for light cards)")
