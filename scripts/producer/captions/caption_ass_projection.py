#!/usr/bin/env python3
"""Render one CaptionTrackV1 compilation as a deterministic ASS projection."""
from __future__ import annotations

import copy
from fractions import Fraction

from captions.caption_contract import CaptionContractError
from captions.captions_ass import (
    _document,
    _escape_ass,
    _wrap_indices,
    ass_color,
)
from captions.caption_outputs import display_separator

_PLACEMENT = {
    "bottom-center": (2, 0.70),
    "lower-third": (2, 0.76),
    "center": (5, 0.50),
    "top-center": (8, 0.20),
}


def _seconds(frame: int, rate: Fraction) -> float:
    return float(Fraction(frame * rate.denominator, rate.numerator))


def _frame_time(frame: int, rate: Fraction) -> str:
    """ASS centiseconds chosen inside the frame boundary at released <=100fps."""
    value = Fraction(frame * 100 * rate.denominator, rate.numerator)
    centiseconds = max(0, value.numerator // value.denominator)
    hours, centiseconds = divmod(centiseconds, 360_000)
    minutes, centiseconds = divmod(centiseconds, 6_000)
    seconds, centiseconds = divmod(centiseconds, 100)
    return (
        f"{hours}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"
    )


def _color(value: object, fallback: str) -> str:
    candidate = value if isinstance(value, str) else fallback
    try:
        return ass_color(candidate)
    except ValueError as exc:
        raise CaptionContractError(str(exc)) from exc


def _integer(value: object, fallback: int, label: str) -> int:
    candidate = fallback if value is None else value
    if isinstance(candidate, bool) or not isinstance(candidate, int) \
            or candidate < 0:
        raise CaptionContractError(f"caption style {label} is invalid")
    return candidate


def _style_name(index: int) -> str:
    return f"Caption{index:03d}"


def _style_line(index: int, cue: dict, style: dict,
                destination: dict) -> str:
    name = _style_name(index)
    font = style.get("font", "Inter")
    if not isinstance(font, str) or not font.strip() or "," in font:
        raise CaptionContractError("caption style font is invalid")
    size = _integer(style.get("size"), 64, "size")
    outline = _integer(style.get("outlinePx"), 4, "outlinePx")
    fill = _color(style.get("fill"), "#ffffff")
    active = _color(style.get("activeFill"), "#ffe34f")
    backing = _color(style.get("outline"), "#000000")
    alignment, baseline = _PLACEMENT[cue["placement"]]
    safe = destination["safeZones"]
    height = destination["height"]
    margin_v = max(safe["top"], min(
        height - safe["bottom"], round(height * baseline)))
    if alignment == 2:
        margin_v = height - margin_v
    elif alignment == 8:
        margin_v = round(height * baseline)
    return (
        f"Style: {name},{font},{size},{fill},{active},{backing},&H00000000,"
        f"-1,0,0,0,100,100,0,0,1,{outline},0,{alignment},"
        f"{safe['left']},{safe['right']},{margin_v},1"
    )


def _texts(cue: dict) -> list[str]:
    rows = cue.get("tokens")
    if not isinstance(rows, list) or not rows:
        raise CaptionContractError("compiled caption cue has no tokens")
    result = [str(row.get("text", "")).strip() for row in rows]
    if any(not text for text in result):
        raise CaptionContractError("compiled caption token is empty")
    return result


def _line_text(cue: dict, style: dict) -> str:
    texts = _texts(cue)
    maximum = _integer(style.get("maxCharsPerLine"), 32, "maxCharsPerLine")
    if maximum < 1:
        raise CaptionContractError("caption maxCharsPerLine must be positive")
    lines = _wrap_indices(texts, maximum)
    return "\\N".join(
        "".join(
            display_separator(texts[index], offset > 0, cue.get("language"))
            + _escape_ass(texts[index])
            for offset, index in enumerate(line)
        )
        for line in lines)


def _karaoke_text(cue: dict, style: dict, rate: Fraction) -> str:
    """Preserve the existing phrase-mode projection; not current-word semantics."""
    duration = max(1, round(_seconds(
        cue["endFrameExclusive"] - cue["startFrame"], rate) * 100))
    return f"{{\\k{duration}}}{_line_text(cue, style)}"


def _word_text(cue: dict, style: dict, frame: int) -> str:
    """Keep complete shaping/wrapping; color only tokens active on this frame."""
    texts = _texts(cue)
    maximum = _integer(style.get("maxCharsPerLine"), 32, "maxCharsPerLine")
    if maximum < 1:
        raise CaptionContractError("caption maxCharsPerLine must be positive")
    fill = _color(style.get("fill"), "#ffffff")
    active = _color(style.get("activeFill"), "#ffe34f")
    colors = [active if token["startFrame"] <= frame
              < token["endFrameExclusive"] else fill for token in cue["tokens"]]
    lines = _wrap_indices(texts, maximum)
    return "\\N".join("".join(
        display_separator(texts[index], offset > 0, cue.get("language"))
        + f"{{\\1c{colors[index]}&}}{_escape_ass(texts[index])}"
        for offset, index in enumerate(line)) for line in lines)


def _event(index: int, cue: dict, rate: Fraction, text: str) -> str:
    """Emit one half-open interval using the original rational frame quantizer."""
    start = _frame_time(cue["startFrame"], rate)
    end = _frame_time(cue["endFrameExclusive"], rate)
    return (
        f"Dialogue: 0,{start},{end},{_style_name(index)},"
        f"{cue['cueId']},0,0,0,,{text}"
    )


def _events(index: int, cue: dict, style: dict, rate: Fraction) -> list[str]:
    """Split word highlighting only at original starts/ends; gaps remain fill."""
    if cue["mode"] != "karaoke-word":
        text = (_line_text(cue, style) if cue["mode"] == "line"
                else _karaoke_text(cue, style, rate))
        return [_event(index, cue, rate, text)]
    start, end = cue["startFrame"], cue["endFrameExclusive"]
    boundaries = sorted({start, end} | {
        value for token in cue["tokens"]
        for value in (token["startFrame"], token["endFrameExclusive"])
        if start < value < end})
    return [_event(index, {**cue, "startFrame": first, "endFrameExclusive": last},
                   rate, _word_text(cue, style, first))
            for first, last in zip(boundaries, boundaries[1:])]


def build_compiled_ass(compilation: dict,
                       styles: dict[str, dict]) -> str:
    """Build ASS from the exact cues used by SRT and Palmier projections."""
    fps = compilation.get("fps") or {}
    try:
        rate = Fraction(int(fps["numerator"]), int(fps["denominator"]))
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise CaptionContractError("caption compilation fps is malformed") from exc
    if rate > 100:
        raise CaptionContractError(
            "ASS compatibility projection cannot prove frame boundaries above 100fps")
    destination = compilation.get("destination")
    if not isinstance(destination, dict):
        raise CaptionContractError("caption compilation destination is missing")
    cues = compilation.get("cues")
    if not isinstance(cues, list):
        raise CaptionContractError("caption compilation cues are malformed")
    style_rows, events = [], []
    for index, cue in enumerate(cues):
        style = styles.get(cue.get("styleId"))
        if not isinstance(style, dict):
            raise CaptionContractError(
                f"caption style {cue.get('styleId')!r} is unavailable")
        style_rows.append(_style_line(index, cue, style, destination))
        events.extend(_events(index, cue, style, rate))
    canvas = {
        "width": destination["width"], "height": destination["height"],
    }
    return _document(style_rows, events, canvas)


def build_local_cue_ass(compilation: dict, cue: dict,
                        styles: dict[str, dict]) -> str:
    """Build one cue on a zero-based clock for an independent alpha shard."""
    start = cue.get("startFrame")
    end = cue.get("endFrameExclusive")
    if not isinstance(start, int) or not isinstance(end, int) or end <= start:
        raise CaptionContractError("compiled caption cue frame range is invalid")
    local = copy.deepcopy(cue)
    local["startFrame"] = 0
    local["endFrameExclusive"] = end - start
    for token in local.get("tokens") or []:
        token["startFrame"] -= start
        token["endFrameExclusive"] -= start
    isolated = {
        "fps": copy.deepcopy(compilation.get("fps")),
        "destination": copy.deepcopy(compilation.get("destination")),
        "cues": [local],
    }
    return build_compiled_ass(isolated, styles)
