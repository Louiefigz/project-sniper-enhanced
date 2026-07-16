#!/usr/bin/env python3
"""word_lock — word-locked seams: snap plan seams onto kept-word boundaries.

NATEHERK_STUDY.md T-G / §5 item 5: every transition start in the reference
lands on a narration phrase boundary (4/4 spot checks vs the VTT: 25.7 "…about
to see.", 67.2 "But benchmarks…", 186.0 "This is day one", 187.4 "So that
was…"). Our graphics ENTRANCES are mostly word-anchored already (triggers are
transcript-derived), but transitions-stage event times and graphic out-starts
are not snapped — this util closes that at PLAN time.

DETERMINISTIC (code finds WHERE, the brain never picks the numbers): the
boundaries are the starts/ends of the KEPT words in OUTPUT time — the words
handed in must come from ``graphics_planner.output_words`` (the transcript
remapped through ``compile_timeline``), so a snap survives cut edits by
arithmetic. The companion lint WARN lives in ``plan_lint_motion.check_word_lock``
(>150ms off-boundary, ``MOTION['word_lock']['warn_off_boundary_s']``).
"""

from __future__ import annotations

import copy
from bisect import bisect_left


def word_boundaries(words: list[dict]) -> list[float]:
    """Sorted, de-duplicated word starts + ends (kept words, OUTPUT time)."""
    pts: set[float] = set()
    for w in words:
        for key in ("start", "end"):
            v = w.get(key)
            if not isinstance(v, bool) and isinstance(v, (int, float)):
                pts.add(round(float(v), 4))
    return sorted(pts)


def nearest_boundary(t: float, boundaries: list[float]) -> float | None:
    """The boundary closest to ``t`` (earlier one on a tie); None when empty."""
    if not boundaries:
        return None
    i = bisect_left(boundaries, t)
    cands = boundaries[max(0, i - 1):i + 1]
    return min(cands, key=lambda b: (abs(b - t), b))


def off_boundary_s(t: float, boundaries: list[float]) -> float:
    """Distance (s) from ``t`` to the nearest boundary; inf when there is none."""
    b = nearest_boundary(t, boundaries)
    return abs(t - b) if b is not None else float("inf")


def snap_to_word_boundary(t: float, words: list[dict],
                          max_shift_s: float) -> float:
    """``t`` moved to the nearest kept-word boundary within ``max_shift_s``.

    Returns ``t`` unchanged when no boundary is that close (the lint WARN then
    names the drifting seam) — never a silent long-range jump.
    """
    b = nearest_boundary(float(t), word_boundaries(words))
    return b if b is not None and abs(b - float(t)) <= max_shift_s else float(t)


def snap_plan_seams(plan: dict, words: list[dict],
                    max_shift_s: float) -> tuple[dict, list[dict]]:
    """Word-lock a plan's seams at plan time; returns ``(new_plan, moves)``.

    Snaps every ``transitions[].outTime`` and TRANSLATES every
    ``graphicsTrack[]`` window (outStart and outEnd move together, hold
    preserved — the entrance seam locks to the word, the comp's internal
    schedule keeps its shape). The input plan is never mutated. Entries whose
    times are malformed are left untouched for ``plan_lint`` to reject.
    """
    out = copy.deepcopy(plan)
    boundaries = word_boundaries(words)
    moves: list[dict] = []
    for i, ev in enumerate(out.get("transitions") or []):
        t = ev.get("outTime")
        if isinstance(t, bool) or not isinstance(t, (int, float)):
            continue
        b = nearest_boundary(float(t), boundaries)
        if b is not None and b != float(t) and abs(b - float(t)) <= max_shift_s:
            ev["outTime"] = b
            moves.append({"track": "transitions", "index": i,
                          "from": float(t), "to": b})
    for i, g in enumerate(out.get("graphicsTrack") or []):
        s, e = g.get("outStart"), g.get("outEnd")
        if any(isinstance(v, bool) or not isinstance(v, (int, float))
               for v in (s, e)):
            continue
        b = nearest_boundary(float(s), boundaries)
        if b is None or b == float(s) or abs(b - float(s)) > max_shift_s:
            continue
        delta = b - float(s)
        g["outStart"] = round(b, 4)
        g["outEnd"] = round(float(e) + delta, 4)
        moves.append({"track": "graphicsTrack", "index": i,
                      "from": float(s), "to": b})
    return out, moves
