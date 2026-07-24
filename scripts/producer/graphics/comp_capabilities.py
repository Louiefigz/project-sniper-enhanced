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

This module is the plan-time predicate surface, the sibling of
``graphics.form_allocation.is_gate_executable_kind`` (the canvas-pip-list
precedent): consumed wherever kinds are proposed/mapped so the planner can
never propose an aspect-illegal comp. Posture matches
``graphics_planner_longform.canvas_ok``: an UNMEASURED kind (matrix absent or
comp not probed yet) passes — the derived MG-4.3 canvas filter and the render
proofs still stand behind it — while a MEASURED aspect is authoritative and
wins over any declared/derived canvas.
"""
from __future__ import annotations

import json
import os

_MATRIX_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "..", "templates", "motion", "comp_capabilities.json")
_ASPECTS = ("9:16", "16:9")

_matrix_cache: dict | None = None


def capability_matrix() -> dict:
    """kind → measured capability entry; ``{}`` when the matrix isn't built.

    Returns:
        The ``comps`` map of ``comp_capabilities.json`` (schemaVersion 1), or
        an empty dict when the probe has not written the file yet — absence
        means "no measured data", never an error (the probe is a one-time
        batch measure; every predicate here degrades to permissive).
    """
    global _matrix_cache
    if _matrix_cache is None:
        try:
            with open(_MATRIX_PATH, encoding="utf-8") as handle:
                loaded = json.load(handle)
            comps = loaded.get("comps") if isinstance(loaded, dict) else None
            _matrix_cache = dict(comps) if isinstance(comps, dict) else {}
        except (OSError, json.JSONDecodeError, ValueError):
            _matrix_cache = {}
    return _matrix_cache


def measured_aspect(kind: str) -> str | None:
    """The comp's MEASURED authored aspect, or None when unmeasured.

    Args:
        kind: A registered composition kind (comp file stem).

    Returns:
        ``"9:16"`` / ``"16:9"`` from the matrix's static probe, or ``None``
        when the matrix (or this kind's entry) doesn't exist yet.
    """
    entry = capability_matrix().get(kind)
    aspect = entry.get("aspect") if isinstance(entry, dict) else None
    return aspect if aspect in _ASPECTS else None


def is_aspect_legal_kind(kind: str, aspect: str) -> bool:
    """Whether ``kind``'s measured canvas can composite on ``aspect``.

    A 16:9-authored comp composited raw onto a 9:16 delivery clips instead of
    fitting (LL-036, the fragment-payoff case) — the render bus scales only
    same-aspect canvases. Measured mismatch = illegal at plan time.

    Args:
        kind: A registered composition kind.
        aspect: The delivery aspect the plan renders at ("9:16"/"16:9").

    Returns:
        False only when the matrix has MEASURED this kind at a different
        aspect; True for a matching measurement or an unmeasured kind.
    """
    measured = measured_aspect(kind)
    return measured is None or measured == aspect
