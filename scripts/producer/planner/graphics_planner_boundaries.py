#!/usr/bin/env python3
"""graphics_planner_boundaries — MG-4.1 SOURCE-time topic-boundary detection.

A chapter shift surfaces as a long inter-topic PAUSE, but ``compile_timeline``'s
cuts TRIM those pauses — so on the OUTPUT words the boundary detector loses its
strongest signal (``gap_s``) and rides discourse markers alone, firing false
takeovers on mid-content "okay so"s. This module runs the boundary pass on SOURCE
words (the pause intact) and maps each hit FORWARD through the TimelineMap: a
boundary whose anchor fell in cut material maps to None and is dropped. Every
OTHER trigger stays on the output words (``graphics_planner.assemble``) — only the
pause-driven boundary signal is destroyed by the cut.

Split from ``graphics_planner`` to keep each file within the logic budget; pairs
with ``graphics_planner_rules`` / ``_density`` / ``_zoom``. Doctrine + pointer:
PRODUCER_MOTION_GRAPHICS_PLAN.md §1 (topic boundaries → transition stingers).
"""

from __future__ import annotations

from planner.motion_triggers import detect_topic_boundaries_from_words


def out_span(words: list[dict], indices: list[int], sid: str,
             tmap) -> tuple[float, float] | None:
    """Output (start, end) of a source-time boundary span, or None if cut out.

    The anchor word's source start must survive the cut (else the boundary is
    gone); the span end falls back to the anchor's output when its own word
    crossed a cut, so the graphic still lands on the kept boundary word.
    """
    out_start = tmap.to_output(sid, float(words[indices[0]]["start"]))
    if out_start is None:
        return None
    out_end = tmap.to_output(sid, float(words[indices[-1]]["end"]))
    if out_end is None or out_end < out_start:
        out_end = out_start
    return round(out_start, 4), round(out_end, 4)


def map_source_words(src_words: list[dict], sid: str, tmap,
                     gap_s: float) -> list[dict]:
    """Detect boundaries on raw source words, map each forward; drop cut ones.

    Each survivor carries an ``outSpan`` (its resolved output window); its
    ``wordIndices`` still index the SOURCE list, so downstream must read the span,
    not re-derive times from the output words.
    """
    out: list[dict] = []
    for c in detect_topic_boundaries_from_words(src_words, gap_s):
        span = out_span(src_words, c["wordIndices"], sid, tmap)
        if span is None:
            continue
        out.append({**c, "outSpan": list(span)})
    return out


def collect(sources_by_id: dict, used_ids: set, load_words, tmap,
            gap_s: float) -> list[dict]:
    """Every used source's boundaries on source time, mapped to output, sorted.

    ``load_words`` is a ``source_entry -> word_list`` callable (kept in the caller
    so this module needs no transcript I/O). Sources absent from the manifest are
    skipped, mirroring ``graphics_planner.output_words``.
    """
    out: list[dict] = []
    for sid in used_ids:
        src = sources_by_id.get(sid)
        if src is None:
            continue
        out.extend(map_source_words(load_words(src), sid, tmap, gap_s))
    out.sort(key=lambda c: c["outSpan"][0])
    return out
