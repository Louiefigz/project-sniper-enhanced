#!/usr/bin/env python3
"""graphics_planner_longform — MG-4.3 canvas filter + R14/R18 retarget.

Doctrine (REFERENCE_STYLE_STUDY.md R14/R17/R18; audit record in
docs/audits/INTRO_MACHINE_VS_PRO_AUDIT.md §2/§6/§7): in the cutaway-only
talking-head LONGFORM grammar no panel floats over the face.
Enumerations/stories earn FULL-FRAME whiteboard cutaways, theses earn dark
takeovers or burned kinetic quotes, and artifact mentions
("my YouTube channel", "an SEO company") earn receipts b-roll. This module
retargets the generic trigger→template candidates for that grammar:

* CANVAS FILTER (MG-4.3): every template kind carries a canvas ("9:16" /
  "16:9" / "any"); a kind authored on a canvas that doesn't match the render
  target's aspect is NEVER proposed. Canvases are DERIVED at first use by
  reading each comp's ``data-width``/``data-height`` from
  templates/motion/compositions/*.html (bucketed by ORIENTATION, so the map
  tracks the comps as they're edited), merged OVER a hardcoded fallback that
  also covers build-queue kinds with no comp file yet (whiteboard-map /
  whiteboard-list / kinetic-quote-wide). Chosen over a pure hardcoded map so
  a rebuilt comp can't silently drift out of sync with the filter.
* R14 (talking-head longform): overlay kinds are DROPPED — glass-lower-third
  is the single allowed exception (lower band, off-face; the audit's one
  approved v1 graphic). Enumerations with 3+ extractable items become
  whiteboard-map cutaways (graphics_planner_items), sequence/process beats
  whiteboard-list cutaways, theses kinetic-quote-wide burns — all own-screen.
* R17 receipts live in graphics_planner_receipts (the b-roll lane).
* Own-screen density: cutaways are expensive attention moves — hook-window-
  aware budget (see OWN_SCREEN below), never in the first 3s / last 5s.

THE graphics_style AXIS (pair-2 study, R14 CONTRADICTION callout): R14 is NOT
a universal law — it is a PER-VIDEO STYLE AXIS. This module IS the
"cutaway-only" doctrine (pair-1). "overlay-rich" (pair-2: fragment-
payoff burns over the face, headroom icon stacks, section-takeover chapter
cards, gate-legal long-list cutaways, concept-stock b-roll) lives in
graphics_planner_style; ``resolve_style`` below picks the doctrine
(param > plan.target.graphicsStyle, with a legacy default only outside
produced/full longform) and graphics_planner dispatches. The planner carries
the axis; it never guesses the produced/full longform grammar.

PROPOSES only, like the rest of MG-4 — nothing here mutates a plan.
"""

from __future__ import annotations

import os
import re
import string
from dataclasses import dataclass
from typing import Callable

from edit_scope import lane_required, resolve_scope
from graphics.comp_capabilities import (
    is_aspect_legal_kind,
    measured_aspect,
)
from planner.graphics_planner_density import reject_cand
from planner.graphics_planner_items import phrase, whiteboard_maps as _scan_maps
from planner.graphics_planner_sequences import sequence_beats as _scan_beats
from planner.motion_triggers import NUMBER_WORDS, _clean, _ends_sentence, _word_text
from producer_config import MOTION
from planner import graphics_planner_rules as rules

# =========================================================================== #
# Constants — MOTION-shaped, kept MODULE-LOCAL for now. These belong in a
# producer_config.MOTION["longform_cutaways"] block once the doctrine settles;
# module-local so this retarget ships without touching the shared config
# (operator instruction 2026-07-06).
# =========================================================================== #
NATURAL_ASPECT = {"short": "9:16", "longform": "16:9"}

# The R14 contradiction, operator-visible (REFERENCE_STYLE_STUDY.md R22 and
# the "R14 contradiction" callout): the owner's own long-form edits use more
# than one legitimate graphic grammar. Produced/full longform must carry an
# explicit choice plus the editorial rationale; lighter/short work retains
# the legacy default because the rich longform grammar is not in force there.
STYLES = ("cutaway-only", "overlay-rich", "face-bridge")
DEFAULT_STYLE = "cutaway-only"

_COMPS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "..", "..", "..", "templates", "motion", "compositions")
_DIM_RE = re.compile(r'data-(width|height)="(\d+)"')

# Fallback canvases — used when a comp file is missing/unreadable, and for the
# R14 build-queue kinds that have no comp yet (whiteboard-map, whiteboard-list,
# kinetic-quote-wide). Derived entries (from the comp files) win over these.
# Data catalog — exempt from the logic line limit.
KIND_CANVAS_FALLBACK = {
    "agenda-slide": "16:9", "blur-tease": "9:16", "chip-row": "9:16",
    "color-wash": "16:9", "glass-lower-third": "16:9", "glass-rail": "16:9",
    "glass-takeover-bg": "16:9", "icon-badge": "9:16",
    "kinetic-quote": "9:16", "kinetic-quote-wide": "16:9",
    "list-build": "9:16", "logo-card": "16:9", "schedule-stack": "9:16",
    "section-marker": "9:16", "stat-card": "9:16", "statement-card": "16:9",
    "stinger-wipe": "9:16", "underline-circle": "9:16",
    "versus-split": "9:16", "whiteboard-connector": "16:9",
    "whiteboard-list": "16:9", "whiteboard-map": "16:9",
    "widget-gauge": "9:16", "widget-pills": "9:16",
    # Pair-2 kinds (templates shipped 2026-07-06). fragment-payoff /
    # section-takeover / canvas-pip-list are mapped by graphics_planner_style
    # (overlay-rich only). glitch-hit and avatar-bio-card deliberately have NO
    # planner trigger anywhere in MG-4 — glitch-hit is a 400ms operator/brain-
    # only emphasis hit (no transcript signal says "hit here"; auto-firing it
    # reads strobe), avatar-bio-card is a once-per-channel intro asset the
    # operator drops in by hand. Both are registered so the canvas filter and
    # lint's comp-file check know the kinds when a plan carries them.
    "avatar-bio-card": "16:9", "canvas-pip-list": "16:9",
    "fragment-payoff": "16:9", "glitch-hit": "16:9",
    "section-takeover": "16:9",
    # Primitives (editor Elements > Primitives, 2026-07-09): bare placeable
    # text / rounded-container building blocks. NO planner trigger anywhere —
    # operator/brain-only layout pieces dropped via the editor + placement.
    "text-element": "9:16", "text-element-wide": "16:9",
    "container-shape": "9:16", "container-shape-wide": "16:9",
    # Hand-drawn (hw) family (catalog port wave A, 2026-08-28): deliberately
    # TRIGGER-LESS, same doctrine as glitch-hit — a marker stroke needs the
    # brain to pick the emphasized WORD, a callout circle needs a REGION of
    # the frame, and no transcript detector earns either; auto-firing them
    # reads as noise, not emphasis. hw-scribble-transition is a seam-cover
    # stinger the brain/operator places spanning a cut (alpha sibling of
    # stinger-wipe). Registered so the canvas filter and lint's comp-file
    # check know the kinds when a plan carries them.
    "marker-highlight": "9:16", "hw-callout-circle": "9:16",
    "hw-scribble-transition": "9:16",
    # Catalog data/hook/screen family (port wave B, 2026-08-28). chart-story
    # and count-up join MOTION["card_form_map"] (information-shape data
    # cards: trend/comparison charts + hero-metric counter) and line-swap
    # joins the thesis family — the brain selects them by shape; no
    # transcript trigger fires them. ui-focus-zoom is deliberately
    # TRIGGER-LESS everywhere (glitch-hit doctrine): it needs a
    # brain-supplied screenshot asset (spec.image) plus an anchor region,
    # and no transcript detector earns either. Registered so the canvas
    # filter and lint's comp-file check know the kinds.
    "chart-story": "16:9", "count-up": "9:16",
    "line-swap": "9:16", "ui-focus-zoom": "16:9",
}

# Own-screen cutaway density. HOOK WINDOW: operator doctrine (2026-07-06):
# "the intro has far more animations/edits than the rest of the video —
# typically the first 2 minutes or so is to increase retention". Audit §2
# agrees: 10 pro cutaways in the first ~126s (~1/25-30s), settling to ~2/min.
# Body numbers: cutaways are EXPENSIVE attention moves — 1 per 45s, 15s apart.
HOOK_WINDOW_S = 120.0
OWN_SCREEN = {
    "hook": {"per_s": 27.5, "min_spacing_s": 10.0},   # first HOOK_WINDOW_S
    "body": {"per_s": 45.0, "min_spacing_s": 15.0},
    "edge_start_s": 3.0,        # never open on a cutaway
    "edge_end_s": 5.0,          # never end inside one
}

# R14: the single overlay allowed over a talking head (lower band, off-face).
OVERLAY_EXCEPTIONS = frozenset({"glass-lower-third"})

# R18 kinetic burns: the full thesis sentence when it's short enough to burn
# word-by-word; a longer ramble keeps the trigger span as a burnable fragment.
QUOTE_MAX_WORDS = 16
QUOTE_EXIT_PAD_S = 1.0

# R18 emphasis heuristic vocab. Data catalogs — exempt from the line limit.
NEGATION_WORDS = frozenset({"not", "no", "never", "nothing", "nobody", "none",
                            "don't", "doesn't", "didn't", "won't", "can't",
                            "cannot", "couldn't", "shouldn't", "wouldn't",
                            "isn't", "aren't", "wasn't", "weren't"})
_EMPHASIS_STOP = frozenset({"the", "a", "an", "and", "or", "but", "of", "to",
                            "for", "with", "in", "on", "at", "by", "is",
                            "was", "are", "were", "be", "been", "that",
                            "this", "these", "those", "you", "we", "it",
                            "they", "he", "she", "i", "so", "as", "if",
                            "from", "into", "than", "your", "my", "our"})
EMPHASIS_MAX = 3


@dataclass(frozen=True)
class Ctx:
    """Retarget context: the output-time words + target parameters."""
    words: list
    mode: str
    aspect: str
    state_fn: Callable
    out_dur: float
    style: str = DEFAULT_STYLE      # graphics_style axis (see resolve_style)


# =========================================================================== #
# Canvas map (MG-4.3).
# =========================================================================== #
_canvas_cache: dict[str, str] | None = None


def kind_canvas() -> dict[str, str]:
    """kind → canvas, derived from the comp files merged over the fallback."""
    global _canvas_cache
    if _canvas_cache is None:
        _canvas_cache = dict(KIND_CANVAS_FALLBACK)
        _canvas_cache.update(_derive_canvases())
    return _canvas_cache


def _derive_canvases() -> dict[str, str]:
    """Read data-width/data-height per comp; bucket by orientation."""
    try:
        names = os.listdir(_COMPS_DIR)
    except OSError:
        return {}
    out: dict[str, str] = {}
    for name in sorted(names):
        if not name.endswith(".html"):
            continue
        dims = _comp_dims(os.path.join(_COMPS_DIR, name))
        if dims:
            out[name[:-5]] = _canvas_of(*dims)
    return out


def _comp_dims(path: str) -> tuple[int, int] | None:
    """(width, height) from a comp's data-* attributes, or None."""
    try:
        with open(path, encoding="utf-8") as handle:
            found = dict(_DIM_RE.findall(handle.read()))
    except OSError:
        return None
    if "width" in found and "height" in found:
        return int(found["width"]), int(found["height"])
    return None


def _canvas_of(width: int, height: int) -> str:
    return "16:9" if width > height else ("9:16" if height > width else "any")


def canvas_ok(kind: str, aspect: str) -> bool:
    """MG-4.3: a kind is proposable only on its own canvas ('any' = both).

    The fresh MEASURED matrix is authoritative. Declared dimensions drifted
    from rendered canvases through the 2026-07-23 mint cycles
    (LL-036/LL-037), so unavailable/unmeasured/error kinds are not proposed.
    """
    return is_aspect_legal_kind(kind, aspect)


def effective_canvas(kind: str) -> str:
    """The canvas the filter judged ``kind`` by (measured wins, for messages)."""
    return measured_aspect(kind) or "unavailable"


def natural_aspect(mode: str) -> str:
    return NATURAL_ASPECT.get(mode, "9:16")


def resolve_aspect(aspect: str | None, plan: dict, mode: str) -> str:
    """Param > plan.target.aspect > the mode's natural aspect."""
    if aspect:
        return aspect
    return (plan.get("target") or {}).get("aspect") or natural_aspect(mode)


def resolve_style(style: str | None, plan: dict) -> str:
    """Resolve the R14 style axis without guessing produced longform intent.

    A produced/full longform plan must explicitly state ``graphicsStyle`` (or
    receive the CLI/API ``style`` argument) and persist a non-empty
    ``target.graphicsStyleRationale``. Short, trim, and light work retain the
    legacy cutaway-only default because this longform doctrine fork is not an
    active production decision for those paths.
    """
    target = plan.get("target") or {}
    strict = target.get("mode") == "longform" and \
        resolve_scope(target) in ("produced", "full") and \
        lane_required(target, "graphics")
    got = style or target.get("graphicsStyle")
    if strict and not got:
        raise ValueError("produced/full longform requires explicit "
                         "target.graphicsStyle "
                         "(cutaway-only|overlay-rich|face-bridge); "
                         "the planner may not guess the visual grammar")
    if strict and not str(target.get("graphicsStyleRationale") or "").strip():
        raise ValueError("produced/full longform requires non-empty "
                         "target.graphicsStyleRationale explaining why the "
                         "selected visual grammar fits this edit")
    got = got or DEFAULT_STYLE
    if got not in STYLES:
        raise ValueError(f"unknown graphics style {got!r} — expected one of "
                         f"{'|'.join(STYLES)} (R14 style axis)")
    from graphics.style_profiles import target_errors
    issues = target_errors({**target, "graphicsStyle": got})
    if issues:
        raise ValueError(issues[0])
    return got


# =========================================================================== #
# Retarget: canvas filter + R14 talking-head grammar.
# =========================================================================== #
def retarget(candidates: list[dict], ctx: Ctx) -> tuple[list[dict], list[dict]]:
    """(kept, rejected) after canvas filtering + R14 longform retargeting.

    kept additionally contains structural whiteboard-map cutaways (3+ coordinated
    items) and whiteboard-list cutaways (2+ clustered sequence steps), both built
    from the words with no spoken count needed."""
    wb_maps = whiteboard_maps(ctx)
    wb_lists = whiteboard_list_runs(ctx)
    kept, rejected = [], []
    for cand in candidates:
        status, obj = _retarget_one(cand, ctx, wb_maps, wb_lists)
        (kept if status == "keep" else rejected).append(obj)
    kept.extend(wb_maps)
    kept.extend(wb_lists)
    return kept, rejected


def whiteboard_maps(ctx: Ctx) -> list[dict]:
    """Structural listed-items scan (graphics_planner_items), mode/canvas-gated."""
    if ctx.mode != "longform" or not canvas_ok("whiteboard-map", ctx.aspect):
        return []
    return _scan_maps(ctx.words, ctx.mode, ctx.state_fn, ctx.out_dur)


def whiteboard_list_runs(ctx: Ctx) -> list[dict]:
    """Sequence-ordinal clusters → candidate whiteboard-list BEATS
    (graphics_planner_sequences), mode/canvas-gated. Each beat carries
    ``needsCopy`` and no copy — the BRAIN writes its items in the skill flow
    (reads rawSpan, drops non-lists, calls graphics_copy.fill_list_spec)."""
    if ctx.mode != "longform" or not canvas_ok("whiteboard-list", ctx.aspect):
        return []
    return _scan_beats(ctx.words, ctx.mode, ctx.state_fn, ctx.out_dur)


def _retarget_one(cand: dict, ctx: Ctx, wb_maps: list[dict],
                  wb_lists: list[dict]) -> tuple[str, dict]:
    """One candidate through the R14 remap → canvas → overlay-drop gauntlet."""
    th = _is_talking_head(cand, ctx)
    if th:
        status, obj = _remap_talking_head(cand, ctx, wb_maps, wb_lists)
        if status == "reject":
            return status, obj
        cand = obj
    if not canvas_ok(cand["kind"], ctx.aspect):
        canvas = effective_canvas(cand["kind"])
        return "reject", reject_cand(cand, f"MG-4.3: {cand['kind']} authors on "
                                     f"a {canvas} canvas — target is {ctx.aspect}")
    if th and cand["anchor"] != "own-screen" \
            and cand["kind"] not in OVERLAY_EXCEPTIONS:
        return "reject", reject_cand(cand, "R14: no overlay over a talking "
                                     "head — the frame belongs to the subject "
                                     "or to the canvas, never both")
    return "keep", cand


def _is_talking_head(cand: dict, ctx: Ctx) -> bool:
    if ctx.mode != "longform":
        return False
    state, _ = ctx.state_fn(cand["outStart"])
    # Untagged longform defaults to talking-head — identical to
    # graphics_planner_density.suggest_treatment_map's `state or "talking-head"`.
    # R14 protects the FACE by default; only an EXPLICIT screen-share/mixed tag
    # opts a zone out of the cutaway grammar. Without this, an untagged plan (the
    # propose-phase norm — visual_state.py tags at MERGE, AFTER this retarget)
    # leaves every overlay candidate un-retargeted and glass-rail floats over the
    # face (the C0679 occlusion). The expensive mistake is a panel over the face.
    return (state or "talking-head") == "talking-head"


def _remap_talking_head(cand: dict, ctx: Ctx, wb_maps: list[dict],
                        wb_lists: list[dict]) -> tuple[str, dict]:
    """R14 grammar for one talking-head longform candidate."""
    trigger = cand["trigger"]
    if trigger == "sequence":
        if _duration_ordinal(cand, ctx):
            return "reject", reject_cand(cand, "ordinal rides a number "
                                         "('…ninety second…') — a duration, "
                                         "not a process beat")
        cover = _covering(wb_lists, cand["outStart"])
        if cover is not None:
            return "reject", reject_cand(cand, "folded into the whiteboard-list "
                                         f"at {cover:.1f}s")
        return "reject", reject_cand(cand, "R14: lone ordinal — not a real "
                                     "sequence run (bare modifier / discourse "
                                     "marker), earns nothing over a talking head")
    if trigger == "thesis":
        return "keep", _thesis_quote(cand, ctx)
    if trigger == "enumeration":
        cover = _covering(wb_maps, cand["outStart"])
        if cover is not None:
            return "reject", reject_cand(cand, "folded into the whiteboard-map "
                                         f"at {cover:.1f}s")
        return "reject", reject_cand(cand, "R14: enumeration without 3+ "
                                     "extractable items earns NOTHING over a "
                                     "talking head (R14: an agenda needs "
                                     "real items)")
    if trigger == "entity" and cand["kind"] in ("icon-badge", "chip-row"):
        return "reject", reject_cand(cand, "R14: no badge/chip floats over the "
                                     "face — showable artifacts ride the "
                                     "b-roll receipts lane (R17)")
    return "keep", cand


def _thesis_quote(cand: dict, ctx: Ctx) -> dict:
    """thesis → kinetic-quote-wide (R14/R18). ``words`` = the full thesis
    sentence when it's burnable (≤ QUOTE_MAX_WORDS — the burn builds word-by-
    word synced to speech, so the window re-anchors to the spoken sentence);
    a longer sentence keeps the trigger span as the burnable fragment."""
    out = _as_cutaway(cand, "kinetic-quote-wide", {},
                      "R14/R18: thesis → burned kinetic quote")
    text = cand["evidence"]
    span = _containing_sentence(ctx.words, cand.get("_wi"))
    if span and span[1] - span[0] + 1 <= QUOTE_MAX_WORDS:
        text = phrase(ctx.words, span[0], span[1], 0)
        hold_max = MOTION["hold_max_s"].get(ctx.mode,
                                            MOTION["hold_max_s"]["short"])
        start = float(ctx.words[span[0]]["start"])
        end = min(ctx.out_dur,
                  float(ctx.words[span[1]]["end"]) + QUOTE_EXIT_PAD_S,
                  start + hold_max)
        out["outStart"], out["outEnd"] = round(start, 3), round(end, 3)
        out["evidence"] = text
    out["spec"] = {"words": text, "emphasisWords": emphasis_words(text)}
    return out


def _containing_sentence(words: list[dict],
                         wi: list | None) -> tuple[int, int] | None:
    """(start, end) word span of the sentence containing ``wi``'s anchor."""
    if not wi:
        return None
    i = j = wi[0]
    while i > 0 and not _ends_sentence(_word_text(words[i - 1])):
        i -= 1
    while j < len(words) - 1 and not _ends_sentence(_word_text(words[j])):
        j += 1
    return i, j


def _duration_ordinal(cand: dict, ctx: Ctx) -> bool:
    """True when a sequence ordinal is governed by a number ("ninety second
    video") — a duration reading, not a process beat. Uses the candidate's
    output-word indices (``_wi``, planner-internal)."""
    wi = cand.get("_wi")
    if not wi or wi[0] == 0:
        return False
    prev = _clean(_word_text(ctx.words[wi[0] - 1]))
    return prev in NUMBER_WORDS or any(ch.isdigit() for ch in prev)


def _as_cutaway(cand: dict, kind: str, spec: dict, note: str) -> dict:
    """Retargeted copy of ``cand``: full-frame own-screen cutaway."""
    out = {k: v for k, v in cand.items() if k != "faceBBoxNorm"}
    out.update({"kind": kind, "spec": spec, "anchor": "own-screen",
                "needsOperator": True,
                "reason": f"{cand['trigger']} on “{cand['evidence']}” → "
                          f"{kind} ({note})"})
    return out


def _covering(wb_maps: list[dict], t: float) -> float | None:
    for wb in wb_maps:
        if wb["outStart"] <= t < wb["outEnd"]:
            return wb["outStart"]
    return None


# =========================================================================== #
# R18 emphasis heuristic (kinetic-quote-wide).
# =========================================================================== #
def emphasis_words(text: str) -> list[str]:
    """1-3 payoff words for a burned quote (R18), by priority tier:
    (1) numerals — digit tokens or spelled cardinals; (2) negations ("not",
    "nothing" — the reversal is the payoff); (3) the last content word, a
    cheap stand-in for the final noun phrase's head ("…could actually
    survive." → "survive"). First-seen order inside each tier, capped at 3."""
    toks = [t.strip(string.punctuation) for t in text.split()]
    toks = [t for t in toks if t]
    picks = [t for t in toks
             if any(ch.isdigit() for ch in t) or t.lower() in NUMBER_WORDS]
    picks += [t for t in toks if t.lower() in NEGATION_WORDS and t not in picks]
    final = _final_content_word(toks)
    if final and final not in picks and len(picks) < EMPHASIS_MAX:
        picks.append(final)
    return picks[:EMPHASIS_MAX]


def _final_content_word(toks: list[str]) -> str | None:
    for t in reversed(toks):
        low = t.lower()
        if t.isalpha() and low not in _EMPHASIS_STOP \
                and low not in NEGATION_WORDS:
            return t
    return None


# =========================================================================== #
# Own-screen cutaway density (hook-window-aware).
# =========================================================================== #
def trim_own_screen(accepted: list[dict], mode: str,
                    out_dur: float) -> tuple[list[dict], list[dict]]:
    """Cap own-screen cutaways: hook window (first HOOK_WINDOW_S) runs
    ~1/27.5s with 10s spacing (operator retention doctrine + audit §2), the
    body 1/45s with 15s spacing; never in the first 3s / last 5s. Greedy
    rank-first, like density.trim."""
    if mode != "longform":
        return accepted, []
    own = [c for c in accepted if c.get("anchor") == "own-screen"]
    ranked = sorted(own, key=lambda c: (-rules.conf_rank(c["confidence"]),
                                        c["outStart"]))
    state = {"starts": [], "counts": {"hook": 0, "body": 0},
             "budgets": _own_screen_budgets(out_dur), "out_dur": out_dur}
    keep_ids: set[int] = set()
    rejected: list[dict] = []
    for cand in ranked:
        why = _own_screen_verdict(cand, state)
        if why:
            rejected.append(reject_cand(cand, why))
            continue
        state["counts"][_window(cand["outStart"])] += 1
        state["starts"].append(cand["outStart"])
        keep_ids.add(id(cand))
    kept = [c for c in accepted
            if c.get("anchor") != "own-screen" or id(c) in keep_ids]
    return kept, rejected


def _own_screen_budgets(out_dur: float) -> dict[str, int]:
    hook_len = min(out_dur, HOOK_WINDOW_S)
    body_len = max(0.0, out_dur - HOOK_WINDOW_S)
    body = int(body_len // OWN_SCREEN["body"]["per_s"])
    return {"hook": max(1, int(hook_len // OWN_SCREEN["hook"]["per_s"])),
            "body": max(1, body) if body_len > 0 else 0}


def own_screen_cap(out_dur: float) -> int:
    """Total own-screen cutaway budget for a longform of ``out_dur`` — hook +
    body (the SAME budget ``trim_own_screen`` enforces). Exposed so plan_lint
    caps takeovers with the proposer's retention-doctrine budget rather than a
    stricter flat/linear count that the proposer would routinely exceed."""
    return sum(_own_screen_budgets(out_dur).values())


def _window(t: float) -> str:
    return "hook" if t < HOOK_WINDOW_S else "body"


def _own_screen_verdict(cand: dict, state: dict) -> str | None:
    """Reject reason for an own-screen candidate, or None to accept."""
    start, win = cand["outStart"], _window(cand["outStart"])
    if start < OWN_SCREEN["edge_start_s"]:
        return f"own-screen inside the first {OWN_SCREEN['edge_start_s']:.0f}s"
    if cand["outEnd"] > state["out_dur"] - OWN_SCREEN["edge_end_s"]:
        return f"own-screen inside the last {OWN_SCREEN['edge_end_s']:.0f}s"
    spacing = OWN_SCREEN[win]["min_spacing_s"]
    near = [s for s in state["starts"] if abs(s - start) < spacing]
    if near:
        return (f"own-screen {abs(near[0] - start):.1f}s from the cutaway at "
                f"{near[0]:.1f}s (< {spacing:.0f}s {win}-window spacing)")
    if state["counts"][win] >= state["budgets"][win]:
        per = OWN_SCREEN[win]["per_s"]
        return (f"own-screen {win}-window budget full "
                f"({state['budgets'][win]} ≈ 1 per {per:.0f}s)")
    return None


def density_note() -> str:
    """One table line: which own-screen budget applied where (for the brain)."""
    hook, body = OWN_SCREEN["hook"], OWN_SCREEN["body"]
    return (f"own-screen density: hook 0-{HOOK_WINDOW_S:.0f}s = "
            f"1/{hook['per_s']:.0f}s, {hook['min_spacing_s']:.0f}s spacing "
            "(operator retention doctrine + audit §2); body = "
            f"1/{body['per_s']:.0f}s, {body['min_spacing_s']:.0f}s spacing; "
            f"edges {OWN_SCREEN['edge_start_s']:.0f}s/"
            f"{OWN_SCREEN['edge_end_s']:.0f}s")
