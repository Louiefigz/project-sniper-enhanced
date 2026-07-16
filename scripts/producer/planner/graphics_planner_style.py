#!/usr/bin/env python3
"""graphics_planner_style — the overlay-rich (pair-2) longform retarget.

REFERENCE_STYLE_STUDY.md pair 2 (R21-R24 + the R14 CONTRADICTION callout):
pair 2's editor overlays constantly — two-tier burned text at chest, icon
stacks in headroom, chips beside the face — and reserves full takeovers for
section/canvas moments. R14 is therefore a PER-VIDEO STYLE AXIS
(graphics_style: cutaway-only | overlay-rich), never a universal law. This
module is the overlay-rich half; graphics_planner_longform stays the
cutaway-only half (byte-identical to the pre-axis planner) and
graphics_planner dispatches on ``resolve_style``. Only LONGFORM zones run
this grammar — the shorts path never enters here.

What overlay-rich changes (each PROPOSES only, like all of MG-4):
* thesis lines: the kinetic-quote-wide takeover is reserved for the TOP-1
  thesis per 2 minutes; every other thesis burns as a ``fragment-payoff``
  free-band overlay (R23: small verbatim fragment + large accent payoff
  building word-by-word, slid to the emptier side per R10). The accent color
  stays a per-video BRAND TOKEN — the spec never hardcodes it.
* number-payoff lines: the 9:16 stat-card (canvas-dead on 16:9) becomes a
  ``fragment-payoff`` too — setup words small, the number clause as payoff.
* headroom icon stacks (icon-badge) become legal again over the talking head
  — pair 2 runs them constantly. The comp is 9:16-AUTHORED but placed by
  REGION (free_space/graphics_anchors scale the element region, not the
  canvas), and the pair-2 reference shows the grammar on 16:9, so icon-badge
  is exempted from the MG-4.3 canvas gate IN THIS STYLE ONLY.
* topic boundaries on a 16:9 target: ``section-takeover`` own-screen chapter
  cards (drifting ghost numeral = chapter ordinal, title lands second)
  supersede the 9:16-era stinger/glass-takeover kinds.
* 5+-item enumerations: a gate-legal full-frame ``whiteboard-list`` fallback;
  ``canvas-pip-list`` upgrades it to speaker PiP only after that renderer is
  wired — see graphics_planner_items.pip_aware_maps.
* concept-stock b-roll (R24) rides the receipts lane —
  graphics_planner_receipts.concept_lane, called by graphics_planner.

NO trigger maps to glitch-hit (400ms operator/brain-only emphasis hit — no
transcript signal says "hit here") or avatar-bio-card (once-per-channel intro
asset, operator-placed) — see graphics_planner_rules for the rationale; both
are registered in the canvas map so lint knows them.

PROPOSES only — the brain reviews, the operator vetoes. Nothing mutates a
plan. Split from graphics_planner_longform to keep each file within the
300-logic-line budget (and to keep cutaway-only provably untouched).
"""

from __future__ import annotations

from planner.graphics_planner_density import reject_cand
from planner.graphics_planner_items import phrase, pip_aware_maps
from planner.motion_triggers import _word_text
from producer_config import MOTION
from planner import graphics_planner_longform as longform
from planner import graphics_planner_rules as rules

# --------------------------------------------------------------------------- #
# Constants — MOTION-shaped, module-local for now (belong in a future
# producer_config.MOTION["longform_cutaways"] block; see graphics_planner_
# longform for the rationale).
# --------------------------------------------------------------------------- #
TAKEOVER_BUCKET_S = 120.0       # top-1 thesis per 2 minutes keeps the takeover

# Overlays that may ride the talking head in THIS style (extends the pair-1
# single exception): the pair-2 grammar burns text at chest/free-band and
# stacks icons in headroom.
RICH_OVERLAY_KINDS = longform.OVERLAY_EXCEPTIONS | {"fragment-payoff",
                                                    "icon-badge"}

# MG-4.3 exemption, THIS STYLE ONLY: icon-badge is 9:16-authored but placed
# by region (see module docstring) — pair 2 proves headroom stacks on 16:9.
_CANVAS_EXEMPT = frozenset({"icon-badge"})

# fragment-payoff windowing around a number line: setup tokens scanned back,
# payoff tokens carried forward (both clamped to the containing sentence).
FRAG_BACKSCAN = 6
PAYOFF_FWD = 5
_SPLIT_PUNCT = (",", ":", ";", "—", "–")


# =========================================================================== #
# Retarget (mirrors longform.retarget's gauntlet, pair-2 grammar).
# =========================================================================== #
def retarget(candidates: list[dict],
             ctx: longform.Ctx) -> tuple[list[dict], list[dict]]:
    """(kept, rejected) — the overlay-rich remap → canvas → overlay gauntlet.

    Longform only (graphics_planner gates the call); structural list cutaways
    come from ``pip_aware_maps`` with its gate-legal long-list fallback."""
    wb_maps = _list_maps(ctx)
    wb_lists = longform.whiteboard_list_runs(ctx)
    aux = {"wb": wb_maps, "wb_lists": wb_lists,
           "winners": _takeover_winners(candidates, ctx),
           "ordinals": _boundary_ordinals(candidates)}
    kept, rejected = [], []
    for cand in candidates:
        status, obj = _retarget_one(cand, ctx, aux)
        (kept if status == "keep" else rejected).append(obj)
    kept.extend(wb_maps)
    kept.extend(wb_lists)
    return kept, rejected


def _list_maps(ctx: longform.Ctx) -> list[dict]:
    """Structural list cutaways, mode/canvas-gated like longform's scan."""
    if ctx.mode != "longform":
        return []
    return [c for c in pip_aware_maps(ctx)
            if longform.canvas_ok(c["kind"], ctx.aspect)]


def _retarget_one(cand: dict, ctx: longform.Ctx,
                  aux: dict) -> tuple[str, dict]:
    """One candidate through the pair-2 remap → canvas → overlay gauntlet."""
    th = longform._is_talking_head(cand, ctx)
    if cand["trigger"] == "topic-boundary" and ctx.aspect == "16:9":
        cand = _section_takeover(cand, aux["ordinals"])
    elif th:
        status, obj = _remap_rich(cand, ctx, aux)
        if status == "reject":
            return status, obj
        cand = obj
    if not _canvas_ok(cand["kind"], ctx.aspect):
        canvas = longform.kind_canvas().get(cand["kind"], "any")
        return "reject", reject_cand(cand, f"MG-4.3: {cand['kind']} authors on "
                                     f"a {canvas} canvas — target is {ctx.aspect}")
    if th and cand["anchor"] != "own-screen" \
            and cand["kind"] not in RICH_OVERLAY_KINDS:
        return "reject", reject_cand(cand, "R14(overlay-rich): only fragment-"
                                     "payoff burns, headroom icon stacks and "
                                     "the lower third ride the talking head")
    return "keep", cand


def _canvas_ok(kind: str, aspect: str) -> bool:
    return kind in _CANVAS_EXEMPT or longform.canvas_ok(kind, aspect)


def _remap_rich(cand: dict, ctx: longform.Ctx,
                aux: dict) -> tuple[str, dict]:
    """Pair-2 grammar for one talking-head longform candidate.

    Everything not overridden here (sequence, enumeration, chip-row entities)
    keeps the pair-1 mapping — pair 2 still cuts to whiteboard canvases and
    still refuses text chips floating on the face."""
    trigger = cand["trigger"]
    if trigger == "thesis":
        if id(cand) in aux["winners"]:
            return "keep", longform._thesis_quote(cand, ctx)
        return "keep", _fragment_payoff(cand, ctx, None)
    if trigger == "number":
        return "keep", _fragment_payoff(cand, ctx, "number")
    if trigger == "entity" and cand["kind"] == "icon-badge":
        return "keep", cand         # pair 2: headroom icon stacks are legal
    return longform._remap_talking_head(
        cand, ctx, aux["wb"], aux["wb_lists"])


def _takeover_winners(candidates: list[dict],
                      ctx: longform.Ctx) -> set[int]:
    """ids of the TOP-1 talking-head thesis per 2-minute bucket (R23 tiering:
    the takeover is the expensive tier; every other thesis burns as a
    fragment-payoff overlay). Rank: confidence, then the earlier line."""
    best: dict[int, dict] = {}
    for c in candidates:
        if c["trigger"] != "thesis" or not longform._is_talking_head(c, ctx):
            continue
        bucket = int(c["outStart"] // TAKEOVER_BUCKET_S)
        cur = best.get(bucket)
        if cur is None or _rank(c) > _rank(cur):
            best[bucket] = c
    return {id(c) for c in best.values()}


def _rank(cand: dict) -> tuple[int, float]:
    return (rules.conf_rank(cand["confidence"]), -cand["outStart"])


def _boundary_ordinals(candidates: list[dict]) -> dict[int, int]:
    """id → 1-based chapter ordinal for the topic-boundary candidates (time
    order). The brain renumbers at merge if the intro counts as chapter 1."""
    bounds = sorted((c for c in candidates if c["trigger"] == "topic-boundary"),
                    key=lambda c: c["outStart"])
    return {id(c): n for n, c in enumerate(bounds, start=1)}


# =========================================================================== #
# section-takeover (chapter cards).
# =========================================================================== #
def _section_takeover(cand: dict, ordinals: dict[int, int]) -> dict:
    """topic-boundary → section-takeover own-screen (pair-2 chapter grammar):
    ghost numeral = chapter ordinal, title = the boundary phrase, builds
    staggered at ~0.0/0.5/1.0 (numeral → title → subline slot)."""
    out = {k: v for k, v in cand.items() if k != "faceBBoxNorm"}
    out.update({
        "kind": "section-takeover", "anchor": "own-screen",
        "needsOperator": True,
        "spec": {"num": str(ordinals.get(id(cand), 1)),
                 "title": " ".join(cand["evidence"].split()[:5]),
                 "at1": 0.0, "at2": 0.5, "at3": 1.0},
        "reason": f"topic-boundary on “{cand['evidence']}” → section-takeover "
                  "(pair-2: ghost-numeral chapter card supersedes the "
                  "9:16-era stinger/glass-takeover kinds on 16:9; num = "
                  "chapter ordinal)"})
    return out


# =========================================================================== #
# fragment-payoff (R23 two-tier burns).
# =========================================================================== #
def _fragment_payoff(cand: dict, ctx: longform.Ctx,
                     payoff_from: str | None) -> dict:
    """Retargeted copy of ``cand`` as a fragment-payoff free-band overlay.

    ``payoff_from`` = "number" anchors the payoff at the number word;
    None (thesis) splits the containing sentence at its last clause break.
    When the word span is known the window re-anchors to the spoken words
    (the burn builds synced to speech) and ``payoffAt`` is word-timed;
    otherwise the trigger window is kept and the whole evidence burns as the
    payoff. The accent color is a per-video brand token — never in the spec."""
    out = {k: v for k, v in cand.items() if k != "faceBBoxNorm"}
    seg = _burn_segment(cand, ctx, payoff_from)
    if seg is None:
        fragment, payoff = "", cand["evidence"].strip()
        spec = {"fragment": fragment, "payoff": payoff}
    else:
        lo, hi, split = seg
        _anchor_window(out, ctx, lo, hi)
        fragment = phrase(ctx.words, lo, split - 1, 0) if split > lo else ""
        payoff = phrase(ctx.words, split, hi, 0)
        spec = {"fragment": fragment, "payoff": payoff,
                "payoffAt": round(max(0.0, float(ctx.words[split]["start"])
                                      - out["outStart"]), 2)}
    spec["align"] = _align(ctx, out["outStart"])
    out.update({
        "kind": "fragment-payoff", "anchor": "free-band", "spec": spec,
        "evidence": f"{fragment} {payoff}".strip(),
        "reason": f"{cand['trigger']} on “{cand['evidence']}” → "
                  "fragment-payoff (R23: two-tier burn, the cheaper tier "
                  "below the takeover; accent color = per-video brand token)"})
    return out


def _burn_segment(cand: dict, ctx: longform.Ctx,
                  payoff_from: str | None) -> tuple[int, int, int] | None:
    """(lo, hi, payoff_start) word indices for the burn, or None (no span)."""
    span = longform._containing_sentence(ctx.words, cand.get("_wi"))
    if span is None:
        return None
    if payoff_from == "number":
        n0 = cand["_wi"][0]
        return (max(span[0], n0 - FRAG_BACKSCAN),
                min(span[1], n0 + PAYOFF_FWD), n0)
    if span[1] - span[0] + 1 > longform.QUOTE_MAX_WORDS:
        return None                     # too long to burn — evidence fallback
    return span[0], span[1], _split_index(ctx.words, span)


def _split_index(words: list[dict], span: tuple[int, int]) -> int:
    """Word index where the payoff clause starts (R23 split heuristic):
    after the LAST mid-sentence clause break (comma/colon/dash); else at the
    first emphasis word in the sentence's back half; else the final 3 words."""
    lo, hi = span
    for k in range(hi - 1, lo, -1):
        if _word_text(words[k]).rstrip().endswith(_SPLIT_PUNCT):
            return k + 1
    emphasis = {w.lower() for w in
                longform.emphasis_words(phrase(words, lo, hi, 0))}
    half = lo + (hi - lo + 1) // 2
    for k in range(half, hi + 1):
        if _word_text(words[k]).strip(".,!?;:").lower() in emphasis:
            return k
    return max(lo + 1, hi - 2)


def _anchor_window(out: dict, ctx: longform.Ctx, lo: int, hi: int) -> None:
    """Re-anchor the graphic window to the spoken burn span (hold-bounded)."""
    hold_min = MOTION["hold_min_s"].get(ctx.mode, 1.0)
    hold_max = MOTION["hold_max_s"].get(ctx.mode, MOTION["hold_max_s"]["short"])
    start = float(ctx.words[lo]["start"])
    end = min(ctx.out_dur,
              max(float(ctx.words[hi]["end"]) + longform.QUOTE_EXIT_PAD_S,
                  start + hold_min),
              start + hold_max)
    out["outStart"], out["outEnd"] = round(start, 3), round(end, 3)


def _align(ctx: longform.Ctx, t: float) -> str:
    """The burn slides to the emptier side (R10/R23): opposite the face."""
    _, bbox = ctx.state_fn(t)
    if not bbox or len(bbox) != 4:
        return "center"
    face_cx = float(bbox[0]) + float(bbox[2]) / 2.0
    if face_cx > 0.55:
        return "left"
    if face_cx < 0.45:
        return "right"
    return "center"
