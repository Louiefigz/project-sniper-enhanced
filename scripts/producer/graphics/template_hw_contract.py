#!/usr/bin/env python3
"""Per-kind slot contracts for the hand-drawn (hw) annotation family.

Catalog port wave A (2026-08-28): ``marker-highlight``, ``hw-callout-circle``,
``hw-scribble-transition``. These comps draw over live footage, so a spec that
silently renders nothing (an emphasis word absent from its line, a callout
region off the canvas) is a planning defect, not a template default to fall
through to.  Same fail-closed doctrine and wiring pattern as
``template_contract.statement_card_errors``; called from ``entry_errors``.
"""
from __future__ import annotations

import math
from typing import Any

from graphics.glyph_metrics import CAVEAT_700, INTER_600, text_width_px

HW_KINDS = ("marker-highlight", "hw-callout-circle", "hw-scribble-transition")
# Authored canvas of the annotation comps (matches their data-width/height).
_CANVAS = (1080, 1920)
_BANDS_RANGE = (3, 18)
_STROKE_SCALE_RANGE = (0.5, 2.0)
# marker-highlight panel: 870px safe-width minus 2x56 padding; Inter-600 at
# the comp's char-count fit (1610/chars clamped [38,84]) with -0.02em spacing.
_PANEL_CONTENT_PX = 758.0
_HOUSE_LS_EM = -0.02


def _text(value: Any) -> str | None:
    """Whitespace-normalized string, or None for a non-string."""
    if not isinstance(value, str):
        return None
    return " ".join(value.split())


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def word_boundary_match(phrase: str, text: str) -> bool:
    """True when ``phrase`` matches inside ``text`` at WORD boundaries.

    A bare substring match circles the wrong ink: "art" first matches inside
    "Start", so the marker lands mid-word (review 2026-08-28). Boundary =
    the chars around the match are absent or non-alphanumeric — pure
    membership arithmetic, mirrored by the comps' boundaryIndexOf.
    """
    low_text, low_phrase = text.lower(), phrase.lower()
    start = low_text.find(low_phrase)
    while start >= 0:
        end = start + len(low_phrase)
        before_ok = start == 0 or not low_text[start - 1].isalnum()
        after_ok = end >= len(low_text) or not low_text[end].isalnum()
        if before_ok and after_ok:
            return True
        start = low_text.find(low_phrase, start + 1)
    return False


def _marker_fit_errors(text: str, word: str) -> list[str]:
    """Width-table fit against the panel: the emphasis span never wraps."""
    chars = max(1, len(text))
    fitted = max(38, min(84, int(1610 / chars + 0.5)))
    checks = [("emphasisWord", word)]
    longest = max(text.split(), key=len, default="")
    if longest and longest.lower() not in word.lower():
        checks.append(("text's longest word", longest))
    errors = []
    for slot, line in checks:
        width = text_width_px(line, INTER_600, fitted, _HOUSE_LS_EM)
        if width > _PANEL_CONTENT_PX:
            errors.append(
                f"spec.{slot} {line!r} paints ~{width:.0f}px at the "
                f"{fitted}px fit — wider than the {_PANEL_CONTENT_PX:.0f}px "
                "nowrap panel content box (glyph-width table, not a char "
                "count); shorten the phrase or emphasize fewer words")
    return errors


def _marker_errors(spec: dict) -> list[str]:
    """The marker IS the graphic: line + matched emphasis word are required."""
    errors = []
    text = _text(spec.get("text"))
    if not text:
        errors.append("marker-highlight requires explicit non-empty spec.text; "
                      "the template's demo default is not planned content")
    word = _text(spec.get("emphasisWord"))
    if not word:
        errors.append("marker-highlight requires explicit non-empty "
                      "spec.emphasisWord — a line with no marker is a "
                      "statement, not an emphasis annotation")
    elif text and not word_boundary_match(word, text):
        errors.append(f"spec.emphasisWord {word!r} does not appear in "
                      "spec.text as a whole word/phrase (case-insensitive "
                      "boundary match — a mid-word hit marks the wrong ink)")
    elif text:
        errors.extend(_marker_fit_errors(text, word))
    drawn = _num(spec.get("drawAt", 0))
    if drawn is None or drawn < 0:
        errors.append("spec.drawAt must be a number >= 0")
    return errors


def _callout_errors(spec: dict) -> list[str]:
    """A default region is a mis-annotation: the box is required, on-canvas."""
    errors = []
    missing = [key for key in ("x", "y", "w", "h") if key not in spec]
    if missing:
        errors.append("hw-callout-circle requires an explicit region — "
                      "missing " + ", ".join(f"spec.{key}" for key in missing))
    box = {key: _num(spec[key]) for key in ("x", "y", "w", "h")
           if key in spec}
    bad = [key for key, value in box.items() if value is None]
    if bad:
        errors.append("region values must be finite numbers: " +
                      ", ".join(f"spec.{key}" for key in bad))
    if not missing and not bad:
        if box["w"] <= 0 or box["h"] <= 0:
            errors.append("spec.w and spec.h must be > 0")
        elif not (0 <= box["x"] and box["x"] + box["w"] <= _CANVAS[0]
                  and 0 <= box["y"] and box["y"] + box["h"] <= _CANVAS[1]):
            errors.append("region must sit inside the "
                          f"{_CANVAS[0]}x{_CANVAS[1]} canvas; got "
                          f"x={box['x']:g} y={box['y']:g} "
                          f"w={box['w']:g} h={box['h']:g}")
        else:
            errors.extend(_callout_margin_errors(box))
            errors.extend(_callout_label_errors(spec, box))
    drawn = _num(spec.get("drawAt", 0))
    if drawn is None or drawn < 0:
        errors.append("spec.drawAt must be a number >= 0")
    return errors


# Ellipse clearance mirror: the outline draws _ELLIPSE_PAD px outside the
# region, wobbled up to 4%, with a 10px stroke — a region flush against the
# canvas edge clips its own ink.
_ELLIPSE_PAD = 26.0
_STROKE_HALF = 5.0
_WOBBLE_PCT = 0.04


def _callout_margin_errors(box: dict) -> list[str]:
    """The wobbled ellipse stroke must stay on the canvas."""
    margin_x = _ELLIPSE_PAD + _STROKE_HALF \
        + _WOBBLE_PCT * (box["w"] / 2 + _ELLIPSE_PAD)
    margin_y = _ELLIPSE_PAD + _STROKE_HALF \
        + _WOBBLE_PCT * (box["h"] / 2 + _ELLIPSE_PAD)
    if box["x"] < margin_x or box["x"] + box["w"] > _CANVAS[0] - margin_x \
            or box["y"] < margin_y or box["y"] + box["h"] > _CANVAS[1] - margin_y:
        return [f"region must keep ~{margin_x:.0f}px horizontal / "
                f"~{margin_y:.0f}px vertical clearance from the canvas edge — "
                "the ellipse draws 26px outside the region plus wobble and "
                "stroke, and a flush region clips its own ink"]
    return []


# Label geometry mirror of the comp's connector arithmetic (proven defect:
# labelAt "right" beside a wide region ran the label off-canvas on a real
# render). Width = the measured 72px Caveat-700 glyph table, not a char
# average (review F3b: ten "W" glyphs blew a 36px/char estimate by ~350px).
_LABEL_FONT_PX = 72.0
_LABEL_PAD_PX = 20.0
_LABEL_HEIGHT_PX = 90.0


def _callout_label_errors(spec: dict, box: dict) -> list[str]:
    """The connector-anchored label must land fully on the canvas."""
    label = spec.get("label")
    if not isinstance(label, str) or not label.strip():
        return []                       # explicit blank = circle-only intent
    side = spec.get("labelAt", "right")
    if side not in ("right", "left", "below"):
        return []                       # the enum gate reports this one
    cx, cy = box["x"] + box["w"] / 2, box["y"] + box["h"] / 2
    rx, ry = box["w"] / 2 + 26, box["h"] / 2 + 26
    sx = cx - rx if side == "left" else cx if side == "below" else cx + rx
    sy = cy + ry if side == "below" else cy + ry * 0.35
    ex = sx - 70 if side == "left" else sx + 40 if side == "below" else sx + 70
    left = ex - 180 if side == "left" else ex + 12
    top = sy + 55 - 30
    width = _LABEL_PAD_PX + text_width_px(
        label.strip(), CAVEAT_700, _LABEL_FONT_PX)
    if left < 0 or left + width > _CANVAS[0] or top < 0 \
            or top + _LABEL_HEIGHT_PX > _CANVAS[1]:
        return [f"label {label.strip()!r} at labelAt={side!r} lands off the "
                f"{_CANVAS[0]}x{_CANVAS[1]} canvas (estimated box "
                f"[{left:.0f},{top:.0f},{left + width:.0f},"
                f"{top + _LABEL_HEIGHT_PX:.0f}]); shorten the label, move "
                "the region, or pick another labelAt side"]
    return []


def _scribble_errors(spec: dict) -> list[str]:
    """No content copy to leak — bounds only ({} is a legitimate spec)."""
    errors = []
    if "bands" in spec:
        bands = _num(spec["bands"])
        low, high = _BANDS_RANGE
        if bands is None or bands != int(bands) or not low <= bands <= high:
            errors.append(f"spec.bands must be an integer in [{low},{high}]")
    if "strokeScale" in spec:
        scale = _num(spec["strokeScale"])
        low, high = _STROKE_SCALE_RANGE
        if scale is None or not low <= scale <= high:
            errors.append(f"spec.strokeScale must be a number in [{low},{high}]")
    return errors


_ERRORS_BY_KIND = {
    "marker-highlight": _marker_errors,
    "hw-callout-circle": _callout_errors,
    "hw-scribble-transition": _scribble_errors,
}


def hw_entry_errors(entry: dict) -> list[str]:
    """Slot errors for one planned hw-family graphic; [] for other kinds."""
    check = _ERRORS_BY_KIND.get(str(entry.get("kind", "")))
    if check is None:
        return []
    spec = entry.get("spec")
    if not isinstance(spec, dict):
        return ["spec must be an object"]
    return check(spec)
