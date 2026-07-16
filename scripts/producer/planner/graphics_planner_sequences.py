#!/usr/bin/env python3
"""graphics_planner_sequences — ordinal clusters → candidate whiteboard-list BEATS.

The sequence half of the R14 longform retarget (sibling to
graphics_planner_items, which handles COORDINATED lists "A, B, and C"). A process
spoken as a run of ordinals — "First … then … finally …" — MAY earn a full-frame
whiteboard-list checklist.

THE DIVISION OF LABOUR (feedback 2026-07-07: no regex for semantics). This module
is DETERMINISTIC and does only the part code is good at: spot a CLUSTER of
ordinals and hand back a BEAT — the window, the per-ordinal timing anchors, and
the raw transcript span. It does NOT decide whether the beat is a real list, and
it does NOT write item copy: "first person" (grammar) vs "First, sharpen the
pain" (a step) is a CONTEXT call only an LLM can make. That semantic step lives
in graphics_copy (brain in the skill flow now, a pipeline LLM call for the live
app); it fills the copy and graphics_copy times each label to its anchor. A beat
carries ``needsCopy: True`` and an empty ``spec`` until then — it must never
reach the render un-filled.

PROPOSES only — candidates are reviewed by the brain, vetoed by the operator.
"""

from __future__ import annotations

from planner.graphics_planner_items import WHITEBOARD_EXIT_PAD_S, phrase
from planner.motion_triggers import (SEQUENCE_STRONG, SEQUENCE_WEAK, _clean,
                                     _sentence_end, _word_text)
from producer_config import MOTION

# --------------------------------------------------------------------------- #
# Constants — module-local (belong in a future MOTION["longform_cutaways"]
# block; see graphics_planner_longform for the rationale).
# --------------------------------------------------------------------------- #
SEQ_MIN_ORDINALS = 2            # a cluster worth asking the LLM about — 2+ ordinals
SEQ_CLUSTER_GAP_S = 25.0        # ordinals >25s apart are separate clusters
HINT_WORDS = 9                  # raw words after each ordinal handed to the LLM
_ORDINALS = SEQUENCE_STRONG | SEQUENCE_WEAK


def sequence_beats(words: list[dict], mode: str, state_fn,
                   out_dur: float) -> list[dict]:
    """Candidate whiteboard-list BEATS from clustered ordinals — DETERMINISTIC.

    Each beat is a window + per-ordinal timing anchors + the raw transcript span,
    with ``needsCopy: True`` and an empty ``spec``. Whether the beat is a real
    list and what the clean labels are is filled later by graphics_copy (LLM).
    Only talking-head clusters of 2+ ordinals fire; the caller gates
    mode/canvas."""
    return [_beat(words, run, (mode, out_dur))
            for run in _ordinal_runs(words, state_fn)]


def _ordinal_runs(words: list[dict], state_fn) -> list[list[int]]:
    """Talking-head clusters of 2+ ordinals (word positions), anchored by ≥1
    STRONG ordinal so bare 'then … then' temporal chatter is not surfaced."""
    cleaned = [_clean(_word_text(w)) for w in words]
    # Untagged longform defaults to talking-head (same as the R14 retarget gate,
    # graphics_planner_longform._is_talking_head) — only an EXPLICIT screen-share
    # zone opts out. Without this, an untagged plan surfaces no beats at all.
    ords = [i for i, c in enumerate(cleaned)
            if c in _ORDINALS
            and (state_fn(float(words[i]["start"]))[0] or "talking-head")
            == "talking-head"]
    runs: list[list[int]] = []
    cur: list[int] = []
    for i in ords:
        if cur and (float(words[i]["start"])
                    - float(words[cur[-1]]["start"]) > SEQ_CLUSTER_GAP_S):
            _flush_run(runs, cur, cleaned)
            cur = []
        cur.append(i)
    _flush_run(runs, cur, cleaned)
    return runs


def _flush_run(runs: list, cur: list[int], cleaned: list[str]) -> None:
    """Surface a cluster only if it has 2+ ordinals AND a strong anchor (a
    recall gate — pattern only; the LLM still decides if it's a real list)."""
    if len(cur) >= SEQ_MIN_ORDINALS and any(cleaned[i] in SEQUENCE_STRONG
                                            for i in cur):
        runs.append(list(cur))


def _beat(words: list[dict], ordinals: list[int], target: tuple) -> dict:
    """A candidate beat: window (rides the spoken span, hold-capped), per-ordinal
    timing anchors ({atSec, hint}), and the raw span for the copy LLM."""
    mode, out_dur = target
    hold_max = MOTION["hold_max_s"].get(mode, MOTION["hold_max_s"]["short"])
    out_start = float(words[ordinals[0]]["start"])
    span_end = min(_sentence_end(words, ordinals[-1]), len(words) - 1)
    out_end = min(out_dur, float(words[span_end]["end"]) + WHITEBOARD_EXIT_PAD_S,
                  out_start + hold_max)
    anchors = [{"atSec": round(max(0.0, float(words[i]["start"]) - out_start), 2),
                "hint": phrase(words, i, min(i + HINT_WORDS, span_end), 0)}
               for i in ordinals]
    raw = phrase(words, ordinals[0], span_end, 0)
    return {"outStart": round(out_start, 3), "outEnd": round(out_end, 3),
            "kind": "whiteboard-list", "trigger": "sequence",
            "anchor": "own-screen", "spec": {}, "needsCopy": True,
            "anchors": anchors, "rawSpan": raw, "confidence": "medium",
            "reason": f"{len(ordinals)}-ordinal cluster → candidate whiteboard-"
                      "list (graphics_copy/LLM decides real-list? + writes items)",
            "evidence": raw[:80], "needsOperator": True}
