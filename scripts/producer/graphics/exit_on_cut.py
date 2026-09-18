#!/usr/bin/env python3
"""exit_on_cut — THE EXIT LAW as a first-class compositing rule (G4).

Source: scripts/producer/docs/findings/PUNCH_STYLE.md §5.3 [6/6 HIGH]:
graphics are NEVER animated out — hard-off <= 1-2 frames, either (a) exactly
ON the next cut or (b) an instant pop at the semantic boundary. House comps
already hold to their window end (no self fade-out); this module supplies (a):
a ``graphicsTrack`` entry may opt in with ``"exitOnCut": true`` and its
``outEnd`` is CLAMPED to the first cutTrack seam after ``outStart`` — the
graphic dies exactly on the cut, deterministically.

Seam times come from ``compile_timeline.compile_plan`` (the source↔output
keystone — never hand-rolled). Shared by:

* ``plan_lint_motion`` — entry vocabulary (``entry_errors``) + clamp preview
  warnings, so lint and the renderers can never drift;
* ``render.py`` ``graphics_track_stage`` — clamps before the composite;
* ``assemble.py`` ``_composite`` — same clamp on the incremental path.

Also owns the ``takeoverBase`` vocabulary (G5 — the blur+desat takeover base
treatment rendered by ``graphics_stage``): plan value must be in
``TAKEOVER_BASES`` and is illegal under an opaque own-screen takeover or a
focus-shift anchor (which already blurs the base).

And the ``spec.exit`` vocabulary (MODULE_STUDY.md §2 T-D / §5 item 2): a
comp may exit via a graphics-layer-only blur+fade+recede (``"blur-recede"``,
``EXIT_BLUR_S`` = 0.15s ≈ 4 frames @30fps — a Sniper design parameter). The
renderers clamp BEFORE rendering (``apply_exit_on_cut`` runs ahead of
``graphics_render``), so the comp re-times its exit to the clamped window and
the blur ends exactly on the seam — lint's job (``exit_grammar_issues``) is
to fail the degenerate windows where the blur cannot complete before the
clamp point. JS twin: ``templates/motion/motion-tokens.js`` ``EXIT_BLUR_S`` /
``tokens.css`` ``--exit-blur-dur``.
"""

from __future__ import annotations

from compile_timeline import compile_plan
from graphics.placement_context import bind_plan_face_bbox

# G5 vocabulary: full-frame gaussian-blur + desaturate of the FOOTAGE as a
# takeover background (PUNCH_STYLE.md §5.4 E4 — 8 instances / 4 reels HIGH).
TAKEOVER_BASES = ("blur-desat",)

# spec.exit vocabulary — the union of the comps' exit enums ("hold" =
# statement-card default, "fade" = glass-rail default, "blur-recede" = T-D).
EXITS = ("hold", "fade", "blur-recede")
EXIT_BLUR_S = 0.15

# EXIT RUNWAY (showpiece QC 2026-07-10, FAILURE_LEDGER.md LL-001): the c0679
# statement-card's blur-recede was truncated by the 25.04 seam — outEnd sat
# exactly ON the cut, so the half-receded smear hard-cut to the next shot. A
# free-floating blur-recede (no exitOnCut) whose outEnd lands within a blur
# length of ANY seam cannot complete before/clear of the cut: ERROR. Fix by
# ending the window ≥ ~0.3s before the seam, or set exitOnCut (hard clear).
EXIT_RUNWAY_S = EXIT_BLUR_S + 0.05

_EPS = 1e-6


def seams_from_plan(plan: dict) -> list[float]:
    """Output-time cut seams (internal segment boundaries), ascending.

    The seam between segment k and k+1 is segment k+1's ``out_start`` — the
    instant the next shot's first frame lands. A single-segment cutTrack has
    no seams.
    """
    segments = compile_plan(plan).segments
    return [round(seg.out_start, 4) for seg in segments[1:]]


def effective_out_end(entry: dict, seams: list[float]) -> float:
    """The entry's outEnd after the exit-on-cut clamp (identity when off).

    Clamp rule: ``outEnd' = min(outEnd, first seam > outStart)``. No seam
    after ``outStart`` (the window sits in the final segment) leaves the
    authored end — there is no cut to die on.
    """
    start, end = float(entry["outStart"]), float(entry["outEnd"])
    if not entry.get("exitOnCut"):
        return end
    for seam in seams:
        if seam > start + _EPS:
            return min(end, seam)
    return end


def apply_exit_on_cut(plan: dict) -> tuple[list[dict], int]:
    """Effective graphics rows + how many entries were exit-clamped.

    The render-time projection also materializes a plan-global
    ``faceBBoxNorm`` onto automatic-placement rows. Entry-level geometry wins,
    explicit placements stay untouched, and the reviewed plan is never
    mutated.
    """
    track = bind_plan_face_bbox(plan.get("graphicsTrack") or [], plan)
    if not any(g.get("exitOnCut") for g in track):
        return track, 0
    seams = seams_from_plan(plan)
    out: list[dict] = []
    clamped = 0
    for g in track:
        end = effective_out_end(g, seams)
        if end != float(g["outEnd"]):
            g = {**g, "outEnd": end}
            clamped += 1
        out.append(g)
    return out, clamped


def exit_grammar_issues(entry: dict, tag: str, seams: list[float],
                        hold_min: float) -> tuple[list[str], list[str]]:
    """(errors, warnings) for ``spec.exit`` — vocabulary + the T-D clamp rule.

    ``blur-recede`` must complete BEFORE the exit-on-cut clamp point: the
    effective (clamped) window carries the comp's whole timeline, so a window
    shorter than ``EXIT_BLUR_S`` cannot finish the blur — ERROR. A window
    whose content hold after reserving the blur drops under the mode's hold
    floor is taste, not a wall — WARNING (mirrors the generic clamp preview).
    Entries without ``spec.exit`` pass through untouched (additive field).
    """
    errs: list[str] = []
    warns: list[str] = []
    exit_kind = (entry.get("spec") or {}).get("exit")
    if exit_kind is None:
        return errs, warns
    if exit_kind not in EXITS:
        errs.append(f"{tag}: spec.exit {exit_kind!r} not in {EXITS}")
        return errs, warns
    if exit_kind != "blur-recede":
        return errs, warns
    start = float(entry.get("outStart", 0))
    hold = effective_out_end(entry, seams) - start
    if hold < EXIT_BLUR_S - _EPS:
        errs.append(f"{tag}: exit 'blur-recede' needs {EXIT_BLUR_S}s but the "
                    f"effective window is {hold:.2f}s — the blur cannot "
                    "complete before the exitOnCut clamp point")
    elif hold - EXIT_BLUR_S < hold_min - _EPS:
        warns.append(f"{tag}: 'blur-recede' leaves {hold - EXIT_BLUR_S:.2f}s "
                     f"of content hold (< hold_min {hold_min}s) — the blur "
                     "eats the hold floor")
    if not entry.get("exitOnCut"):
        end = float(entry.get("outEnd", start))
        seam = next((s for s in seams
                     if abs(end - s) <= EXIT_RUNWAY_S + _EPS), None)
        if seam is not None:
            errs.append(f"{tag}: exit animation has no runway before the seam "
                        f"— 'blur-recede' outEnd {end:g}s sits within "
                        f"{EXIT_RUNWAY_S:.2f}s of the cut at {seam:g}s, so the "
                        "recede smears into the cut (LL-001: end the window "
                        "~0.3s before the seam, or set exitOnCut)")
    return errs, warns


def entry_errors(entry: dict, tag: str) -> list[str]:
    """Static vocabulary checks for the ``exitOnCut``/``takeoverBase`` keys."""
    errs: list[str] = []
    flag = entry.get("exitOnCut")
    if flag is not None and not isinstance(flag, bool):
        errs.append(f"{tag}: exitOnCut must be a boolean (got {flag!r})")
    base = entry.get("takeoverBase")
    if base is None:
        return errs
    if base not in TAKEOVER_BASES:
        errs.append(f"{tag}: takeoverBase {base!r} not in {TAKEOVER_BASES}")
    anchor = entry.get("anchor", "free-band")
    if anchor in ("own-screen", "focus-shift"):
        errs.append(f"{tag}: takeoverBase is a base-video treatment under an "
                    f"alpha overlay — illegal with anchor {anchor!r} "
                    "(own-screen covers the frame; focus-shift already blurs)")
    return errs
