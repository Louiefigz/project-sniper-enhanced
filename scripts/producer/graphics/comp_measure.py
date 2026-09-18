#!/usr/bin/env python3
"""comp_measure — plan-time comp-size measurement gate (geometry contract v3 #2).

Comp pixels are video-independent, so a graphic's rendered content extent is
measurable BEFORE any base render exists. For each ``graphicsTrack`` entry this
gate (1) derives the entry's ASSEMBLE-EFFECTIVE window, (2) renders the REAL
comp into the SHARED content-hash cache, (3) measures the settled content bbox
(``planner.graphics_anchors._content_bbox``), and (4) declares typed verdicts
through :mod:`gate_policy` — killing the LL-035 class (comp content overflowing
the canvas / the SAFE_BOX-clamped legal area) at lint instead of at Audit C.

Before rendering, the measured capability matrix
(``templates/motion/comp_capabilities.json``, via :mod:`plan_lint_comps`) is
consulted: an own-screen delivery-aspect mismatch the matrix already answers
fails fast WITHOUT spending the render; the render-measure remains the
authoritative confirmation everywhere else. A missing matrix simply skips
the fast path (plan_lint_comps reports the SKIP at plan lint).

CLI: comp_measure.py <plan.json> [--cache-dir DIR] [--budget-s S] [--fps N]
prints the gate contract ``{ok, errors, warnings, metrics}``; exit 0 iff ok.
"""
# CACHE-HIT PARITY PROOF (why a later assemble re-renders nothing):
# assemble.py `_composite` runs `apply_exit_on_cut(plan)` and hands each
# resulting entry UNTOUCHED to `graphics_render.render_entry` (via
# `graphics_stage._render_all`); render.py `graphics_track_stage` does the
# same. The live cache key is `content_hash(kind, json_canon(spec),
# outEnd - outStart, comp_html)` + shared-file/asset hashes + the resolved
# tool identity. This gate calls the IDENTICAL chain — `apply_exit_on_cut`
# then `render_entry` with the same default cache dir — so every key input is
# either a pure function of the same plan bytes or shared repo/tool state.
# Equal plan graphics fields + templates + assets + tools ⇒ equal key ⇒
# guaranteed hit. The guarantee intentionally breaks when any key input
# changes (edited spec/template, upgraded tools, sealed-container mode
# toggled) — those MUST re-render.
#
# Semantics notes (measured against the code, 2026-07-23):
# * `word_lock` snapping (`planner/word_lock.snap_plan_seams`) is a PLAN-TIME
#   transform — the plan on disk already carries snapped windows, so reading
#   the plan reproduces it; nothing re-runs here.
# * render.py/assemble NEVER pad windows; `timeline_padded_entry` is applied
#   only by the Palmier delivery lanes (`palmier/checkpoint_plan` /
#   `desktop_repair` / `desktop_revision`). Default = exact render/assemble
#   parity; `--fps` routes entries through the same padding function to warm
#   that lane's cache variant instead.
# * SAFE_BOX is authored for the 9:16 canvas — the fit check applies to comps
#   authored at that canvas (mirrors `plan_lint_motion`'s shorts-only
#   SAFE_BOX rule); 16:9 comps are cache-warmed but not SAFE_BOX-checked.
# * Missing node/browser/cv2 toolchain = ONE SKIP-with-evidence verdict —
#   never a crash, never a silent pass (the render still fails loud later).
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # run-by-path: producer pkg root on sys.path

import plan_lint_comps
from gate_policy import Verdict, to_gate_json
from graphics.comp_measure_rules import (GATE, _EntryCtx, _free_verdicts,
                                         _ownscreen_verdicts, _placed_verdicts)
from graphics.exit_on_cut import apply_exit_on_cut
from graphics.graphics_render import (DEFAULT_CACHE_DIR, comp_path,
                                      content_hash, format_for, render_entry,
                                      timeline_padded_entry)
from graphics.pip_hole import entry_has_hole
from graphics.template_contract import composition_dimensions
from motion.recompose import requires_recompose
from planner.graphics_anchors import _content_bbox
from producer_config import COMP_MEASURE, MODES


@dataclass
class _Budget:
    """Wall-clock budget shared across the entry loop (checked between comps)."""

    started: float
    allowance_s: float
    metrics: dict
    matrix: Optional[dict] = None   # comp_capabilities comps map (fail-fast)


def _matrix_fail_fast(entry: dict, ctx: _EntryCtx,
                      matrix: Optional[dict]) -> list:
    """Pre-render aspect fail-fast from the measured capability matrix.

    When the matrix already knows the comp's canvas, an own-screen
    delivery-aspect mismatch is decided WITHOUT spending the render (the
    same predicate ``_ownscreen_verdicts`` applies post-render — the render
    measure stays the authoritative confirmation on every other path).
    Verdicts are re-tagged onto THIS gate so the comp_size CLI contract is
    unchanged. Hole comps render with alpha (never the own-screen mp4 path)
    and are exempt, mirroring ``measure_entry``.
    """
    if matrix is None or entry_has_hole(entry):
        return []
    row = matrix.get(entry.get("kind")) or {}
    early = plan_lint_comps.ownscreen_matrix_verdicts(
        entry, row, ctx.tag, ctx.mode)
    return [Verdict(GATE, v.severity, v.evidence, lane=v.lane, mode=v.mode)
            for v in early]


def effective_entries(plan: dict, fps: Optional[float] = None) -> list:
    """Entries exactly as the renderer's composite will render them.

    Applies THE EXIT LAW clamp via the shared ``apply_exit_on_cut`` (the same
    call ``assemble._composite`` and ``render.graphics_track_stage`` make).
    ``fps=None`` (default) matches render.py/assemble, which never pad;
    a numeric fps routes each entry through ``timeline_padded_entry`` — the
    Palmier delivery lanes' padding — to warm that cache variant instead.

    Args:
        plan: The full edit plan (cutTrack + graphicsTrack).
        fps: Optional timeline fps for the Palmier-lane padding.

    Returns:
        The clamped (and optionally padded) graphicsTrack entry list.
    """
    track, _ = apply_exit_on_cut(plan)
    if fps is None:
        return list(track)
    return [timeline_padded_entry(entry, fps) for entry in track]


def environment_issue() -> Optional[str]:
    """Why the render/measure toolchain cannot run here, or None when it can.

    Returns:
        A human-readable reason (missing HyperFrames install, unresolvable
        node/browser/ffmpeg tools, or no cv2 for bbox probing), else ``None``.
    """
    from graphics.graphics_render import HYPERFRAMES_BIN, NODE_USER_PRELOAD
    from graphics.render_tools import resolve_tools
    if not os.path.isfile(os.path.realpath(HYPERFRAMES_BIN)):
        return f"pinned HyperFrames install missing: {HYPERFRAMES_BIN}"
    if not os.path.isfile(NODE_USER_PRELOAD):
        return f"node isolation preload missing: {NODE_USER_PRELOAD}"
    try:
        resolve_tools()
    except RuntimeError as exc:
        return f"render tools unavailable: {exc}"
    try:
        import cv2  # noqa: F401 — needed by _content_bbox
    except ImportError as exc:
        return f"cv2 unavailable for bbox measurement: {exc}"
    return None


def cache_probe(entry: dict, cache_dir: str) -> Optional[str]:
    """Path of this entry's already-cached render, or None when cold.

    Same key derivation as ``render_entry``'s live path (kind + canonical spec
    + effective duration + comp/shared/asset hashes + tool identity). Sealed
    mode (``SNIPER_RENDER_IMAGE_ID``) keys on a per-attempt snapshot, so the
    probe honestly reports cold there.

    Args:
        entry: One clamped graphicsTrack entry.
        cache_dir: The shared content-hash cache directory.

    Returns:
        The cached artifact path, or ``None``.
    """
    if os.environ.get("SNIPER_RENDER_IMAGE_ID"):
        return None
    kind = entry["kind"]
    spec = entry.get("spec") or {}
    duration = float(entry["outEnd"]) - float(entry["outStart"])
    _, ext = format_for(kind, entry.get("anchor", "free-band"), spec)
    with open(comp_path(kind), encoding="utf-8") as f:
        comp_html = f.read()
    key = content_hash(kind, spec, duration, comp_html)
    path = os.path.join(cache_dir, f"{key}.{ext}")
    return path if os.path.lexists(path) else None


def measure_entry(entry: dict, ctx: _EntryCtx, cache_dir: str) -> list:
    """Render one entry into the shared cache and check its measured geometry.

    Args:
        entry: One assemble-effective graphicsTrack entry.
        ctx: Verdict context (tag + mode).
        cache_dir: The shared content-hash cache directory.

    Returns:
        Zero or more FAIL verdicts (empty = legal / exempt anatomy).

    Raises:
        RuntimeError, ValueError, OSError: Render or measurement failure —
            the caller converts these to a FAIL verdict (fail-closed).
    """
    rendered = render_entry(entry, cache_dir)
    with open(comp_path(entry["kind"]), encoding="utf-8") as f:
        dims = composition_dimensions(f.read())
    if rendered["fmt"] == "mp4":
        return _ownscreen_verdicts(ctx, dims)
    if entry_has_hole(entry) or requires_recompose(entry):
        return []   # registered full-canvas anatomies (pip frame / edge rail)
    bbox = _content_bbox(rendered["path"])
    if entry.get("placement") is not None:
        return _placed_verdicts(entry, bbox, rendered["path"], ctx)
    return _free_verdicts(ctx, bbox, dims)


def _measure_one(entry: dict, ctx: _EntryCtx, cache_dir: str,
                 budget: _Budget) -> list:
    """Budget-guarded measurement of one entry; exceptions become verdicts."""
    fast = _matrix_fail_fast(entry, ctx, budget.matrix)
    if fast:
        budget.metrics["matrixFailFast"] += 1
        return fast
    try:
        cached = cache_probe(entry, cache_dir)
    except (ValueError, OSError, RuntimeError) as exc:
        return [Verdict(GATE, "FAIL", f"{ctx.tag}: cache probe failed — {exc}",
                        lane="graphics", mode=ctx.mode)]
    spent = time.monotonic() - budget.started
    if cached is None and spent >= budget.allowance_s:
        budget.metrics["skipped"] += 1
        return [Verdict(GATE, "SKIP", (
            f"{ctx.tag}: not yet cached and the time budget is exhausted "
            f"({spent:.1f}s spent of {budget.allowance_s:.1f}s) — unmeasured; "
            "assemble renders it later"), lane="graphics", mode=ctx.mode)]
    try:
        verdicts = measure_entry(entry, ctx, cache_dir)
    except (RuntimeError, ValueError, OSError, KeyError, TypeError) as exc:
        return [Verdict(GATE, "FAIL", f"{ctx.tag}: render/measure failed — {exc}",
                        lane="graphics", mode=ctx.mode)]
    budget.metrics["measured"] += 1
    if cached is not None:
        budget.metrics["cachedHits"] += 1
    return verdicts


def measure_plan(plan: dict, cache_dir: str, budget_s: float,
                 fps: Optional[float] = None) -> tuple:
    """Measure every graphicsTrack entry of a plan.

    Args:
        plan: The full edit plan.
        cache_dir: The shared content-hash cache directory.
        budget_s: Per-comp wall-clock allowance (total = budget_s x entries;
            checked between comps, cache hits always measured).
        fps: Optional Palmier-lane padding fps (see :func:`effective_entries`).

    Returns:
        ``(verdicts, metrics)`` — typed gate_policy verdicts + run counters.
    """
    mode_raw = (plan.get("target") or {}).get("mode")
    mode = mode_raw if mode_raw in MODES else None
    entries = effective_entries(plan, fps)
    metrics = {"entries": len(entries), "measured": 0, "cachedHits": 0,
               "skipped": 0, "matrixFailFast": 0}
    if not entries:
        return [], metrics
    issue = environment_issue()
    if issue:
        metrics["skipped"] = len(entries)
        return [Verdict(GATE, "SKIP", (
            f"environment unavailable — {issue}; {len(entries)} comp(s) "
            "unmeasured (the render itself still fails loud)"),
            lane="graphics", mode=mode)], metrics
    matrix, _ = plan_lint_comps.load_matrix()   # None = no fast path
    budget = _Budget(time.monotonic(), budget_s * len(entries), metrics,
                     matrix)
    verdicts: list = []
    for i, entry in enumerate(entries):
        ctx = _EntryCtx(f"graphicsTrack[{i}] {entry.get('kind')}", mode)
        verdicts.extend(_measure_one(entry, ctx, cache_dir, budget))
    metrics["elapsedS"] = round(time.monotonic() - budget.started, 2)
    return verdicts, metrics


def main() -> int:
    """CLI entry point printing the ``{ok, errors, warnings}`` gate contract."""
    ap = argparse.ArgumentParser(
        description="PRODUCER comp-size plan-time measurement gate")
    ap.add_argument("plan_path")
    ap.add_argument("--cache-dir", default=None,
                    help="content-hash render cache (default: the shared "
                         "templates/motion/renders/cache)")
    ap.add_argument("--budget-s", type=float,
                    default=COMP_MEASURE["per_comp_budget_s"],
                    help="per-comp wall-clock allowance (cache-aware)")
    ap.add_argument("--fps", type=float, default=None,
                    help="Palmier-lane parity: pad each entry via "
                         "timeline_padded_entry (render/assemble never pad)")
    args = ap.parse_args()
    try:
        with open(args.plan_path) as f:
            plan = json.load(f)
        verdicts, metrics = measure_plan(
            plan, args.cache_dir or DEFAULT_CACHE_DIR, args.budget_s, args.fps)
        verdict = to_gate_json(verdicts, plan.get("target"))
        verdict["metrics"] = metrics
        print(json.dumps(verdict, indent=2))
        return 0 if verdict["ok"] else 1
    except (OSError, json.JSONDecodeError, KeyError, ValueError,
            RuntimeError) as exc:
        print(json.dumps({"ok": False,
                          "errors": [f"comp_measure: {exc}"],
                          "warnings": []}, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
