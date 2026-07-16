#!/usr/bin/env python3
"""plan_lint_nateherk — lint for the NATEHERK longform lane (§5 items 8-9).

OPERATOR ADJUDICATION (2026-07-10): the rail-push beside the live face (item
8, T-B) and the dark takeover with the face in a rounded PIP card (item 9,
T-C/§3 rank 11) are LEGAL FOR LONGFORM and stay BANNED FOR SHORTS. This
module is that ruling as code — called per graphics entry from
``plan_lint_motion._check_graphic_entry`` (same Report accumulator pattern;
split out to respect the 300-line logic budget).

Two moves, two gates:

* ``spec.entrance: "rail-push"`` — a ``glass-rail`` entrance (the field
  width-grows 0->33%W beside the live face). Vocabulary is checked (an
  unknown entrance would silently render the default build — fail loud) and
  the move is longform-only.
* an ACTIVE hole-comp (``graphics.pip_hole.entry_has_hole`` — always for
  ``nateherk-takeover``, opt-in via ``spec.presenterFrame`` for the dark
  scoreboard/pipeline/ledger-dark cards) — the comp renders a transparent face
  hole the renderer fills with footage. Longform-only, and the entry must ride
  anchor "own-screen" (it IS a takeover: full-frame, budget-counted, captions
  suppressed — and the alpha render is forced by ``graphics_render``).
"""

from __future__ import annotations

from typing import Any

from graphics.pip_hole import entry_has_hole

# Entrance vocabulary for glass-rail (the only comp with an `entrance` var).
RAIL_ENTRANCES = ("slide", "rail-push")
_RAIL_KIND = "glass-rail"


def _check_entrance(tag: str, g: dict, mode: str, rep: Any) -> None:
    """``spec.entrance`` vocabulary + the rail-push longform-only gate."""
    entrance = (g.get("spec") or {}).get("entrance")
    if entrance is None:
        return
    if str(g.get("kind", "")) != _RAIL_KIND:
        rep.error(f"{tag}: spec.entrance is a {_RAIL_KIND} variable — "
                  f"{g.get('kind')!r} does not read it (it would silently "
                  "render the default build)")
        return
    if entrance not in RAIL_ENTRANCES:
        rep.error(f"{tag}: spec.entrance {entrance!r} not in {RAIL_ENTRANCES}")
        return
    if entrance == "rail-push" and mode != "longform":
        rep.error(f"{tag}: entrance 'rail-push' (rail beside the live face, "
                  "NATEHERK T-B) is LONGFORM-ONLY — banned for shorts "
                  "(operator adjudication 2026-07-10)")


def _check_hole_kind(tag: str, g: dict, mode: str, rep: Any) -> None:
    """Hole-comps (face-in-PIP takeovers): longform-only + own-screen.

    Gated on the ACTIVATION predicate (``entry_has_hole``), NOT raw registry
    membership — so a scoreboard/pipeline/ledger-dark card WITHOUT the
    ``presenterFrame`` opt-in is a plain opaque card and untouched here; only an
    active presenter-frame (or nateherk-takeover) draws the longform+own-screen
    gate."""
    if not entry_has_hole(g):
        return
    if mode != "longform":
        rep.error(f"{tag}: {g.get('kind')} (face-in-PIP takeover, NATEHERK "
                  "item 9) is LONGFORM-ONLY — banned for shorts (operator "
                  "adjudication 2026-07-10)")
    if g.get("anchor", "free-band") != "own-screen":
        rep.error(f"{tag}: {g.get('kind')} must ride anchor 'own-screen' — "
                  "it is a full-frame takeover (budget-counted, captions "
                  "suppressed); the alpha render for the face hole is forced "
                  "by graphics_render.format_for")


def check_nateherk_entry(tag: str, g: dict, mode: str, rep: Any) -> None:
    """All NATEHERK-lane checks for one graphics entry."""
    _check_entrance(tag, g, mode, rep)
    _check_hole_kind(tag, g, mode, rep)
