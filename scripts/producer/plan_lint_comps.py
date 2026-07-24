#!/usr/bin/env python3
"""plan_lint_comps — the measured comp-capability matrix lint (plan time).

Reads ``templates/motion/comp_capabilities.json`` (written by
``graphics/comp_catalog_probe.py`` — measured canvas dims + terminal-frame
fade class per registered comp) and judges every ``graphicsTrack`` entry
against it BEFORE any render exists:

* (a) OVERLAY ASPECT: an entry whose comp canvas aspect differs from the
  delivery aspect under an overlay anchor (``free-band``/``headroom``/
  ``beside-face``) FAILs, naming the comp's real canvas and the aspect-legal
  comps of the same family (the ``-wide`` sibling convention).
* (b) OWN-SCREEN ASPECT: the plan-time mirror of ``graphics/comp_measure``'s
  own-screen delivery-aspect check (same ratio predicate/tolerance as
  ``comp_measure_rules._ownscreen_verdicts``) — caught from the matrix before
  a single frame renders.
* (c) HOLD-TO-CUT EXIT: a ``fadeClass: "hold-to-cut"`` comp whose window does
  NOT end on a cutTrack seam (and carries no ``exitOnCut``) FAILs — a
  full-alpha terminal frame hard-drops mid-shot (THE EXIT LAW, G4).
* (d) PARTIAL FADE: ``fadeClass: "partial-fade"`` WARNs with the measured
  terminal alpha — residual pixels linger at the window end.

Missing/unreadable matrix = ONE SKIP-with-evidence verdict via
:mod:`gate_policy` (never a crash, never a silent pass). A kind absent from
the matrix WARNs (``unmeasured comp``); a row without a render measurement
(probe still running / renderError) SKIPs the fade rules with evidence.
``plan_lint.lint`` dispatches via :func:`check_comp_matrix`;
``graphics/comp_measure`` reuses :func:`ownscreen_matrix_verdicts` as its
pre-render fail-fast.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

import gate_policy
from gate_policy import Verdict
from compile_timeline import compile_plan
from graphics.comp_measure_rules import _ASPECT_TOL, _delivery_canvas
from graphics.graphics_render import COMPOSITIONS_DIR
from producer_config import COMP_MEASURE, MODES

GATE = "comp_capabilities"
gate_policy.register_gate(GATE, "FAIL")

#: The probe's output — the measured capability matrix for every comp.
DEFAULT_MATRIX_PATH = os.path.join(
    os.path.dirname(COMPOSITIONS_DIR), "comp_capabilities.json")

# Overlay anchors whose geometry is authored against the delivery canvas —
# a wrong-aspect comp cannot overlay it (rule a). own-screen is rule (b);
# chest/focus-shift stay out per the wiring contract.
_OVERLAY_ASPECT_ANCHORS = ("free-band", "headroom", "beside-face")
_SEAM_TOL_S = COMP_MEASURE["seam_tol_s"]


def load_matrix(path: Optional[str] = None) -> tuple[Optional[dict], str]:
    """The matrix's comps map, or ``(None, why)`` — never raises.

    Args:
        path: Matrix file path (default: :data:`DEFAULT_MATRIX_PATH`).

    Returns:
        ``(comps, "")`` when readable and well-shaped, else ``(None,
        evidence)`` for the SKIP-with-evidence verdict.
    """
    path = path or DEFAULT_MATRIX_PATH
    if not os.path.isfile(path):
        return None, (f"matrix file missing: {path} — run "
                      "graphics/comp_catalog_probe.py")
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"matrix unreadable: {path} — {exc}"
    comps = data.get("comps") if isinstance(data, dict) else None
    if not isinstance(comps, dict) or not comps:
        return None, f"matrix malformed: {path} carries no comps map"
    return comps, ""


def _row_canvas(row: dict) -> Optional[tuple[int, int]]:
    """The row's measured ``(width, height)``, or None when malformed."""
    canvas = row.get("canvas")
    if (isinstance(canvas, (list, tuple)) and len(canvas) == 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                    and v > 0 for v in canvas)):
        return int(canvas[0]), int(canvas[1])
    return None


def _aspect_label(canvas: tuple[int, int]) -> str:
    """The probe's aspect taxonomy: portrait canvas = 9:16, else 16:9."""
    return "9:16" if canvas[1] > canvas[0] else "16:9"


def _family(kind: str) -> str:
    """Comp family: the ``-wide`` suffix marks the 16:9 sibling of a kind."""
    return kind[: -len("-wide")] if kind.endswith("-wide") else kind


def _aspect_siblings(kind: str, comps: dict, delivery_aspect: str) -> list:
    """Same-family kinds whose measured canvas matches the delivery aspect."""
    out = []
    for other, row in comps.items():
        if other == kind or _family(other) != _family(kind):
            continue
        canvas = _row_canvas(row)
        if canvas is not None and _aspect_label(canvas) == delivery_aspect:
            out.append(other)
    return sorted(out)


def _overlay_verdicts(entry: dict, row: dict, comps: dict,
                      ctx: tuple) -> list:
    """(a) Overlay-anchored entries: comp aspect must match delivery aspect."""
    anchor = entry.get("anchor", "free-band")
    if anchor not in _OVERLAY_ASPECT_ANCHORS:
        return []
    canvas = _row_canvas(row)
    if canvas is None:
        return []
    tag, mode = ctx
    delivery = MODES.get(mode or "", {}).get("aspect", "9:16")
    comp_aspect = _aspect_label(canvas)
    if comp_aspect == delivery:
        return []
    siblings = _aspect_siblings(str(entry.get("kind")), comps, delivery)
    alt = (f"aspect-legal same-family comps: {', '.join(siblings)}"
           if siblings else "no aspect-legal same-family comp is registered "
           f"— pick a {delivery}-authored kind")
    return [Verdict(GATE, "FAIL", (
        f"{tag}: comp's real canvas is {canvas[0]}x{canvas[1]} "
        f"({comp_aspect}) but the delivery is {delivery} and anchor "
        f"{anchor!r} overlays the delivery canvas directly — {alt}"),
        lane="graphics", mode=mode)]


def ownscreen_matrix_verdicts(entry: dict, row: dict, tag: str,
                              mode: Optional[str]) -> list:
    """(b) Own-screen entries: matrix canvas vs delivery aspect, pre-render.

    Mirrors ``comp_measure_rules._ownscreen_verdicts`` (same ratio predicate
    and tolerance) so the answer lands at plan time. A row with a
    ``canvasNote`` (CSS root disagrees with the declared data-width/height)
    is ambiguous — the render-side measure stays authoritative there.

    Args:
        entry: One graphicsTrack entry.
        row: The kind's matrix row (empty dict = unknown → no verdict).
        tag: Evidence tag (``graphicsTrack[i] kind``).
        mode: The plan's validated mode (or None).

    Returns:
        Zero or one FAIL verdict.
    """
    if entry.get("anchor", "free-band") != "own-screen":
        return []
    canvas = _row_canvas(row)
    if canvas is None or "canvasNote" in row:
        return []
    video_w, video_h = _delivery_canvas(mode)
    if abs(canvas[0] / canvas[1] - video_w / video_h) <= _ASPECT_TOL:
        return []
    return [Verdict(GATE, "FAIL", (
        f"{tag}: own-screen comp's measured canvas {canvas[0]}x{canvas[1]} "
        f"does not match the {video_w}x{video_h} delivery aspect — the "
        "composite will refuse it (matrix pre-check; the render measure "
        "confirms)"), lane="graphics", mode=mode)]


def _safe_seam_map(plan: dict) -> Optional[tuple[list, float]]:
    """(seams, output end) via compile_plan, or None when the map can't build."""
    try:
        segments = compile_plan(plan).segments
    except (ValueError, TypeError, KeyError):
        return None
    if not segments:
        return None
    return ([round(seg.out_start, 4) for seg in segments[1:]],
            round(segments[-1].out_end, 4))


def _hold_verdicts(entry: dict, seam_map: Optional[tuple],
                   ctx: tuple) -> list:
    """(c) hold-to-cut comps must die on a cut seam (or the output end)."""
    tag, mode = ctx
    if entry.get("exitOnCut"):
        return []
    if seam_map is None:
        return [Verdict(GATE, "SKIP", (
            f"{tag}: hold-to-cut comp but the cutTrack seam map is "
            "unavailable (compile_plan failed) — cannot verify the exit "
            "lands on a cut"), lane="graphics", mode=mode)]
    seams, total = seam_map
    try:
        end = float(entry.get("outEnd"))
    except (TypeError, ValueError):
        return []                 # window-shape errors are the base lint's job
    if (any(abs(end - seam) <= _SEAM_TOL_S for seam in seams)
            or abs(end - total) <= _SEAM_TOL_S):
        return []
    return [Verdict(GATE, "FAIL", (
        f"{tag}: hold-to-cut comp must exit on a cut — outEnd {end:g}s lands "
        f"on no cutTrack seam (seams: {seams or 'none'}, output end "
        f"{total:g}s) and exitOnCut is not set; the full-alpha terminal "
        "frame hard-drops mid-shot (THE EXIT LAW)"),
        lane="graphics", mode=mode)]


def _fade_verdicts(entry: dict, row: dict, seam_map: Optional[tuple],
                   ctx: tuple) -> list:
    """(c)+(d) fade-class rules; SKIP-with-evidence when unmeasured."""
    tag, mode = ctx
    fade = row.get("fadeClass")
    if fade is None:
        why = row.get("renderError")
        detail = (f"render probe failed: {why}" if why
                  else "the render pass has not measured it yet")
        return [Verdict(GATE, "SKIP", (
            f"{tag}: comp has no measured fadeClass ({detail}) — the "
            "hold-to-cut/partial-fade checks cannot run"),
            lane="graphics", mode=mode)]
    if fade == "partial-fade":
        alpha = row.get("terminalAlpha") or {}
        return [Verdict(GATE, "WARN", (
            f"{tag}: comp ends on a partial fade (measured terminal alpha "
            f"max={alpha.get('maxAlpha8')}, mean={alpha.get('meanAlpha8')}) "
            "— residual pixels linger at the window end; prefer a clean "
            "fade or exitOnCut"), lane="graphics", mode=mode)]
    if fade != "hold-to-cut":
        return []
    return _hold_verdicts(entry, seam_map, ctx)


def matrix_verdicts(plan: dict,
                    matrix_path: Optional[str] = None) -> list:
    """Every matrix-derived verdict for the plan's graphicsTrack.

    Args:
        plan: The full edit plan.
        matrix_path: Override matrix path (tests; default = repo matrix).

    Returns:
        Typed :class:`gate_policy.Verdict` list (empty = clean / no track).
    """
    track = plan.get("graphicsTrack") or []
    if not track:
        return []
    mode_raw = (plan.get("target") or {}).get("mode")
    mode = mode_raw if mode_raw in MODES else None
    comps, why = load_matrix(matrix_path)
    if comps is None:
        return [Verdict(GATE, "SKIP", (
            f"comp-capability checks cannot run — {why}; "
            f"{len(track)} graphicsTrack entr"
            f"{'y' if len(track) == 1 else 'ies'} unchecked"),
            lane="graphics", mode=mode)]
    seam_map = _safe_seam_map(plan)
    out: list = []
    for i, entry in enumerate(track):
        kind = entry.get("kind")
        tag = f"graphicsTrack[{i}] {kind}"
        row = comps.get(kind)
        if row is None:
            out.append(Verdict(GATE, "WARN", (
                f"{tag}: unmeasured comp — kind {kind!r} has no "
                "comp_capabilities entry (matrix stale? re-run "
                "graphics/comp_catalog_probe.py)"), lane="graphics",
                mode=mode))
            continue
        ctx = (tag, mode)
        out.extend(_overlay_verdicts(entry, row, comps, ctx))
        out.extend(ownscreen_matrix_verdicts(entry, row, tag, mode))
        out.extend(_fade_verdicts(entry, row, seam_map, ctx))
    return out


def check_comp_matrix(plan: dict, rep: Any) -> None:
    """plan_lint dispatch: adapt matrix verdicts through the policy table.

    Blocking resolutions land in ``rep.errors``; advisories and labeled
    skips land in ``rep.warnings`` (``gate_policy.to_gate_json`` semantics).

    Args:
        plan: The edit plan (``target.mode`` already validated by the caller).
        rep: plan_lint's Report accumulator.
    """
    verdicts = matrix_verdicts(plan)
    if not verdicts:
        return
    resolved = gate_policy.to_gate_json(verdicts, plan.get("target") or {})
    for msg in resolved["errors"]:
        rep.error(msg)
    for msg in resolved["warnings"]:
        rep.warn(msg)
