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
_TEMPLATE_BY_MODE = {
    "sequence":       ("list-build", "glass-rail"),
    "contrast":       ("versus-split", "versus-split"),
    "thesis":         ("kinetic-quote", "kinetic-quote"),
    "topic-boundary": ("section-marker", "glass-takeover-bg"),
}


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


def classify_entity(text: str) -> tuple[str, str | None]:
    """Entity → (kind, icon_file). ('reject', None) for a generic entity (R12).

    Specific + recognizable mark → icon-badge (R12 rule 2: bare mark beats
    chip+label). Specific but no known mark → chip-row (R12 rule 3: text is then
    the information). Generic → rejected entirely (R12 rule 1).
    """
    if is_generic_entity(text):
        return "reject", None
    icon = resolve_icon(text)
    return ("icon-badge", icon) if icon else ("chip-row", None)


# =========================================================================== #
# Trigger → template (non-entity triggers).
# =========================================================================== #
def template_for(trigger: str, text: str, mode: str) -> tuple[str | None, str | None]:
    """Map a non-entity trigger to a template kind for ``mode``.

    Returns ``(kind, note)``; ``note`` is a human hint carried into the proposal
    (e.g. why a longform takeover needs an operator). ``(None, None)`` = the
    planner has no template for this trigger (it becomes a rejected candidate).
    """
    longform = mode == "longform"
    idx = 1 if longform else 0
    if trigger == "enumeration":
        last = (_clean(text).split() or [""])[-1]
        if last in UNIT_NOUNS:
            return "stat-card", "count governs a measure noun — read as a quantity"
        return ("glass-rail" if longform else "list-build"), None
    if trigger == "number":
        return "stat-card", None
    pair = _TEMPLATE_BY_MODE.get(trigger)
    if not pair:
        return None, None
    kind = pair[idx]
    if trigger == "topic-boundary" and longform:
        return kind, "chapter takeover — heavier; operator confirms"
    return kind, None


# =========================================================================== #
# Anchor preference from visual state (placement stays a RENDER-time decision;
# the planner only expresses a PREFERENCE the brain/lint later resolves).
# =========================================================================== #
def anchor_for(kind: str, state: str | None, mode: str) -> tuple[str, bool]:
    """(anchor_preference, needs_operator) for a graphic given the zone's state.

    Doctrine (SKILL.md + plan_lint_motion): over a SCREEN-SHARE the screen is the
    star — overlays are illegal, so the planner proposes a cutaway (own-screen)
    and flags it for the operator. Over a TALKING-HEAD graphics live around the
    face (R3 headroom / beside-face) or centered in the free band (wide cards).
    MIXED is ambiguous → keep the talking-head preference but flag it.
    """
    longform = mode == "longform"
    if state == "screen-share":
        return "own-screen", True
    if kind in ("stinger-wipe", "glass-takeover-bg"):
        return "own-screen", longform
    needs = state == "mixed"
    if longform:
        return "free-band", needs            # 16:9 glass cards self-place
    if kind in ("versus-split", "kinetic-quote"):
        return "free-band", needs            # wide → centered free band
    if kind in ("list-build", "stat-card"):
        return "beside-face", needs
    return "headroom", needs                 # icon-badge / chip-row (R3)


# =========================================================================== #
# Seed specs (minimal, valid-shaped; the brain fills detail at merge).
# =========================================================================== #
def seed_spec(kind: str, text: str, land_s: float) -> dict:
    """A minimal spec for ``kind`` seeded from the spoken evidence ``text``.

    Proposals are reviewed before merge, so specs carry the raw spoken words in
    the right slot rather than invented copy — the brain refines them. ``land_s``
    is the entity/beat's time RELATIVE to the graphic's outStart (the ``atN``
    sync convention the templates use).
    """
    text = text.strip()
    at = round(max(0.0, land_s), 2)
    if kind == "stat-card":
        return {"value": text, "label": "", "count_up": True}
    if kind == "list-build":
        return {"item1": text, "at1": at, "chip_style": "check"}
    if kind == "glass-rail":
        return {"eyebrow": "", "num1": "1", "title1": text, "sub1": ""}
    if kind == "versus-split":
        return {"leftTitle": "", "rightTitle": "", "left1": text, "right1": "",
                "at1": at}
    if kind == "kinetic-quote":
        return {"quote": " ".join(text.split()[:8]), "bg": "dark", "highlight": ""}
    if kind == "stinger-wipe":
        return {"title": " ".join(text.split()[:5])}
    if kind == "section-marker":
        # Headroom section header (shorts): the brain writes the eyebrow ("System
        # No.2") + a real title/qualifier at merge — the boundary words only seed
        # the title slot so an un-refined marker still reads.
        return {"num": "", "line1": " ".join(text.split()[:4]), "line2": ""}
    if kind == "glass-takeover-bg":
        return {"eyebrow": "", "title": " ".join(text.split()[:5])}
    if kind == "glass-lower-third":
        return {"eyebrow": "", "titleBase": text, "titleHighlight": ""}
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
