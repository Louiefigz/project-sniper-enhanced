#!/usr/bin/env python3
"""graphics_planner_gauge — the milestone GAUGE lane (widget-gauge / widget-pills).

Grounded in the operator's reels (Video-472): a run of climbing quantities —
"0 to 1k to 10k to 50k to 100k to 1M followers" — renders as a HEADROOM gauge
with an arrow sweeping across, or a pill row. Shorts-native (widget-gauge is a
9:16 comp); a long expresses the same climb through other comps the brain picks.

Split like every other lane (feedback: no regex for semantics — but a numeric
CLIMB is arithmetic, not a context call, so the WHERE is deterministic): the
detector finds a run of number tokens whose MAGNITUDE increases, and surfaces a
BEAT with a per-milestone timing anchor + the spoken text (``needsCopy``). The
BRAIN reads it, confirms it's a real milestone gauge, writes the gauge ``label``
and maps each milestone to a bar POSITION (0..1), then fills via
``fill_gauge_spec`` — copy + positions from the brain, TIMES from the anchors.
PROPOSES only.
"""

from __future__ import annotations

from planner.graphics_planner_longform import Ctx, canvas_ok
from planner.graphics_planner_items import phrase
from planner.motion_triggers import _clean, _word_text, detect_numbers

# scale suffixes / words → multiplier (lexing a number, NOT a semantic call)
_SCALE = {"k": 1e3, "thousand": 1e3, "grand": 1e3, "m": 1e6, "mil": 1e6,
          "million": 1e6, "b": 1e9, "billion": 1e9}
GAUGE_MIN_MARKS = 3            # a climb needs 3+ milestones to read as a gauge
GAUGE_MAX_MARKS = 4           # widget-gauge renders pos1..4
GAUGE_GAP_WORDS = 6          # milestones within N words of each other
GAUGE_HOLD_S = 4.0           # widget-gauge's natural duration


def gauge_beats(ctx: Ctx) -> list[dict]:
    """Milestone-progression BEATS (``needsCopy``) for shorts, or ``[]``.

    Shorts/9:16 only — widget-gauge is a vertical comp; a long renders a climb
    through comps the brain picks at a reference/number beat instead."""
    if ctx.mode != "short" or not canvas_ok("widget-gauge", ctx.aspect):
        return []
    words = ctx.words
    cleaned = [_clean(_word_text(w)) for w in words]
    marks = []
    for cand in detect_numbers(words, cleaned):
        mag = _magnitude(words, cleaned, cand["wordIndices"])
        if mag is None:
            continue
        i = cand["wordIndices"][0]
        marks.append({"i": i, "mag": mag, "atSec": round(float(words[i]["start"]), 3),
                      "text": cand["text"]})
    return [_beat(words, run, ctx) for run in _runs(marks)]


def _magnitude(words: list[dict], cleaned: list[str], indices: list[int]):
    """Approx numeric magnitude of a number candidate (digits × scale), or None."""
    base, mult = None, 1.0
    for k in indices:
        raw = _word_text(words[k]).lower().replace(",", "").replace("$", "")
        digits = "".join(ch for ch in raw if ch.isdigit() or ch == ".")
        if digits:
            try:
                base = float(digits)
            except ValueError:
                pass
        suffix = "".join(ch for ch in raw if ch.isalpha())
        if suffix in _SCALE:
            mult = _SCALE[suffix]
        elif cleaned[k] in _SCALE:
            mult = _SCALE[cleaned[k]]
    return base * mult if base is not None else None


def _runs(marks: list[dict]) -> list[list[dict]]:
    """Cluster consecutive, non-decreasing-magnitude marks into climbs (net up)."""
    runs, cur = [], []
    for m in marks:
        if cur and m["i"] - cur[-1]["i"] <= GAUGE_GAP_WORDS and m["mag"] >= cur[-1]["mag"]:
            cur.append(m)
        else:
            runs += _flush(cur)
            cur = [m]
    return runs + _flush(cur)


def _flush(cur: list[dict]) -> list[list[dict]]:
    if len(cur) >= GAUGE_MIN_MARKS and cur[-1]["mag"] > cur[0]["mag"]:
        return [cur]
    return []


def _beat(words: list[dict], run: list[dict], ctx: Ctx) -> dict:
    """One gauge beat over a milestone climb — copy is the brain's, timing ours."""
    start, end = run[0]["atSec"], round(min(ctx.out_dur, run[0]["atSec"] + GAUGE_HOLD_S), 3)
    raw = phrase(words, run[0]["i"], run[-1]["i"], 0)
    return {"trigger": "progression", "kind": "widget-gauge",
            "outStart": start, "outEnd": end, "anchor": "headroom",
            "aspect": ctx.aspect, "needsCopy": True, "needsOperator": True,
            "marks": [{"atSec": m["atSec"], "text": m["text"]} for m in run],
            "rawSpan": raw, "evidence": raw, "confidence": "medium",
            "note": "milestone gauge: brain writes the label + maps each "
                    "milestone to a bar position (0..1), or drops the beat"}


def fill_gauge_spec(beat: dict, label: str, positions: list[dict]) -> dict | None:
    """Brain's label + milestone POSITIONS → a placed widget-gauge candidate.

    ``positions`` = ordered ``[{"markIndex": int, "pos": float}]`` (2–4 of the
    beat's marks, ``pos`` in 0..1). Each lands on its mark's spoken time; the
    positions must be non-decreasing (a climb). Fewer than 2, out-of-range, or
    non-monotonic → ``None`` (drop; not a real gauge)."""
    marks = beat.get("marks") or []
    spec: dict = {"label": " ".join(str(label).split()[:6])}
    times, last_pos, n = [], -1.0, 0
    for item in positions[:GAUGE_MAX_MARKS]:
        mi, pos = item.get("markIndex"), item.get("pos")
        if not isinstance(mi, int) or not 0 <= mi < len(marks):
            continue
        if not isinstance(pos, (int, float)) or not 0.0 <= pos <= 1.0 or pos < last_pos:
            return None
        n += 1
        last_pos = float(pos)
        spec[f"pos{n}"] = round(float(pos), 3)
        spec[f"at{n}"] = round(marks[mi]["atSec"] - beat["outStart"], 3)
        times.append(marks[mi]["text"])
    if n < 2:
        return None
    out = {k: v for k, v in beat.items()
           if k not in ("marks", "rawSpan", "needsCopy", "note", "aspect")}
    out["spec"] = spec
    out["reason"] = f"milestone climb → widget-gauge ({' → '.join(times)})"
    return out


def table_lines(beats: list[dict]) -> list[str]:
    """The milestone-gauge section of the proposal table (shorts)."""
    lines = ["", f"MILESTONE GAUGES ({len(beats)})  — headroom widget-gauge slots "
             "{needsCopy}; brain writes label + maps each milestone to a bar "
             "position:"]
    for i, b in enumerate(beats, 1):
        lines.append(f"{i:>2}  {b['outStart']:>6.2f}-{b['outEnd']:<6.2f}  "
                     f"{'widget-gauge':<20}  {b['confidence']:<6}  !   "
                     f"“{b['evidence']}”")
    return lines
