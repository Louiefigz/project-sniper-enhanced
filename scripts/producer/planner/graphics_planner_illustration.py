#!/usr/bin/env python3
"""graphics_planner_illustration — the concept ILLUSTRATION b-roll lane.

Grounded in the operator's real longs (project_broll_footage_study): on a
CONCEPT beat with no showable owned artifact — "getting your data ready",
"your team's skills", "roadmap to growth" — the pro CUTS TO A FLAT-VECTOR
ILLUSTRATION ("6 reasons": office-meeting-with-charts, rocket/growth scenes),
full-frame. It is b-roll — a pool asset riding over the footage — NOT a
data-driven comp, so it rides the existing broll_insert engine.

Whether an abstract beat DESERVES a visual, and WHICH concept illustration, is
a pure SEMANTIC call (feedback: no regex for semantics — a concept-noun list
can't tell "our growth roadmap" worth-illustrating from "grow your list"
throwaway). So this lane is deterministic ONLY about the legal SLOTS:
talking-head BODY sentences, past the hook, spread by a min-gap, minus the
beats a receipt or cutaway already owns. The BRAIN (skill) reads each slot's
``rawSpan``, keeps the few worth a visual, and fills a REAL illustration
``assetId`` from the manifest ``broll`` pool (no invented ids; drop the slot if
nothing fits) via ``graphics_copy.fill_illustration_spec``. A filled slot is an
ordinary brollTrack row — the render already handles it.

Longform only: illustrations are a full-frame-cutaway pattern; the 9:16 short
equivalent is a HEADROOM overlay, which needs the shorts-graphics system that
does not exist yet (see project_broll_footage_study). PROPOSES only — nothing
here mutates a plan.
"""

from __future__ import annotations

from planner.graphics_planner_items import _sentences, phrase
from planner.graphics_planner_longform import HOOK_WINDOW_S, Ctx
from producer_config import BROLL

# Hold/gap knobs live in producer_config.BROLL (consolidated b-roll lane
# doctrine, docs/studies/EDITCRAFT_LESSONS.md 2026-07-11); module names kept.
ILLUSTRATION_HOLD_S = BROLL["illustration_hold_s"]        # = receipts hold
ILLUSTRATION_MIN_GAP_S = BROLL["illustration_min_gap_s"]  # 1 slot per 30s body
RAWSPAN_WORDS = 16                 # transcript context the brain reads to decide


def illustration_beats(ctx: Ctx) -> list[dict]:
    """Candidate concept-illustration SLOTS (``needsConcept``), or ``[]``.

    Body talking-head sentences past the hook, spread by ILLUSTRATION_MIN_GAP_S.
    The brain keeps the worth-illustrating few and fills a pool assetId."""
    if ctx.mode != "longform":
        return []
    words = ctx.words
    beats: list[dict] = []
    last = -ILLUSTRATION_MIN_GAP_S
    for lo, hi in _sentences(words):
        start = float(words[lo]["start"])
        if start < HOOK_WINDOW_S:                       # body only, not the hook
            continue
        if (ctx.state_fn(start)[0] or "talking-head") != "talking-head":
            continue                                    # only over a clean head
        if start - last < ILLUSTRATION_MIN_GAP_S:
            continue
        last = start
        beats.append(_slot(words, (lo, hi), ctx.out_dur))
    return beats


def _slot(words: list[dict], span: tuple[int, int], out_dur: float) -> dict:
    """One candidate illustration slot over a body sentence."""
    lo, hi = span
    start = float(words[lo]["start"])
    end = round(min(out_dur, start + ILLUSTRATION_HOLD_S), 3)
    raw = phrase(words, lo, min(hi, lo + RAWSPAN_WORDS), 0)
    return {"trigger": "illustration", "kind": "broll-illustration",
            "assetId": None, "outStart": round(start, 3), "outEnd": end,
            "anchor": "own-screen", "needsConcept": True, "needsOperator": True,
            "rawSpan": raw, "evidence": raw, "confidence": "low",
            "note": "illustration?: brain picks a pool illustration for this "
                    "concept or drops the slot"}


def suppress_covered(beats: list[dict], receipt_rows: list[dict],
                     accepted: list[dict]) -> tuple[list, list]:
    """Drop slots a receipt or accepted own-screen cutaway already owns — one
    visual per beat; the brain shouldn't be offered an illustration there."""
    own = [c for c in accepted if c.get("anchor") == "own-screen"]
    kept, rejected = [], []
    for beat in beats:
        cover = _cover(beat, receipt_rows, own)
        if cover is None:
            kept.append(beat)
            continue
        rejected.append({"trigger": "illustration", "confidence": "low",
                         "evidence": beat["evidence"],
                         "reason": f"covered by {cover} — one visual per beat"})
    return kept, rejected


def _cover(beat: dict, receipt_rows: list[dict],
           own: list[dict]) -> str | None:
    """What already owns this slot's beat (receipt / cutaway), or None."""
    for r in receipt_rows:
        if r["outStart"] < beat["outEnd"] and beat["outStart"] < r["outEnd"]:
            return f"“{r['note']}”"
    for c in own:
        if c["outStart"] < beat["outEnd"] and beat["outStart"] < c["outEnd"]:
            return f"the {c['kind']} cutaway at {c['outStart']:.1f}s"
    return None


def table_lines(beats: list[dict]) -> list[str]:
    """The concept-illustration section of the proposal table."""
    lines = ["", f"CONCEPT ILLUSTRATIONS ({len(beats)})  — full-frame b-roll "
             "slots {assetId: null, needsConcept}; the brain keeps the few "
             "worth a visual and fills an assetId from the manifest pool "
             "(never invented):"]
    for i, b in enumerate(beats, 1):
        lines.append(f"{i:>2}  {b['outStart']:>6.2f}-{b['outEnd']:<6.2f}  "
                     f"{'broll-illustration':<20}  {b['confidence']:<6}  !   "
                     f"“{b['evidence']}”")
    return lines
