#!/usr/bin/env python3
"""edit_scope — resolve the operator's EDIT SCOPE + per-lane directives.

The skill is MALLEABLE: the operator can ask for a PIECE (just trim the silences)
or the WHOLE thing (full auto), and can override any single lane ("no b-roll",
"use my b-roll", "I'll supply the graphics"). This module turns ``target.scope`` +
``target.lanes`` into the active-lane map every downstream stage (the Hook
Contract, the graphics/motion planners) reads to know what is in force. It is the
single source of truth for "what did the operator actually ask us to do".

Scope ladder — each tier activates more lanes:
  trim     — cut + trim silences/retakes only (no engagement stack)
  light    — + subtle motion + captions
  produced — the full engaging stack using AVAILABLE assets: importance-pushes,
             graphics (cards/chips), transitions, credibility move, AND b-roll
             cutaways from the operator's pool
  full     — produced + GENERATE/source what's missing to cover every beat
             (generated b-roll, product-UI graphics, body montages). Same emit
             lanes as produced today; the generative lanes are roadmap, so a
             `full` job currently proposes the same set — the distinction is
             "engage with what you have" (produced) vs "spare no effort" (full).

A per-lane directive in ``target.lanes`` ALWAYS wins over the scope:
  "off"      — the operator waived it (don't add; the contract won't require it)
  "operator" — the operator will supply it (defer; the obligation is met off-system)
  "auto"     — the system owns the editorial decision (the default when the
               scope activates the lane); a conditional lane may explicitly
               decide that no effect earns a slot
  [ids...]   — operator-chosen assets (broll/graphics): treated as supplied
"""
from __future__ import annotations

# The engagement lanes the operator can scope or override. The base cut (trim +
# reframe) is ALWAYS on and is not a lane.
LANES = ("motion", "graphics", "transitions", "captions", "broll", "credibility")

SCOPES: dict[str, dict[str, bool]] = {
    "trim":     dict(motion=False, graphics=False, transitions=False,
                     captions=False, broll=False, credibility=False),
    "light":    dict(motion=True,  graphics=False, transitions=False,
                     captions=True,  broll=False, credibility=False),
    "produced": dict(motion=True,  graphics=True,  transitions=True,
                     captions=True,  broll=True,  credibility=True),
    "full":     dict(motion=True,  graphics=True,  transitions=True,
                     captions=True,  broll=True,  credibility=True),
}
SCOPE_DEFAULT = "produced"
# Back-compat: the older ``target.treatment`` axis maps onto a scope.
_TREATMENT_TO_SCOPE = {"clean-cut": "trim", "produced": "produced"}
# Only these lanes accept operator-supplied ASSET LISTS; the rest take a word.
_ASSET_LANES = frozenset({"broll", "graphics"})
_DIRECTIVE_WORDS = frozenset({"off", "operator", "auto"})


def resolve_scope(target: dict | None) -> str:
    """The scope name: explicit ``target.scope``, else mapped from ``treatment``,
    else the default ("produced"). A PRESENT-but-unknown scope/treatment RAISES —
    a typo like ``"trm"`` must not silently run the full produced stack (no-fallback
    rule); an absent scope legitimately defaults."""
    t = target or {}
    if "scope" in t:
        if t["scope"] not in SCOPES:
            raise ValueError(f"unknown scope {t['scope']!r} — one of {sorted(SCOPES)}")
        return t["scope"]
    tr = t.get("treatment")
    if tr is not None and tr not in _TREATMENT_TO_SCOPE:
        raise ValueError(f"unknown treatment {tr!r} — one of {sorted(_TREATMENT_TO_SCOPE)}")
    return _TREATMENT_TO_SCOPE.get(tr, SCOPE_DEFAULT)


def _validate_overrides(overrides: dict) -> None:
    """Raise on any malformed per-lane directive — an unknown lane name, a garbage
    value, an asset list on a non-asset lane, or an empty list. Silently swallowing
    these turned a typo'd "no b-roll" into b-roll staying ON (no-fallback rule)."""
    for lane, d in overrides.items():
        if lane not in LANES:
            raise ValueError(f"unknown lane {lane!r} — one of {sorted(LANES)}")
        if isinstance(d, list):
            if lane not in _ASSET_LANES:
                raise ValueError(f"lane {lane!r} takes a directive word, not an asset "
                                 f"list (lists only for {sorted(_ASSET_LANES)})")
            if not d:
                raise ValueError(f"lane {lane!r} asset list is empty — use 'off' to waive")
        elif d not in _DIRECTIVE_WORDS:
            raise ValueError(f"lane {lane!r} directive {d!r} invalid — one of "
                             f"{sorted(_DIRECTIVE_WORDS)} or a non-empty asset list")


def resolve_lanes(target: dict | None) -> dict:
    """Active state per lane after applying scope + per-lane directives.

    Returns ``{lane: state}`` where state is ``"auto"`` (system owns it), ``"off"``
    (not present), ``"operator"`` (operator supplies), or a ``list`` of asset ids.
    A directive overrides the scope; ``"auto"`` only takes effect if the scope
    actually activates the lane (you cannot ``auto`` a lane a ``trim`` job excludes).
    Malformed directives RAISE (see ``_validate_overrides``)."""
    base = SCOPES[resolve_scope(target)]
    overrides = (target or {}).get("lanes") or {}
    _validate_overrides(overrides)
    out: dict[str, object] = {}
    for lane in LANES:
        d = overrides.get(lane)
        if isinstance(d, list) or d in ("off", "operator"):
            out[lane] = d
        else:
            out[lane] = "auto" if base[lane] else "off"
    return out


def lane_required(target: dict | None, lane: str) -> bool:
    """True iff the SYSTEM owns this lane's editorial decision.

    The lane's contract decides how to discharge that obligation. Most automatic
    lanes require render evidence; a transition-free intro requires a time-bound,
    evidence-backed clean-hook receipt rather than an empty list. ``"off"``/
    ``"operator"`` and operator assets discharge ownership before authoring.
    """
    return resolve_lanes(target).get(lane) == "auto"
