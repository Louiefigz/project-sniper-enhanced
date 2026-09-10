#!/usr/bin/env python3
"""comp_capabilities — reader for the MEASURED comp capability matrix.

``templates/motion/comp_capabilities.json`` is measured data emitted by
``graphics/comp_catalog_probe.py``: one entry per registered comp carrying the
comp's real authored canvas + aspect (static pass over the ``#<id>-root`` CSS
rule) and, when the render pass ran, the terminal-frame fade class and settled
content bbox. It exists because catalog capability previously lived NOWHERE a
planner could read — five comps failed one-at-a-time through render/mint
cycles on 2026-07-23 (FAILURE_LEDGER LL-036/LL-037) before the matrix turned
discovery-by-render-failure into plan-time data.

This module is the plan-time predicate surface. Only a kind backed by a fresh,
complete, successful measured row is proposable. Missing/stale/unmeasured/error
state is unavailable, never a permissive fallback to declared dimensions.
"""
from __future__ import annotations

import os

from graphics.comp_capability_artifact import (
    capability_row_issue,
    load_artifact,
)

_MATRIX_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "..", "templates", "motion", "comp_capabilities.json")
_ASPECTS = ("9:16", "16:9")

_matrix_cache: dict | None = None
_matrix_error: str | None = None


def capability_matrix() -> dict:
    """Kind → release-ready measured capability entry.

    Returns:
        Only complete successful rows from a fresh artifact. ``{}`` means
        capability authority is unavailable; all predicates then fail closed.
    """
    global _matrix_cache, _matrix_error
    if _matrix_cache is None:
        comps, _matrix_error = load_artifact(_MATRIX_PATH)
        _matrix_cache = {
            kind: row for kind, row in (comps or {}).items()
            if capability_row_issue(row) is None}
    return _matrix_cache


def measured_aspect(kind: str) -> str | None:
    """The comp's MEASURED authored aspect, or None when unmeasured.

    Args:
        kind: A registered composition kind (comp file stem).

    Returns:
        ``"9:16"`` / ``"16:9"`` from a release-ready measured row, or
        ``None`` when capability authority is unavailable.
    """
    entry = capability_matrix().get(kind)
    aspect = entry.get("aspect") if isinstance(entry, dict) else None
    return aspect if aspect in _ASPECTS else None


def measured_fade_class(kind: str) -> str | None:
    """Return the fresh measured terminal behavior for one released comp."""
    entry = capability_matrix().get(kind)
    fade = entry.get("fadeClass") if isinstance(entry, dict) else None
    return fade if fade in {"fades-clean", "hold-to-cut", "partial-fade"} else None


def is_aspect_legal_kind(kind: str, aspect: str) -> bool:
    """Whether ``kind``'s measured canvas can composite on ``aspect``.

    A 16:9-authored comp composited raw onto a 9:16 delivery clips instead of
    fitting (LL-036, the fragment-payoff case) — the render bus scales only
    same-aspect canvases. Measured mismatch = illegal at plan time.

    Args:
        kind: A registered composition kind.
        aspect: The delivery aspect the plan renders at ("9:16"/"16:9").

    Returns:
        True only for a release-ready measurement matching ``aspect``.
    """
    measured = measured_aspect(kind)
    return measured == aspect
