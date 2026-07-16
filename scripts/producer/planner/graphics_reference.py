#!/usr/bin/env python3
"""graphics_reference — the reference-driven graphic MECHANISM (cross-format).

The operator's model (project_reference_graphic_mechanism): a graphic is a
REFERENCE being resolved, not a trigger firing a comp. When the speaker
points/refers — "here", "look at this", "check this out", or names the thing —
the graphic that appears IS that referent. Division of labor:
  * the BRAIN owns the WHAT — names the referent and PICKS the graphic,
  * the SYSTEM owns the WHERE/WHEN/HOW — placement, timing, anchor ("you point,
    I place"); never the operator's job.

Cross-format: the mechanism holds for shorts AND longs (more frequent in
shorts). Placement is the only aspect-dependent part — a SHORT (9:16) overlays
in the HEADROOM (room above the head); a LONG (16:9) CUTS full-frame (no
headroom); a screen-share keeps the screen the star (own-screen).

SOURCE HIERARCHY (do NOT over-abstract): HyperFrames comps are PRIMARY and the
default both formats — the brain picks a comp and fills it (code-rendered, $0).
The b-roll pool is a shorts-leaning reach (the receipts/illustration lanes);
Higgsfield generation is a future source behind the SAME seam, built as its own
loadable skill — no code path here (skills-only, no flags). The operator can
steer source at any time ("create b-roll" / "no b-roll" / "use my b-roll here")
— that's a directive the brain honors in the skill flow, not a config here.

This module is the DISCOVERY lane (`reference_beats` — deictic showing-language)
+ the HyperFrames-first RESOLVER (`fill_reference_spec` — brain's comp + copy →
a placed candidate). PROPOSES only; nothing here mutates a plan.
"""

from __future__ import annotations

from planner.graphics_planner_items import phrase
from planner.graphics_planner_longform import Ctx, canvas_ok
from planner.motion_triggers import _clean, _sentence_end, _word_text

# Deictic-presentational SHOWING language — "show the referent NOW". Data catalog
# (exempt from the logic line limit); high-recall — the brain confirms which
# actually reference a showable thing. NOT bare "this"/"that" (too noisy) — the
# pointing/showing phrases the operator uses when a visual should appear.
SHOWING_CUES = (
    ("look", "at", "this"), ("look", "at", "that"), ("look", "at", "these"),
    ("look", "at", "how"), ("check", "this", "out"), ("watch", "this"),
    ("watch", "how"), ("right", "here"), ("take", "a", "look"),
    ("you", "can", "see"), ("look", "here"), ("see", "this"),
    ("here", "is", "the"), ("this", "right", "here"), ("what", "you", "see"),
)

REFERENCE_HOLD_S = 2.5
REFERENCE_MIN_GAP_S = 12.0        # don't surface two reference slots closer
RAWSPAN_WORDS = 14               # transcript context the brain reads to decide


def reference_beats(ctx: Ctx) -> list[dict]:
    """Deictic DISCOVERY: showing-language reference SLOTS (needsContent), or [].

    High recall — the brain keeps the ones that reference a SHOWABLE thing, names
    the referent + picks the HyperFrames comp. Cross-format; placement is
    pre-decided from aspect + state (the system's job)."""
    words = ctx.words
    cleaned = [_clean(_word_text(w)) for w in words]
    beats: list[dict] = []
    last = -REFERENCE_MIN_GAP_S
    for i in range(len(words)):
        if not _cue_at(cleaned, i):
            continue
        start = float(words[i]["start"])
        if start - last < REFERENCE_MIN_GAP_S:
            continue
        last = start
        beats.append(_slot(words, i, ctx))
    return beats


def _cue_at(cleaned: list[str], i: int) -> bool:
    return any(cleaned[i:i + len(c)] == list(c) for c in SHOWING_CUES)


def _slot(words: list[dict], i: int, ctx: Ctx) -> dict:
    """One reference slot at a showing-cue, placement pre-decided by the system."""
    start = float(words[i]["start"])
    end = round(min(ctx.out_dur, start + REFERENCE_HOLD_S), 3)
    state, _ = ctx.state_fn(start)
    j = min(_sentence_end(words, i), i + RAWSPAN_WORDS)
    raw = phrase(words, i, j, 0)
    return {"trigger": "reference", "outStart": round(start, 3), "outEnd": end,
            "anchor": place(ctx.aspect, state), "state": state or "talking-head",
            "aspect": ctx.aspect, "needsContent": True, "needsOperator": True,
            "rawSpan": raw, "evidence": raw, "confidence": "low",
            "note": "reference: brain names the referent + picks a HyperFrames "
                    "comp (or pool b-roll), or drops the slot"}


def place(aspect: str, state: str | None) -> str:
    """The PLACEMENT engine (the system's job — you point, I place).

    Over a screen-share the screen is the star → own-screen. A SHORT (9:16) has
    room above the head → HEADROOM overlay. A LONG (16:9) has no headroom → a
    full-frame OWN-SCREEN cutaway (HyperFrames-first)."""
    if state == "screen-share":
        return "own-screen"
    if aspect == "9:16":
        return "headroom"
    return "own-screen"


def fill_reference_spec(beat: dict, kind: str, spec: dict) -> dict | None:
    """Brain's chosen HyperFrames comp + filled copy → a PLACED candidate.

    ``kind`` must be a real comp legal for the beat's aspect (canvas_ok); an
    empty spec or an aspect-illegal kind returns None (drop the slot — clean
    frame). Placement (anchor) + timing are already the beat's — the system's,
    decided at discovery; the brain supplies ONLY the comp + its content (the
    referent). The b-roll path is fill_illustration_spec; generation is a future
    skill on this same seam."""
    if not spec or not canvas_ok(kind, beat.get("aspect", "16:9")):
        return None
    out = {k: v for k, v in beat.items()
           if k not in ("needsContent", "rawSpan", "note", "state", "aspect")}
    out["kind"] = kind
    out["spec"] = spec
    out["confidence"] = "medium"
    out["reason"] = (f"reference → {kind} ({beat['anchor']}); "
                     "brain-named referent, system-placed")
    return out


def suppress_covered(beats: list[dict],
                     taken: list[dict]) -> tuple[list, list]:
    """Drop reference slots a graphic/b-roll already owns on the beat."""
    kept, rejected = [], []
    for beat in beats:
        hit = next((t for t in taken if t["outStart"] < beat["outEnd"]
                    and beat["outStart"] < t["outEnd"]), None)
        if hit is None:
            kept.append(beat)
            continue
        rejected.append({"trigger": "reference", "confidence": "low",
                         "evidence": beat["evidence"],
                         "reason": f"covered by a {hit.get('kind', 'graphic')} "
                                   f"at {hit['outStart']:.1f}s"})
    return kept, rejected


def table_lines(beats: list[dict]) -> list[str]:
    """The reference section of the proposal table (cross-format)."""
    lines = ["", f"REFERENCES ({len(beats)})  — deictic 'here / look at this' "
             "slots {needsContent}; the brain names the referent + picks a "
             "HyperFrames comp (pool b-roll for shorts), system places it:"]
    for i, b in enumerate(beats, 1):
        lines.append(f"{i:>2}  {b['outStart']:>6.2f}-{b['outEnd']:<6.2f}  "
                     f"{'reference':<20}  {b['anchor']:<11}  {b['confidence']:<6}"
                     f"  !   “{b['evidence']}”")
    return lines
