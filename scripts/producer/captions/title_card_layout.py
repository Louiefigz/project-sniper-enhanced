"""Aspect-aware title-card layout derived from the authored portrait grid."""
from __future__ import annotations

from dataclasses import dataclass

from producer_config import (
    CANVAS, HOOK_CARD, SAFE_BOX, VISUAL_CENTER_X,
)


@dataclass(frozen=True)
class CardLayout:
    """Canvas-relative title-card geometry."""

    width: int
    height: int
    safe: dict
    visual_center_x: int
    y_range: tuple[int, int]
    font_range: tuple[int, int]
    padding: int
    radius: int


def layout_for_canvas(width: int, height: int) -> CardLayout:
    """Scale the authored portrait safe geometry to a delivery canvas."""
    if width <= 0 or height <= 0:
        raise ValueError("title-card canvas must be positive")
    sx, sy = width / CANVAS["width"], height / CANVAS["height"]
    scale = min(sx, sy)
    style = HOOK_CARD["style"]
    safe = {
        "left": round(SAFE_BOX["left"] * sx),
        "right": round(SAFE_BOX["right"] * sx),
        "top": round(SAFE_BOX["top"] * sy),
        "bottom": round(SAFE_BOX["bottom"] * sy),
    }
    authored_fonts = style["font_size_range"]
    fonts = (max(1, round(authored_fonts[0] * scale)),
             max(1, round(authored_fonts[1] * scale)))
    authored_y = HOOK_CARD["y_range"]
    return CardLayout(
        width, height, safe, round(VISUAL_CENTER_X * sx),
        (round(authored_y[0] * sy), round(authored_y[1] * sy)), fonts,
        max(1, round(style["padding"] * scale)),
        max(1, round(style["corner_radius"] * scale)))
