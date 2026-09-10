#!/usr/bin/env python3
"""Per-kind slot contracts for the catalog data/hook/screen family.

Catalog port wave B (2026-08-28): ``chart-story``, ``count-up``,
``line-swap``, ``ui-focus-zoom``.  A chart that silently re-shapes bad data,
a counter that never moves, a swap line that overflows its card, or a camera
punch-in with no screenshot is a planning defect, not a template default to
fall through to.  Same fail-closed doctrine and wiring pattern as
``template_hw_contract``; called from ``template_contract.entry_errors``.

``ui-focus-zoom``'s screenshot is a VARIABLE-REFERENCED ASSET: ``spec.image``
is a motion-web-root-relative selector under ``templates/motion/assets/``.
``image_asset_rows`` resolves it (keyed on the declared ``image`` variable, so
kind-less callers like the sealed-snapshot path see it too) and
``template_contract.resolved_assets`` returns the row, which makes the render
cache hash the image bytes and the sealed archive carry them.
"""
from __future__ import annotations

import os
from typing import Any

from graphics.glyph_metrics import INTER_600, text_width_px
from graphics.template_hw_contract import _num, _text, word_boundary_match

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PIPELINE_ROOT = os.environ.get(
    "SNIPER_PIPELINE_ROOT",
    os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", "..")))
MOTION_DIR = os.path.join(PIPELINE_ROOT, "templates", "motion")

CATALOG_KINDS = ("chart-story", "count-up", "line-swap", "ui-focus-zoom")
_CHART_TYPES = ("bars", "line", "donut", "progress")
_DATA_RANGE = (2, 8)
_DATA_BOUND = 1e9             # a readable axis, not scientific notation
_UNIT_MAX_CHARS = 8           # the value lockups budget a short suffix
_LINE_MAX_CHARS = 48          # legibility floor of the nowrap fit (30px)
_LINE_MASK_PX = 758.0         # the overflow-hidden mask width
_HOUSE_LS_EM = -0.02          # the card lines' letter-spacing
_COUNT_BOUND = 1e9            # a readable figure, not scientific notation
_ZOOM_RANGE = (1.05, 3.0)     # < 1.05 is a no-op "punch-in"
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")
# The comp parses tokens with JS Number(); Python float() is WIDER (it takes
# "1_2" underscores and unicode digits), so a gate-green plan could crash the
# render (review F5). Only this charset reaches float().
_NUMERIC_CHARS = frozenset("0123456789+-.eE")


def _chart_data(spec: dict) -> tuple[list[float] | None, list[str]]:
    """Parse spec.data into finite values, or explain why it is rejected."""
    raw = spec.get("data")
    if not isinstance(raw, str) or not raw.strip():
        return None, ["chart-story requires explicit non-empty spec.data; "
                      "the template's demo series is not planned content"]
    tokens = [token.strip() for token in raw.split(",")]
    values = []
    for token in tokens:
        if not token or not set(token) <= _NUMERIC_CHARS:
            return None, [f"spec.data token {token!r} is not a number"]
        try:
            values.append(float(token))
        except ValueError:
            return None, [f"spec.data token {token!r} is not a number"]
    low, high = _DATA_RANGE
    if not low <= len(values) <= high:
        return None, [f"spec.data needs {low}..{high} values, got {len(values)}"]
    if any(value != value or value in (float("inf"), float("-inf"))
           or value < 0 for value in values):
        return None, ["spec.data values must be finite and >= 0"]
    if max(values) <= 0:
        return None, ["spec.data must contain at least one value > 0"]
    if max(values) > _DATA_BOUND:
        return None, [f"spec.data values must stay within {_DATA_BOUND:.0e} — "
                      "a chart axis is a readable figure, not notation"]
    return values, []


def _chart_errors(spec: dict) -> list[str]:
    """The chart form and every landed value are explicit editorial intent."""
    errors = []
    if spec.get("type") not in _CHART_TYPES:
        errors.append("chart-story requires explicit spec.type "
                      "(bars|line|donut|progress); the chart form follows the "
                      "beat's information shape, not a template default")
    values, data_errors = _chart_data(spec)
    errors.extend(data_errors)
    labels = spec.get("labels")
    if not isinstance(labels, str):
        errors.append("chart-story requires explicit spec.labels (one "
                      "comma-separated slot per datum; a slot may be blank)")
    elif values is not None and len(labels.split(",")) != len(values):
        errors.append(f"spec.labels has {len(labels.split(','))} slot(s) for "
                      f"{len(values)} data value(s); they must pair 1:1")
    emphasize = _num(spec.get("emphasize"))
    if emphasize is None or emphasize != int(emphasize):
        errors.append("chart-story requires explicit integer spec.emphasize — "
                      "the emphasized datum is the editorial point")
    elif values is not None and not 0 <= emphasize <= len(values) - 1:
        errors.append(f"spec.emphasize {int(emphasize)} is outside the data "
                      f"range [0,{len(values) - 1}]")
    unit = spec.get("unit")
    if isinstance(unit, str) and len(unit) > _UNIT_MAX_CHARS:
        errors.append(f"spec.unit is {len(unit)} characters; the value "
                      f"lockups budget at most {_UNIT_MAX_CHARS} — a unit is "
                      "a suffix, not a caption")
    return errors


def _count_errors(spec: dict) -> list[str]:
    """The landed number is the content: explicit, integer, and moving."""
    errors = []
    end = _num(spec.get("end"))
    if end is None:
        errors.append("count-up requires explicit finite spec.end — the "
                      "landed number IS the graphic")
    elif abs(end) > _COUNT_BOUND:
        errors.append(f"spec.end must stay within +-{_COUNT_BOUND:.0e}")
    elif end != int(end):
        errors.append(f"spec.end {end:g} must be an integer — the comp "
                      "rounds every painted row, so a fractional end lands "
                      "a number no gate ever saw")
    start = _num(spec.get("start", 0))
    if start is None or abs(start) > _COUNT_BOUND:
        errors.append(f"spec.start must be a finite number within "
                      f"+-{_COUNT_BOUND:.0e}")
    elif start != int(start):
        errors.append(f"spec.start {start:g} must be an integer — the "
                      "painted rows are integers")
    elif end is not None and round(start) == round(end):
        errors.append("spec.start and spec.end must differ as integers — a "
                      "zero-motion counter is a static stat (use stat-card)")
    return errors


def _swap_errors(spec: dict) -> list[str]:
    """Both lines are required and must fit the nowrap card."""
    errors = []
    lines = {}
    for key in ("lineA", "lineB"):
        line = _text(spec.get(key))
        if not line:
            errors.append(f"line-swap requires explicit non-empty spec.{key}; "
                          "the template's demo copy is not planned content")
            continue
        lines[key] = line
        if len(line) > _LINE_MAX_CHARS:
            errors.append(f"spec.{key} is {len(line)} characters; the nowrap "
                          f"fit overflows the card past {_LINE_MAX_CHARS}")
    errors.extend(_swap_fit_errors(lines))
    word = _text(spec.get("underlineWord"))
    if word and "lineB" in lines \
            and not word_boundary_match(word, lines["lineB"]):
        errors.append(f"spec.underlineWord {word!r} does not appear in "
                      "spec.lineB as a whole word/phrase (case-insensitive "
                      "boundary match — a mid-word hit underlines the "
                      "wrong ink)")
    swap_at = _num(spec.get("swapAt", 0))
    if swap_at is None or swap_at < 0:
        errors.append("spec.swapAt must be a number >= 0")
    return errors


def _swap_fit_errors(lines: dict[str, str]) -> list[str]:
    """Glyph-width fit against the 758px mask (a char count assumes average
    glyphs; "W" x 40 passed the count and clipped half the line — review F3)."""
    if not lines:
        return []
    chars = max(len(line) for line in lines.values())
    fitted = max(30, min(84, int(1440 / max(1, chars) + 0.5)))
    errors = []
    for key, line in sorted(lines.items()):
        width = text_width_px(line, INTER_600, fitted, _HOUSE_LS_EM)
        if width > _LINE_MASK_PX:
            errors.append(
                f"spec.{key} paints ~{width:.0f}px at the {fitted}px fit — "
                f"wider than the {_LINE_MASK_PX:.0f}px overflow-hidden mask "
                "(glyph-width table, not a char count); shorten the line")
    return errors


def _resolve_image(value: str) -> str | None:
    """Resolve a motion-web-root-relative ``assets/<file>`` image selector
    (path rules only — content is ``_image_bytes_match``'s check)."""
    raw = value.strip()
    if (not raw or raw != value or any(char in raw for char in "?#%\\")
            or any(ord(char) < 32 for char in raw)):
        return None
    parts = raw.split("/")
    if parts[0] != "assets" or len(parts) < 2 \
            or any(part in ("", ".", "..") for part in parts):
        return None
    if os.path.splitext(raw)[1].lower() not in _IMAGE_EXTS:
        return None
    root = os.path.realpath(MOTION_DIR)
    lexical = os.path.join(root, raw)
    candidate = os.path.realpath(lexical)
    try:
        inside = os.path.commonpath((root, candidate)) == root
    except ValueError:
        return None
    return candidate if inside and candidate == lexical \
        and os.path.isfile(candidate) else None


def _image_bytes_match(path: str) -> bool:
    """The file's magic bytes must match its extension — any other bytes
    silently degrade the render to the skeleton with every gate green
    (review F7: a text file named .png passed the resolver)."""
    ext = os.path.splitext(path)[1].lower()
    try:
        with open(path, "rb") as handle:
            head = handle.read(12)
    except OSError:
        return False
    if ext == ".png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if ext in (".jpg", ".jpeg"):
        return head.startswith(b"\xff\xd8\xff")
    return head[:4] == b"RIFF" and head[8:12] == b"WEBP"  # .webp


def _image_path(value: str) -> str | None:
    """A selector that resolves AND holds real image bytes; else None."""
    path = _resolve_image(value)
    if path is None or not _image_bytes_match(path):
        return None
    return path


def _focus_zoom_errors(spec: dict) -> list[str]:
    """The screenshot IS the cutaway; the anchor and move must be real."""
    errors = []
    image = spec.get("image")
    if not isinstance(image, str) or not image.strip():
        errors.append("ui-focus-zoom requires explicit spec.image — the "
                      "screenshot IS the cutaway; the skeleton is a preview "
                      "sample, not planned content")
    elif _resolve_image(image) is None:
        errors.append(f"spec.image {image!r} does not resolve to an image "
                      "under templates/motion/assets (motion-web-root-"
                      "relative 'assets/<file>', png/jpg/jpeg/webp)")
    elif not _image_bytes_match(_resolve_image(image)):
        errors.append(f"spec.image {image!r} content does not match its "
                      "extension (magic-byte check: PNG/JPEG/WebP signature "
                      "required) — the browser would silently fall back to "
                      "the skeleton instead of the planned screenshot")
    for key in ("anchorX", "anchorY"):
        anchor = _num(spec.get(key, 50))
        if anchor is None or not 0 <= anchor <= 100:
            errors.append(f"spec.{key} must be a percent in [0,100]")
    zoom = _num(spec.get("zoom", 1.6))
    low, high = _ZOOM_RANGE
    if zoom is None or not low <= zoom <= high:
        errors.append(f"spec.zoom must be in [{low},{high}] — below {low} "
                      "the camera move is a no-op")
    zoom_at = _num(spec.get("zoomAt", 0))
    if zoom_at is None or zoom_at < 0:
        errors.append("spec.zoomAt must be a number >= 0")
    return errors


# Kinds whose contract demands PAINTED NUMBERS (chart data, a landed count).
# claims_contract owes every painted number to the card's spoken window, so
# these kinds are only feasible for a beat that actually speaks a number;
# intro_semantic_contract drops them from number-free beats (run #4, 2026-09-06:
# template_usage demanded chart-story for a beat that speaks no number).
SPOKEN_NUMBER_KINDS = frozenset({"chart-story", "count-up"})

_ERRORS_BY_KIND = {
    "chart-story": _chart_errors,
    "count-up": _count_errors,
    "line-swap": _swap_errors,
    "ui-focus-zoom": _focus_zoom_errors,
}


def catalog_entry_errors(entry: dict) -> list[str]:
    """Slot errors for one planned catalog-family graphic; [] otherwise."""
    check = _ERRORS_BY_KIND.get(str(entry.get("kind", "")))
    if check is None:
        return []
    spec = entry.get("spec")
    if not isinstance(spec, dict):
        return ["spec must be an object"]
    return check(spec)


def image_asset_rows(spec: dict, declared: dict[str, dict]) -> list[dict]:
    """Resolved ``image``-slot asset rows (same shape as icon selector rows).

    Keyed on the DECLARED variable, not the kind, so kind-less callers
    (``container_io._asset_sources``) resolve the screenshot too.
    """
    row = declared.get("image")
    value = spec.get("image")
    if row is None or row.get("type") != "string" \
            or not isinstance(value, str):
        return []
    path = _image_path(value)
    if path is None:
        return []
    return [{"field": "image", "selector": value, "path": path}]
