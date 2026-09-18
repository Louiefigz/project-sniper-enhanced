#!/usr/bin/env python3
"""captions_minimal — the ``minimal`` word-at-a-time caption style (R1/R2).

Split out of ``captions.py`` so each caption module stays within the logic-line
budget (the karaoke/line block grouping and this word-at-a-time path are
distinct responsibilities). Reuses captions' low-level ASS primitives
(``_document``, ``ass_color``, word normalization); ``captions.build_ass``
dispatches here for ``style='minimal'`` via a lazy import (captions imports this
module only at call time, so there is no import cycle).

The style (reference study R1/R2 — docs/studies/REFERENCE_STYLE_STUDY.md, 2026-07-05):
ONE word, or a <=3-word phrase when adjacent words nearly touch, per Dialogue
event; chest-anchored (fixed band, or face-relative when the plan carries
``faceBBoxNorm``); soft drop shadow, no heavy outline box; emphasis words
(``captions.emphasisWords``, case-insensitive) render gold in a serif-italic
accent face as their own events (ASS can't switch font-family cleanly mid-event).
All config lives in ``producer_config.CAPTIONS['MINIMAL']``.
"""

from __future__ import annotations

import re

from producer_config import CANVAS, CAPTIONS, SAFE_BOX, VISUAL_CENTER_X

# Shared ASS primitives from the sibling caption module (no import cycle — see
# the module docstring; captions.py imports THIS module lazily, at call time).
from captions.captions_ass import (
    _ass_time,
    _document,
    _escape_ass,
    _merge_punctuation,
    _norm_word,
    ass_color,
)

_EDGE_PUNCT_RE = re.compile(r"^[^\w]+|[^\w]+$")   # leading/trailing non-word chars


def _emphasis_core(text: str) -> str:
    """Lowercased word-core for emphasis matching: strips surrounding
    punctuation ('priorities?' -> 'priorities') but keeps interior chars, so
    '$12k' and '12k' both reduce to '12k' — the leading/trailing strip is
    applied to BOTH the caption word and the configured emphasis word, so the
    match is symmetric and case-insensitive."""
    return _EDGE_PUNCT_RE.sub("", _norm_word(text)).lower()


def _minimal_events(words: list[dict], m: dict,
                    emphasis: set[str]) -> list[tuple[list[dict], bool]]:
    """Group merged words into minimal events → [(words, is_accent), ...].

    An emphasis word is always its own event so it can carry the serif-italic
    accent STYLE alone (ASS can't switch font-family cleanly mid-event — the
    accent needs its own Dialogue in the MinimalAccent style). Other words fold
    into one event only while consecutive words nearly touch (gap
    < ``phrase_gap_s``) and the event stays <= ``phrase_max_words``.
    """
    gap, max_w = m["phrase_gap_s"], m["phrase_max_words"]
    events: list[tuple[list[dict], bool]] = []
    cur: list[dict] = []
    for w in words:
        if _emphasis_core(w["word"]) in emphasis:
            if cur:
                events.append((cur, False))
                cur = []
            events.append(([w], True))
            continue
        if cur and (float(w["start"]) - float(cur[-1]["end"])) < gap \
                and len(cur) < max_w:
            cur.append(w)
        else:
            if cur:
                events.append((cur, False))
            cur = [w]
    if cur:
        events.append((cur, False))
    return events


def _minimal_windows(events: list[tuple[list[dict], bool]],
                     m: dict) -> list[tuple[float, float]]:
    """Display (start, end) per event: first-word start → next event's start,
    with the on-screen hang past the last spoken word capped at ``hang_s`` (so a
    word doesn't linger through dead air) and a ``min_hold_s`` floor bounded by
    the next onset (rapid speech can't be held longer without stacking words)."""
    min_hold, hang = m["min_hold_s"], m["hang_s"]
    starts = [float(ev[0][0]["start"]) for ev in events]
    out: list[tuple[float, float]] = []
    for i, (ws, _) in enumerate(events):
        start = float(ws[0]["start"])
        last_end = float(ws[-1]["end"])
        nxt = starts[i + 1] if i + 1 < len(events) else last_end + hang
        end = min(nxt, last_end + hang)
        floor = start + min_hold
        if end < floor:
            end = min(floor, nxt) if i + 1 < len(events) else floor
        if end <= start:
            end = start + min_hold
        out.append((round(start, 3), round(end, 3)))
    return out


def _bbox_xywh(face: object) -> tuple[float, float, float, float]:
    """Read a normalized face bbox as (x, y, w, h). Accepts visual_state's
    ``[x, y, w, h]`` list, a ``{'bbox': [...]}`` wrapper, or an x/y/w/h dict."""
    if isinstance(face, dict):
        face = face.get("bbox", [face.get("x", 0), face.get("y", 0),
                                 face.get("w", 0), face.get("h", 0)])
    x, y, w, h = (list(face) + [0.0, 0.0, 0.0, 0.0])[:4]
    return float(x), float(y), float(w), float(h)


def _minimal_band_center(cfg: dict) -> int:
    """Vertical center (px) for minimal events.

    Face-relative when the plan carries ``faceBBoxNorm`` (band sits
    ``face_gap_frac`` of frame height below the chin); otherwise the chest band
    midpoint, carrying the edge-C12 up-shift (render.py moves ``baseline_max_y``
    up by ``bandYOffsetPx``). Always clamped so the glyph box stays inside the
    safe box.
    """
    m = cfg["MINIMAL"]
    face = cfg.get("faceBBoxNorm")
    if face:
        _, y, _, h = _bbox_xywh(face)
        center = (y + h + m["face_gap_frac"]) * CANVAS["height"]
    else:
        lo, hi = m["chest_band_y"]
        center = (lo + hi) / 2.0
        center -= CAPTIONS["baseline_max_y"] - cfg.get(
            "baseline_max_y", CAPTIONS["baseline_max_y"])
    half = m["font_size"] / 2.0
    top = SAFE_BOX["top"] + half
    bottom = CANVAS["height"] - SAFE_BOX["bottom"] - half
    return int(round(max(top, min(bottom, center))))


def _minimal_style_lines(m: dict) -> list[str]:
    """The two minimal styles: 'Minimal' (white Inter, bold, soft shadow) and
    'MinimalAccent' (gold Georgia italic). Alignment 5 = middle-center; every
    event carries its own ``\\pos`` so the band anchors on the exact center."""
    tmpl = ("Style: {name},{font},{size},{pri},{pri},{outl},&H80000000,"
            "{bold},{ital},0,0,100,100,0,0,1,{opx},{spx},5,0,0,0,1")
    outl = ass_color("black")
    return [
        tmpl.format(name="Minimal", font=m["font"], size=m["font_size"],
                    pri=ass_color(m["fill"]), outl=outl, bold=-1, ital=0,
                    opx=m["outline_px"], spx=m["shadow_px"]),
        tmpl.format(name="MinimalAccent", font=m["accent_font"],
                    size=m["font_size"], pri=ass_color(m["accent"]), outl=outl,
                    bold=0, ital=-1, opx=m["outline_px"], spx=m["shadow_px"]),
    ]


def _render_minimal_text(ws: list[dict], band_y: int) -> str:
    """One event's positioned text (verbatim words, no re-capitalization —
    minimal mirrors the reference's as-spoken lowercase look)."""
    text = " ".join(_escape_ass(_norm_word(w["word"])) for w in ws)
    return f"{{\\pos({VISUAL_CENTER_X},{band_y})}}{text}"


def event_count(words: list[dict], cfg: dict = CAPTIONS) -> int:
    """Number of minimal events the words compile to (CLI status helper)."""
    m = cfg["MINIMAL"]
    emphasis = {_emphasis_core(w) for w in (cfg.get("emphasisWords") or [])}
    return len(_minimal_events(_merge_punctuation(words), m, emphasis))


def build_minimal(words: list[dict], cfg: dict = CAPTIONS) -> str:
    """Compile output-time words into a minimal-style ASS document."""
    m = cfg["MINIMAL"]
    emphasis = {_emphasis_core(w) for w in (cfg.get("emphasisWords") or [])}
    events = _minimal_events(_merge_punctuation(words), m, emphasis)
    windows = _minimal_windows(events, m)
    band_y = _minimal_band_center(cfg)
    lines = [
        f"Dialogue: 0,{_ass_time(s)},{_ass_time(e)},"
        f"{'MinimalAccent' if is_accent else 'Minimal'},,0,0,0,,"
        f"{_render_minimal_text(ws, band_y)}"
        for (ws, is_accent), (s, e) in zip(events, windows)
    ]
    return _document(_minimal_style_lines(m), lines)
