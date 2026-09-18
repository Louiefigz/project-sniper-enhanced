#!/usr/bin/env python3
"""graphics_planner_receipts — the R17 b-roll receipts lane (MG-4).

"Receipts beat rendered graphics" (REFERENCE_STYLE_STUDY.md R17): when speech
names a SHOWABLE artifact — his channel, his company's site, his agency — the
pro CUTS TO THE ARTIFACT. This module proposes brollTrack-shaped rows
``{assetId: None, outStart, outEnd}`` with review fields; ``assetId`` is
ALWAYS None — the operator/brain fills it from the manifest pool
(LLM-identifier contract: the planner never invents ids).

R12's generic-entity blocklist does NOT apply here: "AI agency" earns no AI
logo, but it names the operator's real agency — a showable receipt.

CONCEPT-STOCK TIER (R24, overlay-rich only — graphics_planner gates the call
on the graphics_style axis): when speech goes abstract-conceptual
(AI/automation/hiring/team/workflow talk with NO showable owned artifact in
the sentence), pair 2 cuts to 1.5-3.5s concept stock. ``concept_lane``
proposes ``brollConcept`` rows a tier BELOW receipts: {assetId: null,
needsOperator: true, note: "concept-stock: <topic>"} — capped 1 per 60s,
body-only (the hook window spends receipts and burns, never stock), and any
receipt or own-screen cutaway on the same beat wins.

Split from graphics_planner_longform to keep each file within the
300-logic-line budget. PROPOSES only — nothing here mutates a plan.
"""

from __future__ import annotations

from planner.graphics_planner_density import reject_cand
from planner.graphics_planner_items import _sentences, phrase
from planner.graphics_planner_longform import HOOK_WINDOW_S, Ctx
from planner.motion_triggers import (_clean, _ends_sentence, _sentence_starts,
                             _word_text, detect_entities)
from producer_config import BROLL

# --------------------------------------------------------------------------- #
# Constants — the hold/gap numbers live in producer_config.BROLL (the
# consolidated b-roll lane doctrine, docs/studies/EDITCRAFT_LESSONS.md 2026-07-11);
# module-level names kept for call sites/tests.
# SINGULAR artifact nouns only — plurals ("AI products") are category talk,
# not one showable artifact. Platforms are showable bare ("I started with
# YouTube" = his channel). Data catalogs — exempt from the logic line limit.
# --------------------------------------------------------------------------- #
SHOWABLE_NOUNS = frozenset({"channel", "website", "site", "page", "app",
                            "product", "video", "clip", "board", "company",
                            "agency"})
SHOWABLE_PLATFORMS = frozenset({"youtube", "instagram", "tiktok", "linkedin",
                                "facebook", "github", "twitter"})
RECEIPT_HOLD_S = BROLL["receipt_hold_s"]      # R17: receipts run 1-4s
RECEIPT_DEDUP_S = BROLL["receipt_dedup_s"]    # same artifact re-named → one row
RECEIPT_NOUN_SCAN = 3           # tokens after an entity to find its noun

# R24 concept-stock vocabulary: the abstract-conceptual families pair 2 covers
# with stock (AI/robot/office footage). Deliberately TIGHT — a concept noun is
# only a stock cue when its sentence names NO showable owned artifact.
# Data catalog — exempt from the logic line limit.
CONCEPT_NOUNS = frozenset({
    "ai", "a.i.", "automation", "automations", "automate", "automated",
    "automating", "hiring", "hire", "hires", "hired", "team", "teams",
    "workflow", "workflows",
})
CONCEPT_HOLD_S = BROLL["concept_hold_s"]      # R24: concept stock 1.5-3.5s
CONCEPT_EVERY_S = BROLL["concept_every_s"]    # tier-below-receipts: 1 per 60s
CONCEPT_CONTEXT_WORDS = 3       # evidence context around the concept noun

# R17 precedence exception: multi-item STRUCTURE a single artifact can't show
# — the pro kept the whiteboard over receipts at the intro enumeration; the
# canvas-pip-list is the same structure with the speaker inset (R24).
STRUCTURE_KINDS = frozenset({"whiteboard-map", "canvas-pip-list"})


def propose(ctx: Ctx) -> list[dict]:
    """R17 receipt proposals from entity mentions naming showable artifacts."""
    if ctx.mode != "longform":
        return []
    words = ctx.words
    cleaned = [_clean(_word_text(w)) for w in words]
    starts = _sentence_starts(words)
    rows: list[dict] = []
    seen: dict[str, float] = {}
    for cand in detect_entities(words, starts, frozenset()):
        row = _receipt_row(cand, ctx, cleaned)
        if row is None:
            continue
        key = row["note"].lower()
        if key in seen and row["outStart"] - seen[key] < RECEIPT_DEDUP_S:
            continue
        seen[key] = row["outStart"]
        rows.append(row)
    rows.sort(key=lambda r: r["outStart"])
    return rows


def _receipt_row(cand: dict, ctx: Ctx, cleaned: list[str]) -> dict | None:
    """One entity trigger → a receipt row, or None if it shows nothing."""
    i, j = cand["wordIndices"][0], cand["wordIndices"][-1]
    start = float(ctx.words[i]["start"])
    state, _ = ctx.state_fn(start)
    if state == "screen-share":            # the screen already shows it
        return None
    artifact = _artifact_phrase(ctx.words, cleaned, (i, j))
    if artifact is None:
        return None
    return {"assetId": None, "outStart": round(start, 3),
            "outEnd": round(min(ctx.out_dur, start + RECEIPT_HOLD_S), 3),
            "needsOperator": True, "note": f"receipt: {artifact}",
            "evidence": artifact, "confidence": cand["confidence"],
            "trigger": "entity"}


def _artifact_phrase(words: list[dict], cleaned: list[str],
                     span: tuple[int, int]) -> str | None:
    """The showable phrase for an entity span, or None.

    Showable = a SINGULAR artifact noun within the next few tokens of the
    same sentence ("YouTube comedy channel", "SEO company"), or the entity
    itself is a platform the operator publishes on ("started with YouTube")."""
    i, j = span
    for k in range(j + 1, min(j + 1 + RECEIPT_NOUN_SCAN, len(words))):
        if _ends_sentence(_word_text(words[k - 1])):
            break
        if cleaned[k] in SHOWABLE_NOUNS:
            return phrase(words, i, k, 0)
    if any(cleaned[k] in SHOWABLE_PLATFORMS for k in range(i, j + 1)):
        return phrase(words, i, j, 0)
    return None


def apply_precedence(accepted: list[dict],
                     rows: list[dict]) -> tuple[list, list]:
    """R17 — "receipts beat rendered graphics": an own-screen cutaway colliding
    with a receipt window yields the beat to the real artifact, EXCEPT the
    STRUCTURE_KINDS (multi-item structure a single artifact can't show)."""
    kept, rejected = [], []
    for cand in accepted:
        hit = None
        if cand.get("anchor") == "own-screen" and cand["kind"] not in STRUCTURE_KINDS:
            hit = next((r for r in rows if r["outStart"] < cand["outEnd"]
                        and cand["outStart"] < r["outEnd"]), None)
        if hit is None:
            kept.append(cand)
            continue
        rejected.append(reject_cand(cand, "R17: receipts beat rendered "
                                    f"graphics — “{hit['note']}” covers this "
                                    "beat"))
    return kept, rejected


def suppress_covered(rows: list[dict],
                     accepted: list[dict]) -> tuple[list, list]:
    """One attention move per moment (R14): a receipt overlapping an accepted
    own-screen cutaway parks in rejected — the brain picks a lane."""
    own = [c for c in accepted if c.get("anchor") == "own-screen"]
    kept, rejected = [], []
    for row in rows:
        hit = next((c for c in own if row["outStart"] < c["outEnd"]
                    and c["outStart"] < row["outEnd"]), None)
        if hit is None:
            kept.append(row)
            continue
        rejected.append({"trigger": "receipt", "confidence": row["confidence"],
                         "evidence": row["evidence"],
                         "reason": f"covered by the {hit['kind']} cutaway at "
                                   f"{hit['outStart']:.1f}s — one attention "
                                   "move per moment"})
    return kept, rejected


def table_lines(rows: list[dict]) -> list[str]:
    """The b-roll receipts section of the proposal table (R17)."""
    lines = ["", f"B-ROLL RECEIPTS ({len(rows)})  — brollTrack rows "
             "{assetId: null, outStart, outEnd}; operator fills assetId "
             "from the pool (never invented):"]
    for i, r in enumerate(rows, 1):
        lines.append(f"{i:>2}  {r['outStart']:>6.2f}-{r['outEnd']:<6.2f}  "
                     f"{r['note']:<34}  {r['confidence']:<6}  !   "
                     f"“{r['evidence']}”")
    return lines


# --------------------------------------------------------------------------- #
# R24 concept-stock lane (overlay-rich only — the caller gates on the style
# axis; cutaway-only never emits these rows).
# --------------------------------------------------------------------------- #
def concept_lane(ctx: Ctx, receipt_rows: list[dict],
                 accepted: list[dict]) -> tuple[list, list]:
    """(brollConcept rows, rejected rows) for the R24 concept-stock tier.

    Tier order: receipts and accepted own-screen cutaways both beat concept
    stock on the same beat; survivors are capped 1 per CONCEPT_EVERY_S."""
    own = [c for c in accepted if c.get("anchor") == "own-screen"]
    rows, rejected = [], []
    last = -CONCEPT_EVERY_S
    for row in _concept_hits(ctx):
        cover = _concept_cover(row, receipt_rows, own)
        if cover:
            rejected.append(_concept_reject(row, f"R24 tier: {cover} covers "
                                            "this beat — concept stock is the "
                                            "tier below receipts"))
            continue
        if row["outStart"] - last < CONCEPT_EVERY_S:
            rejected.append(_concept_reject(row, "R24 cap: 1 concept-stock "
                                            f"insert per {CONCEPT_EVERY_S:.0f}s "
                                            f"(last at {last:.1f}s)"))
            continue
        last = row["outStart"]
        rows.append(row)
    return rows, rejected


def _concept_hits(ctx: Ctx) -> list[dict]:
    """One candidate row per BODY sentence that goes abstract-conceptual:
    a concept noun with NO showable owned artifact in the same sentence
    (an artifact sentence belongs to the receipts lane). Body-only — never
    inside the hook window (the hook spends receipts and burns, not stock)."""
    words = ctx.words
    cleaned = [_clean(_word_text(w)) for w in words]
    rows: list[dict] = []
    for lo, hi in _sentences(words):
        k = next((k for k in range(lo, hi + 1)
                  if cleaned[k] in CONCEPT_NOUNS), None)
        if k is None or _concept_skip(ctx, cleaned, (lo, hi), k):
            continue
        start = float(words[k]["start"])
        ctx_lo, ctx_hi = max(lo, k - CONCEPT_CONTEXT_WORDS), \
            min(hi, k + CONCEPT_CONTEXT_WORDS)
        rows.append({"assetId": None, "outStart": round(start, 3),
                     "outEnd": round(min(ctx.out_dur,
                                         start + CONCEPT_HOLD_S), 3),
                     "needsOperator": True,
                     "note": f"concept-stock: {cleaned[k]}",
                     "evidence": phrase(words, ctx_lo, ctx_hi, 0),
                     "confidence": "low", "trigger": "concept"})
    return rows


def _concept_skip(ctx: Ctx, cleaned: list[str], span: tuple[int, int],
                  k: int) -> bool:
    """True when the sentence earns NO concept row: hook window (body-only),
    screen-share (the screen already shows something), or a showable owned
    artifact in the same sentence (the receipts lane owns that beat)."""
    start = float(ctx.words[k]["start"])
    if start < HOOK_WINDOW_S:
        return True
    state, _ = ctx.state_fn(start)
    if state == "screen-share":
        return True
    lo, hi = span
    return any(cleaned[m] in SHOWABLE_NOUNS or cleaned[m] in SHOWABLE_PLATFORMS
               for m in range(lo, hi + 1))


def _concept_cover(row: dict, receipt_rows: list[dict],
                   own: list[dict]) -> str | None:
    """What beats this concept row on its beat (receipt/cutaway), or None."""
    for r in receipt_rows:
        if r["outStart"] < row["outEnd"] and row["outStart"] < r["outEnd"]:
            return f"“{r['note']}”"
    for c in own:
        if c["outStart"] < row["outEnd"] and row["outStart"] < c["outEnd"]:
            return f"the {c['kind']} cutaway at {c['outStart']:.1f}s"
    return None


def _concept_reject(row: dict, why: str) -> dict:
    return {"trigger": "concept", "confidence": row["confidence"],
            "evidence": row["evidence"], "reason": why}


def concept_table_lines(rows: list[dict]) -> list[str]:
    """The concept-stock section of the proposal table (R24)."""
    lines = ["", f"CONCEPT STOCK ({len(rows)})  — R24 tier BELOW receipts: "
             "brollConcept rows {assetId: null}; body-only, 1/60s; operator "
             "sources the stock (never invented):"]
    for i, r in enumerate(rows, 1):
        lines.append(f"{i:>2}  {r['outStart']:>6.2f}-{r['outEnd']:<6.2f}  "
                     f"{r['note']:<34}  {r['confidence']:<6}  !   "
                     f"“{r['evidence']}”")
    return lines
