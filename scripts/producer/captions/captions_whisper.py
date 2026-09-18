#!/usr/bin/env python3
"""captions_whisper — the jaden ``whisper`` base caption style (G2).

Source: scripts/producer/docs/findings/JADEN_STYLE.md §4 (6-reel granular
traces, 5/6 HIGH). The base "whisper" layer is a tiny white sentence-case sans
slot that hard-replaces 1-3 word verbatim cues (~2 swaps/s at 255 wpm), soft
shadow, NO box / NO stroke, centered x0.5 in the y0.60-0.64 band. Karaoke
sweep rate is ZERO (CAP1: none anywhere in 623s). Emphasis is tier-A INLINE:
payload words (``captions.emphasisWords``) render amber from the cue's FIRST
frame via an in-event colour override — never swept in, never a separate
styled event (CAP3). Tier-B promotions leave the captions entirely and become
shout-layer lockups (the ``jaden-shout-lockup`` comp) — CAP4.

Dispatch: ``captions_ass.build_ass(words, style="whisper", cfg)`` (lazy import,
mirroring ``captions_minimal``). Config lives in
``producer_config.CAPTIONS["WHISPER"]``; the plan opts in with
``captions.style: "whisper"`` (lint vocabulary: ``CAPTION_STYLES``).
"""

from __future__ import annotations

from producer_config import CANVAS, CAPTIONS

# Shared ASS primitives + the emphasis word-core matcher (same no-cycle shape
# as captions_minimal: captions_ass imports THIS module lazily, at call time).
from captions.captions_ass import (
    _ass_time,
    _capitalize_first,
    _document,
    _ends_sentence,
    _escape_ass,
    _merge_punctuation,
    _norm_word,
    ass_color,
)
from captions.captions_minimal import _emphasis_core, _minimal_windows


def _inline_color(spec: str) -> str:
    """'#RRGGBB' → the inline ``\\c`` override literal ``&HBBGGRR&``."""
    return ass_color(spec)[4:] + "&"        # strip the &H00 alpha prefix


def _whisper_cues(words: list[dict], m: dict) -> list[list[dict]]:
    """Verbatim 1-3 word chunk cues (CAP2 grouping).

    A cue closes on: a gap >= ``phrase_gap_s`` (breath), hitting
    ``phrase_max_words``, or the previous word ending a sentence (a cue never
    straddles a sentence boundary — sentence case needs the seam).
    """
    gap, max_w = m["phrase_gap_s"], m["phrase_max_words"]
    cues: list[list[dict]] = []
    cur: list[dict] = []
    for w in words:
        joins = (cur and (float(w["start"]) - float(cur[-1]["end"])) < gap
                 and len(cur) < max_w and not _ends_sentence(cur[-1]["word"]))
        if joins:
            cur.append(w)
        else:
            if cur:
                cues.append(cur)
            cur = [w]
    if cur:
        cues.append(cur)
    return cues


def _cue_caps(cues: list[list[dict]]) -> list[bool]:
    """Sentence case per cue: capitalize the first word of the first cue and of
    any cue following a sentence-ending word (verbatim otherwise)."""
    return [i == 0 or _ends_sentence(cues[i - 1][-1]["word"])
            for i in range(len(cues))]


def _band_center_y(m: dict, cfg: dict) -> int:
    """Cue center (px): midpoint of ``band_y_frac`` on the delivery canvas."""
    lo, hi = m["band_y_frac"]
    height = cfg.get("canvas", CANVAS)["height"]
    return int(round((lo + hi) / 2.0 * height))


def _render_cue(ws: list[dict], flags: tuple[bool, set[str]],
                m: dict, pos: tuple[int, int]) -> str:
    """One cue's positioned text: sentence-case first word when it opens a
    sentence; tier-A emphasis words tinted amber INLINE from the cue's first
    frame (``\\c`` override, reset with bare ``\\c`` back to the style fill)."""
    capitalize, emphasis = flags
    amber = _inline_color(m["accent"])
    parts: list[str] = []
    for i, w in enumerate(ws):
        text = _norm_word(w["word"])
        if i == 0 and capitalize:
            text = _capitalize_first(text)
        text = _escape_ass(text)
        if _emphasis_core(w["word"]) in emphasis:
            text = f"{{\\c&H{amber}}}{text}{{\\c}}"
        parts.append(text)
    x, y = pos
    return f"{{\\pos({x},{y})}}" + " ".join(parts)


def _whisper_style_line(m: dict) -> str:
    """The single 'Whisper' style: white bold sans, soft shadow, NO outline
    box (BorderStyle 1 with Outline 0), alignment 5 (events carry ``\\pos``)."""
    return ("Style: Whisper,{font},{size},{pri},{pri},{outl},&H80000000,"
            "-1,0,0,0,100,100,0,0,1,{opx},{spx},5,0,0,0,1").format(
        font=m["font"], size=m["font_size"], pri=ass_color(m["fill"]),
        outl=ass_color("black"), opx=m["outline_px"], spx=m["shadow_px"])


def event_count(words: list[dict], cfg: dict = CAPTIONS) -> int:
    """Number of whisper cues the words compile to (CLI status helper)."""
    return len(_whisper_cues(_merge_punctuation(words), cfg["WHISPER"]))


def build_whisper(words: list[dict], cfg: dict = CAPTIONS) -> str:
    """Compile output-time words into a whisper-style ASS document."""
    m = cfg["WHISPER"]
    emphasis = {_emphasis_core(w) for w in (cfg.get("emphasisWords") or [])}
    cues = _whisper_cues(_merge_punctuation(words), m)
    windows = _minimal_windows([(c, False) for c in cues], m)
    caps = _cue_caps(cues) if m.get("sentence_case") else [False] * len(cues)
    pos = (int(m["center_x"]), _band_center_y(m, cfg))
    lines = [
        f"Dialogue: 0,{_ass_time(s)},{_ass_time(e)},Whisper,,0,0,0,,"
        f"{_render_cue(ws, (cap, emphasis), m, pos)}"
        for ws, (s, e), cap in zip(cues, windows, caps)
    ]
    return _document([_whisper_style_line(m)], lines, cfg.get("canvas", CANVAS))
