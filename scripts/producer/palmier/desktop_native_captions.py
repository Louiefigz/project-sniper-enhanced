"""Compile plan caption intent into Palmier's exact native tool vocabulary."""
from __future__ import annotations

import math
from typing import Any

from palmier.mcp_client import PalmierError

MCP_CAPTION_KEYS = {
    "language", "maxWords", "textCase", "fontName", "fontSize", "color",
    "borderColor", "backgroundColor", "highlightColor", "isBold",
    "isItalic", "alignment", "animation", "transform", "censorProfanity",
}
PLAN_META_KEYS = {"burn", "style"}
REQUIRED_KEYS = {
    "language", "maxWords", "textCase", "fontName", "fontSize", "color",
    "borderColor", "highlightColor", "isBold", "isItalic", "alignment",
    "animation", "transform", "censorProfanity",
}
ANIMATIONS = {
    "line": "wordReveal",
    "karaoke": "highlightBlock",
}


def _short(plan: dict) -> bool:
    target = plan.get("target") or {}
    return target.get("mode") == "short" \
        or target.get("aspect") == "9:16"


def _default(style: str, short: bool) -> dict:
    """Use the studied 0.82 short caption band; long stays lower-third."""
    karaoke = style == "karaoke"
    return {
        "language": "en", "maxWords": 4 if karaoke else 7,
        "textCase": "auto", "fontName": "Inter",
        "fontSize": 58 if karaoke else 52,
        "color": "#FFFFFF", "borderColor": "#000000",
        "highlightColor": "#FFD166", "isBold": True, "isItalic": False,
        "alignment": "center", "animation": ANIMATIONS[style],
        "transform": {"centerX": 0.5, "centerY": 0.82 if short else 0.88},
        "censorProfanity": False,
    }


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PalmierError(f"native captions {label} must be numeric")
    number = float(value)
    if number < 0 or number > 1:
        raise PalmierError(f"native captions {label} must be within 0-1")
    return number


def _validate_transform(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != {"centerX", "centerY"}:
        raise PalmierError(
            "native captions transform must contain only centerX/centerY")
    return {"centerX": _number(value["centerX"], "centerX"),
            "centerY": _number(value["centerY"], "centerY")}


def _validate_scalar_settings(settings: dict) -> None:
    strings = {
        "language", "textCase", "fontName", "color", "borderColor",
        "highlightColor", "alignment", "animation",
    }
    if "backgroundColor" in settings:
        strings.add("backgroundColor")
    bad = [key for key in strings
           if not isinstance(settings.get(key), str)
           or not settings[key].strip() or len(settings[key]) > 120]
    if bad:
        raise PalmierError(
            f"native captions string settings are malformed: {sorted(bad)}")
    font_size = settings.get("fontSize")
    if isinstance(font_size, bool) \
            or not isinstance(font_size, (int, float)) \
            or not math.isfinite(float(font_size)) \
            or not 12 <= float(font_size) <= 220:
        raise PalmierError("native captions fontSize must be within 12-220")
    booleans = ("isBold", "isItalic", "censorProfanity")
    if any(not isinstance(settings.get(key), bool) for key in booleans):
        raise PalmierError("native caption flags must be boolean")


def validate_native_caption_settings(value: object) -> dict:
    """Require a complete, schema-exact add_captions argument object."""
    if not isinstance(value, dict):
        raise PalmierError("native captions settings must be an object")
    unknown, missing = set(value) - MCP_CAPTION_KEYS, REQUIRED_KEYS - set(value)
    if unknown or missing:
        raise PalmierError(
            f"native caption schema drift; unknown={sorted(unknown)}, "
            f"missing={sorted(missing)}")
    settings: dict[str, Any] = dict(value)
    settings["transform"] = _validate_transform(settings["transform"])
    _validate_scalar_settings(settings)
    if settings["animation"] not in {
            "off", "fadeIn", "popIn", "slideUp", "typewriter",
            "wordReveal", "wordSlide", "wordPop", "wordCycle",
            "highlightPop", "highlightBlock"}:
        raise PalmierError("native captions animation is unsupported")
    if isinstance(settings["maxWords"], bool) \
            or not isinstance(settings["maxWords"], int) \
            or not 1 <= settings["maxWords"] <= 8:
        raise PalmierError("native captions maxWords must be within 1-8")
    return settings


def native_caption_settings(plan: dict) -> dict:
    """Strip renderer-only keys and map high-level karaoke deterministically."""
    captions = plan.get("captions")
    if not isinstance(captions, dict) or not captions:
        raise PalmierError("native captions require plan caption intent")
    unknown = set(captions) - PLAN_META_KEYS - MCP_CAPTION_KEYS
    if unknown:
        raise PalmierError(
            f"caption plan has no native mapping for {sorted(unknown)}")
    style = captions.get("style", "line")
    if style not in ANIMATIONS:
        raise PalmierError(f"caption style {style!r} has no native mapping")
    settings = _default(str(style), _short(plan))
    settings.update({key: value for key, value in captions.items()
                     if key in MCP_CAPTION_KEYS})
    return validate_native_caption_settings(settings)
