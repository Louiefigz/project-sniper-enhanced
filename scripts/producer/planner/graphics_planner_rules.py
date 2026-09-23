#!/usr/bin/env python3
"""graphics_planner_rules — trigger→template mapping + R12 legality (MG-4).

The "what graphic does this trigger earn, and is it doctrine-legal?" half of the
auto-graphics planner. Pure decision logic + data catalogs — no video, no
timeline math (that lives in ``graphics_planner``). Split out to keep each file
within the 300-logic-line budget. Doctrine sources: REFERENCE_STYLE_STUDY.md R12
(icon doctrine), PRODUCER_MOTION_GRAPHICS_PLAN.md §1 (trigger taxonomy) / §2.2
(short-vs-longform template columns).

Every function here PROPOSES; nothing renders or mutates a plan. The brain
reviews the proposal and the operator vetoes — see
.claude/skills/producer/SKILL.md ("Propose graphics" step).
"""

from __future__ import annotations

import os

from planner.icon_library import SLUG_MAP
from planner.motion_triggers import _clean
from producer_config import CAPTION_AUTO_CORRECTIONS, MOTION

# =========================================================================== #
# DATA (catalogs) — O(1) membership; exempt from the line limit.
# =========================================================================== #
PLANNER = MOTION["planner"]
_BLOCKLIST = frozenset(MOTION["generic_entity_blocklist"])

ICONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "..", "..", "..", "templates", "motion", "icons")

# An enumeration count that governs a MEASURE noun ("two years", "50 dollars")
# is a QUANTITY → stat-card; one governing a list noun ("three things") is a
# real list → list-build. These are the measure nouns that force the stat read.
UNIT_NOUNS = frozenset({
    "year", "years", "month", "months", "week", "weeks", "day", "days",
    "hour", "hours", "minute", "minutes", "second", "seconds",
    "dollar", "dollars", "buck", "bucks", "cent", "cents", "percent",
    "mile", "miles", "pound", "pounds", "kilogram", "kilograms", "kg",
    "gram", "grams", "foot", "feet", "inch", "inches", "x", "times",
})

# Trigger → (short template, longform template). Entities are handled separately
# (grouping + icon resolution live in graphics_planner). "enumeration" splits on
# UNIT_NOUNS at call time, so it is resolved in ``template_for`` not this table.
# ASPECT LEGALITY: each column must hold kinds legal on the mode's canvas
# (short → 9:16, longform → 16:9). This is ENFORCED downstream, not trusted:
# every candidate funnels through graphics_planner_longform.canvas_ok in the
# retarget gauntlet, which consults the MEASURED matrix
# (templates/motion/comp_capabilities.json via graphics.comp_capabilities.
# is_aspect_legal_kind) without a declared-dims fallback — a comp whose
# real canvas drifts from this table's assumption is rejected at propose time
# with the measured canvas named (LL-036/LL-037; a 16:9 comp composites raw +
# clipped on a 9:16 delivery). A NEW lane that bypasses the retarget must
# consume is_aspect_legal_kind itself, like form_allocation does.
# NOTE — deliberately TRIGGER-LESS kinds (pair-2 templates, 2026-07-06):
#   * glitch-hit: a 400ms alpha emphasis HIT. There is no transcript signal
#     that says "hit here" — auto-firing it on any detector reads as strobe,
#     not emphasis — so it is operator/brain-placed only.
#   * avatar-bio-card: a once-per-CHANNEL intro asset (dark bio takeover);
#     nothing in a single video's speech should trigger it — the operator
#     drops it into the plan by hand.
# Both are registered in graphics_planner_longform.KIND_CANVAS_FALLBACK so
# the MG-4.3 canvas filter and lint's comp-file check know the kinds.
# The pair-2 mapped kinds (fragment-payoff / section-takeover /
# canvas-pip-list) are NOT in this table either: they exist only under
# graphics_style="overlay-rich" and are remapped in graphics_planner_style,
# so the cutaway-only doctrine here stays byte-identical.
_TEMPLATE_BY_MODE = {"number": ("count-up", "chart-story"), "thesis": ("line-swap", None)}


# =========================================================================== #
# R12 entity legality.
# =========================================================================== #
def is_generic_entity(text: str) -> bool:
    """R12: True if the entity names a CATEGORY, not a specific product.

    Multi-word entities are generic only when EVERY word is generic ("AI tools"
    → generic; "Higgs Field" → specific because "field" is not blocklisted). A
    lone blocklisted token ("AI", "software") is generic.
    """
    words = _clean(text).split()
    if not words:
        return True
    return all(w in _BLOCKLIST for w in words)


def resolve_icon(name: str) -> str | None:
    """Local icon FILE (``<file>.svg``) for an entity name, or None.

    Plan-time lookup ONLY — never fetches (R12/#27: missing mark → chip-row
    fallback, noted in the proposal, so a network hiccup can't stall planning).
    Resolves via a cached file named for the entity, or a curated ``SLUG_MAP``
    alias whose mark is already cached under the entity's own name or its slug.
    """
    key = _clean(name)
    if not key:
        return None
    candidates = [key, key.replace(" ", "")]
    slug = SLUG_MAP.get(key) or SLUG_MAP.get(key.replace(" ", ""))
    if slug:
        candidates.append(slug)
    for cand in candidates:
        filename = f"{cand}.svg"
        if os.path.exists(os.path.join(ICONS_DIR, filename)):
            return filename
    return None


def classify_entity(text: str) -> tuple[str | None, str | None]:
    """Entities require an inspected catalog design, never an old badge fallback."""
    return None, resolve_icon(text)



# =========================================================================== #
# Trigger → template (non-entity triggers).
# =========================================================================== #
def template_for(trigger: str, text: str, mode: str) -> tuple[str | None, str | None]:
    """Offer only a verified catalog port; other needs go to native catalog discovery."""
    pair = _TEMPLATE_BY_MODE.get(trigger, (None, None))
    kind = pair[mode == "longform"]
    return kind, None if kind else "Select a matching upstream catalog component in a native project"



# =========================================================================== #
# Anchor preference from visual state (placement stays a RENDER-time decision;
# the planner only expresses a PREFERENCE the brain/lint later resolves).
# =========================================================================== #
def anchor_for(kind: str, state: str | None, mode: str) -> tuple[str, bool]:
    """Use footage geometry, never a retired template's house grammar."""
    from graphics.visual_source_policy import require_integrated
    require_integrated(kind)
    if state == "screen-share":
        return "own-screen", True
    return ("free-band" if mode == "longform" else "headroom"), state == "mixed"


# =========================================================================== #
# Seed specs (minimal, valid-shaped; the brain fills detail at merge).
# =========================================================================== #
def seed_spec(kind: str, text: str, land_s: float) -> dict:
    """Leave copy/data to the brain; validated catalog variables cannot be invented."""
    from graphics.visual_source_policy import require_integrated
    require_integrated(kind)
    return {}



def merged_corrections(plan_corrections: dict | None) -> dict:
    """Auto brand/casing fixes merged UNDER plan-level corrections (plan wins).

    Applied to entity spec text so a chip reads the real brand ("Hagen" →
    "HeyGen") rather than the ASR mishear — the same corrections captions use.
    """
    merged = dict(CAPTION_AUTO_CORRECTIONS)
    merged.update({k: v for k, v in (plan_corrections or {}).items()
                   if isinstance(k, str) and isinstance(v, str)})
    return merged


def apply_corrections(text: str, corrections: dict) -> str:
    """Case-insensitive whole-phrase substitution (longest key first)."""
    out = text
    for heard in sorted(corrections, key=len, reverse=True):
        corrected = corrections[heard]
        low_heard = heard.lower()
        idx = out.lower().find(low_heard)
        while idx != -1:
            out = out[:idx] + corrected + out[idx + len(heard):]
            idx = out.lower().find(low_heard, idx + len(corrected))
    return out


def conf_rank(confidence: str) -> int:
    """Numeric rank of a confidence tier (higher = stronger), 0 for unknown."""
    return PLANNER["confidence_rank"].get(confidence, 0)
