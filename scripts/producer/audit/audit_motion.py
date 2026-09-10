#!/usr/bin/env python3
"""audit_motion — deterministic motion-quality backstop for Audit B.

Motion quality is decided UPSTREAM in the planner (pacing coordinator + motion
proposer); this module is the render-time SAFETY NET, never the primary
mechanism. It catches what slips past the plan — a graphics track that silently
failed to composite, an aliveness creep that emitted a dead-frozen still, a push
that snapped instead of easing — using ffmpeg scene-detect + PIL/numpy pixel
diffs only. NO vision/LLM calls: occlusion / "creep absent while the subject
still moves" is the DEEP reviewer's job, out of scope here.

Ambiguous scene-rate misses remain WARN, while literal frozen windows, zero
manifested cuts, and hard splices inside eased pushes FAIL closed. Checks are
gated to PRODUCED plans: a clean-cut treatment has empty engaging tracks, so
these render-side mirrors have nothing to verify and return ``[]``.

  * PACING (``check_pacing_rendered``) — the render-side mirror of the plan-side
    pacing lint: scene-detect the finished file and compare its change RATE +
    longest still GAP against the mode's pacing floors (did graphics render?).
  * PRESENCE (``check_presence``) — every plan-declared aliveness window must
    render as motion, not a literally dead-frozen still (pixel diff at the ends).
  * SMOOTHNESS (``check_smoothness``) — a semantic push should EASE; a scene
    change mid-window is a snap where an ease was intended (MOTION_GRAMMAR).

Thresholds are this module's config (constants at top). See docs/producer/PRODUCER_PLAN.md
§5 (Audit B) and docs/studies/PACING_RHYTHM_STUDY.md / MOTION_GRAMMAR_STUDY.md.
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from audit.audit_checks import CheckResult, FAIL, PASS, WARN  # noqa: E402
from audit.audit_placements import check_eye_trace  # noqa: E402, F401
from audit.audit_probe import extract_frame, run_ff  # noqa: E402
from cut_delivery_authority import CutProof, verify_delivered_cuts  # noqa: E402
from producer_config import TREATMENTS, TREATMENT_DEFAULT  # noqa: E402

SCENE_THR = 0.3               # whole-file scene-detect sensitivity (pacing)
MANIFEST_MIN_FRAC = 0.5       # rendered hard changes must reach this share of cuts
PRESENCE_PAD_S = 0.15         # sample this far inside each aliveness window end
PRESENCE_MIN_DIFF = 1.0       # mean abs pixel diff (0-255) below this = frozen
PRESENCE_DOWNSCALE_W = 160    # grayscale frames to this width before diffing
SMOOTH_THR = 0.4              # CUT-LEVEL: an unexpected hard splice inside a push
                              # (below this, scene-detect can't separate a subtle
                              # animation jerk from subject motion — that subtler
                              # easing-quality call is the DEEP vision reviewer's)
SMOOTH_EDGE_PAD_S = 0.3       # a change within this of a window end is a legit cut

_PTS_RE = re.compile(r"pts_time:(\d+\.?\d*)")


def _ff_output(cmd: list[str]) -> str:
    """Combined stderr+stdout of an ffmpeg run (showinfo logs pts_time to stderr).

    Mirrors ``audit_glitch._ff_output`` so this module reads the filter log the
    same way the sibling screen-integrity checks do.
    """
    proc = run_ff(cmd)
    return proc.stderr + proc.stdout


def _is_produced(plan: dict) -> bool:
    """True when the plan's treatment enables motion or graphics (not clean-cut).

    Resolves ``target.treatment`` against ``TREATMENTS`` (default "produced").
    Clean-cut leaves both flags False — its engaging tracks are empty — so all
    three checks skip it: there is no rendered motion to verify.

    Args:
        plan: The edit plan.

    Returns:
        Whether the produced-only motion checks should run.
    """
    treatment = (plan.get("target") or {}).get("treatment", TREATMENT_DEFAULT)
    flags = TREATMENTS.get(treatment, TREATMENTS[TREATMENT_DEFAULT])
    return bool(flags.get("motion") or flags.get("graphics"))


def _plan_seam_times(plan: dict) -> list[float]:
    """Output-time instants of the plan's internal cut seams."""
    seams: list[float] = []
    cursor = 0.0
    track = plan.get("cutTrack") or []
    for segment in track[:-1]:
        try:
            span = float(segment["end"]) - float(segment["start"])
            speed = float(segment.get("speed", 1.0)) or 1.0
        except (KeyError, TypeError, ValueError):
            return []
        cursor += span / speed
        seams.append(round(cursor, 4))
    return seams


def _seam_frame_delta(final_path: str, at: float, work: str, tag: str) -> float | None:
    """Mean abs pixel delta across the frame pair straddling ``at`` (0-255)."""
    before = os.path.join(work, f"seam-{tag}-a.jpg")
    after = os.path.join(work, f"seam-{tag}-b.jpg")
    if not (extract_frame(final_path, max(0.0, at - 0.06), before)
            and extract_frame(final_path, at + 0.06, after)):
        return None
    try:
        one = np.asarray(Image.open(before).convert("L"), dtype=np.float32)
        two = np.asarray(Image.open(after).convert("L"), dtype=np.float32)
    except OSError:
        return None
    if one.shape != two.shape:
        return None
    return float(np.abs(one - two).mean())


def _seams_manifested(final_path: str, plan: dict, work: str) -> tuple[int, int]:
    """(manifested, checked) mining seams by LOCAL frame-pair delta.

    Whole-file scene-detect is blind to same-scene mining splices (identical
    framing minutes apart, softened further by punch-step covers), so a zero
    scene count must not by itself mean "cuts did not manifest". A real splice
    still steps the pixels locally (pose/hands jump); noise baseline is the
    same-size delta measured half a second BEFORE the seam.
    """
    manifested = 0
    seams = _plan_seam_times(plan)
    for index, seam in enumerate(seams):
        step = _seam_frame_delta(final_path, seam, work, f"{index}")
        noise = _seam_frame_delta(final_path, max(0.0, seam - 0.5), work,
                                  f"{index}n")
        if step is None:
            continue
        floor = max(6.0, 2.0 * noise) if noise is not None else 6.0
        if step > floor:
            manifested += 1
    return manifested, len(seams)


def _sealed_cut_lineage(final_path: str, plan: dict) -> CutProof | None:
    """Verified execution proof, or None when any authority link is absent."""
    try:
        return verify_delivered_cuts(
            os.path.dirname(os.path.abspath(final_path)), final_path, plan)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _scene_times(final_path: str, duration: float) -> list[float]:
    """Sorted scene-change instants strictly inside ``(0, duration)``.

    Whole-file scene-detect reports ABSOLUTE pts_time; t=0 and the video end are
    not visual changes, so both bookends are dropped.
    """
    out = _ff_output(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", final_path,
         "-vf", f"select='gt(scene,{SCENE_THR})',showinfo", "-an",
         "-f", "null", "-"])
    times = sorted(float(m) for m in _PTS_RE.findall(out))
    return [t for t in times if 0.0 < t < duration]


def _zero_scene_cut_result(
    final_path: str,
    plan: dict,
    declared_cuts: int,
) -> CheckResult:
    """Resolve a zero-scene result through seam pixels, then sealed lineage."""
    import tempfile
    with tempfile.TemporaryDirectory(prefix="seam-probe-") as work:
        manifested, checked = _seams_manifested(final_path, plan, work)
    enough = checked and manifested >= max(
        1, int(checked * MANIFEST_MIN_FRAC))
    if enough:
        return CheckResult(
            "motion_pacing", PASS,
            f"scene-detect blind but {manifested}/{checked} seams prove a "
            "local frame step (same-scene mining splices)",
            "per-seam frame-pair delta confirms the declared cuts")
    lineage = _sealed_cut_lineage(final_path, plan)
    if lineage is not None and lineage.parts == declared_cuts + 1:
        return CheckResult(
            "motion_pacing", PASS,
            f"scene-detect blind; sealed {lineage.parts}-part execution "
            f"lineage proves {lineage.frames} exact frames through the "
            f"{lineage.mode} delivery",
            "compiled timeline, per-part frames, concat, base, and current "
            "final authority all agree")
    return CheckResult(
        "motion_pacing", FAIL,
        f"rendered 0 hard changes vs {declared_cuts} plan cuts and only "
        f"{manifested}/{checked} seams show a local frame step — "
        "declared cuts did not manifest",
        "neither scene-detect, per-seam frame deltas, nor sealed execution "
        "lineage proves the cuts")


def check_pacing_rendered(final_path: str, duration: float,
                          plan: dict, mode: str) -> list[CheckResult]:
    """Render-side sanity: did the plan's CUTS actually manifest?

    NOT a pacing-rate gate. ffmpeg scene-detect reliably sees only HARD cuts — it
    is structurally blind to the eased zooms and subtle alpha overlays that also
    carry pacing (measured: eased pushes + glass overlays score below SCENE_THR).
    Comparing a scene-detect RATE to the plan's total-change floor therefore
    over-warns on eased-motion renders the planner considers well-paced. True
    pacing is gated PLAN-SIDE (``planner.pacing`` at lint) and, for motion, by
    ``check_presence``. Here we verify only what scene-detect CAN see: that the
    plan's cut boundaries produced hard changes. A render showing far fewer hard
    changes than the plan has cuts is suspicious; zero manifested cuts FAILs,
    while a partial shortfall remains WARN-only;
    ``[]`` for a clean-cut plan.

    Args:
        final_path: Path to ``final.mp4``.
        duration: Output duration (seconds).
        plan: The edit plan (gating + declared cut count).
        mode: ``"short"`` or ``"longform"`` (unused here; kept for call symmetry).

    Returns:
        One FAIL for zero manifested cuts, WARN for a partial shortfall, else
        one informational PASS. Empty when not produced or duration ≤ 0.
    """
    if not _is_produced(plan) or duration <= 0:
        return []
    declared_cuts = max(0, len(plan.get("cutTrack") or []) - 1)
    rendered = len(_scene_times(final_path, duration))
    rate = rendered / duration * 60.0
    if declared_cuts >= 2 and rendered == 0:
        return [_zero_scene_cut_result(final_path, plan, declared_cuts)]
    if declared_cuts >= 2 and rendered < declared_cuts * MANIFEST_MIN_FRAC:
        return [CheckResult(
            "motion_pacing", WARN,
            f"rendered {rendered} hard changes vs {declared_cuts} plan cuts "
            f"({rate:.1f}/min) — cuts may not have composited (frozen render?)",
            "scene-detect fell well short of the plan's cut count")]
    return [CheckResult(
        "motion_pacing", PASS,
        f"rendered {rendered} hard changes, {rate:.1f} changes/min "
        f"(~{declared_cuts} plan cuts; eased-motion pacing gated plan-side)",
        "scene-detect sees hard cuts only")]


def _load_gray_160(path: str) -> "np.ndarray | None":
    """Grayscale numpy array (float 0-255) of an image, downscaled to 160px wide.

    Returns None if the image can't be read.
    """
    try:
        with Image.open(path) as image:
            gray = image.convert("L")
            width, height = gray.size
            if width > PRESENCE_DOWNSCALE_W:
                new_h = max(1, round(height * PRESENCE_DOWNSCALE_W / width))
                gray = gray.resize((PRESENCE_DOWNSCALE_W, new_h))
            return np.asarray(gray, dtype=np.float64)
    except (OSError, ValueError):
        return None


def _frame_diff(a_path: str, b_path: str) -> "float | None":
    """Mean absolute pixel diff (0-255) of two frames, grayscaled + 160px-wide.

    None if either frame is unreadable or their downscaled shapes disagree (both
    come from one source, so a mismatch means an extraction anomaly — skip it).
    """
    a = _load_gray_160(a_path)
    b = _load_gray_160(b_path)
    if a is None or b is None or a.shape != b.shape:
        return None
    return float(np.mean(np.abs(a - b)))


def _cleanup(*paths: str) -> None:
    """Remove temp frame files, ignoring any that are already gone."""
    for path in paths:
        try:
            os.remove(path)
        except OSError:
            pass


def _window_motion(final_path: str, start: float, end: float,
                   out_dir: str) -> "float | None":
    """Pixel-diff of the two window-end frames of ``[start, end]``, or None.

    Extracts a frame at ``start + PRESENCE_PAD_S`` and ``end - PRESENCE_PAD_S``,
    diffs them (grayscale, 160px), and always cleans the temp frames up.
    """
    tag = f"{start:.3f}".replace(".", "_")
    a_path = os.path.join(out_dir, f"_presence_{tag}_a.jpg")
    b_path = os.path.join(out_dir, f"_presence_{tag}_b.jpg")
    try:
        ok_a = extract_frame(final_path, start + PRESENCE_PAD_S, a_path)
        ok_b = extract_frame(final_path, end - PRESENCE_PAD_S, b_path)
        if not (ok_a and ok_b):
            return None
        return _frame_diff(a_path, b_path)
    finally:
        _cleanup(a_path, b_path)


def check_presence(final_path: str, plan: dict,
                   out_dir: str) -> list[CheckResult]:
    """Verify every plan-declared aliveness window renders as MOTION, not frozen.

    For each ``punchIns`` entry with ``role == "aliveness"`` (a continuous eased
    creep carrying ``outStart``/``outEnd``), measure the mean absolute pixel diff
    between the two window-end frames. A near-zero diff means the creep never
    rendered — a still was emitted — which FAILs. This catches a *literally
    dead-frozen* render, NOT "the creep is absent while the subject still moves"
    (that occlusion/vision judgment is the deep reviewer's). Returns
    ``[]`` for clean-cut plans or when there are no measurable aliveness windows.

    Args:
        final_path: Path to ``final.mp4``.
        plan: The edit plan (gating + the aliveness windows).
        out_dir: Directory for the throwaway extracted frames (cleaned up).

    Returns:
        One FAIL per frozen window, else a single PASS. Empty when not produced or
        no aliveness window is wide enough to sample.
    """
    if not _is_produced(plan):
        return []
    windows = [p for p in plan.get("punchIns") or []
               if p.get("role") == "aliveness"
               and "outStart" in p and "outEnd" in p]
    results: list[CheckResult] = []
    checked = 0
    for w in windows:
        start, end = float(w["outStart"]), float(w["outEnd"])
        if end - start < 2 * PRESENCE_PAD_S:
            continue
        diff = _window_motion(final_path, start, end, out_dir)
        if diff is None:
            continue
        checked += 1
        if diff < PRESENCE_MIN_DIFF:
            results.append(CheckResult(
                "motion_presence", FAIL,
                f"presence: aliveness window {start:.1f}-{end:.1f}s is static "
                f"(diff {diff:.2f}) — no motion rendered",
                f"mean abs pixel diff floor {PRESENCE_MIN_DIFF}"))
    if checked and not results:
        results.append(CheckResult(
            "motion_presence", PASS, f"{checked} aliveness window(s) show motion",
            f"mean abs pixel diff floor {PRESENCE_MIN_DIFF}"))
    return results


def _cut_boundaries(plan: dict) -> list[float]:
    """Internal cut-boundary output times (cumulative segment lengths, dropping
    the final end). A scene change AT one of these is a legitimate cut, not an
    animation snap, so ``_has_mid_snap`` excludes its neighbourhood."""
    offsets: list[float] = []
    running = 0.0
    for seg in plan.get("cutTrack") or []:
        speed = float(seg.get("speed", 1.0)) or 1.0
        running += (float(seg["end"]) - float(seg["start"])) / speed
        offsets.append(running)
    return offsets[:-1]


def _has_mid_snap(final_path: str, start: float, end: float,
                  cut_times: list[float]) -> bool:
    """True when a scene change lands > SMOOTH_EDGE_PAD_S from BOTH window ends
    AND does not coincide with a plan cut boundary.

    Input-side seek (``-ss`` before ``-i``) resets pts to 0, so the reported
    pts_time is RELATIVE to the window start (verified empirically). A detection
    within the edge pad of either end is the legitimate boundary cut; one that
    coincides with an internal ``cut_times`` boundary is a hard cut the plan
    authored inside this window (also legitimate) — only a discontinuity that is
    NEITHER is a snap where an eased push was intended.
    """
    span = end - start
    out = _ff_output(
        ["ffmpeg", "-hide_banner", "-nostats", "-ss", f"{start:.3f}",
         "-i", final_path, "-t", f"{span:.3f}",
         "-vf", f"select='gt(scene,{SMOOTH_THR})',showinfo", "-an",
         "-f", "null", "-"])
    for m in _PTS_RE.findall(out):
        rel = float(m)
        if not (SMOOTH_EDGE_PAD_S < rel < span - SMOOTH_EDGE_PAD_S):
            continue
        if any(abs(start + rel - c) <= SMOOTH_EDGE_PAD_S for c in cut_times):
            continue
        return True
    return False


def check_smoothness(final_path: str, plan: dict) -> list[CheckResult]:
    """Flag an unexpected HARD SPLICE inside a semantic push (a push should EASE).

    For each SEMANTIC punch (``role != "aliveness"``, carrying ``outStart`` /
    ``outEnd``, window ≥ 2·SMOOTH_EDGE_PAD_S), scene-detect WITHIN the window at a
    CUT-LEVEL threshold (SMOOTH_THR). A cut-level discontinuity comfortably inside
    the window, NOT at a window edge and NOT on a plan cut boundary, is an
    unexpected splice/glitch where an eased push was intended (MOTION_GRAMMAR) and
    FAILs. This deliberately does NOT chase subtle easing jerks: below cut level,
    scene-detect can't separate a small crop-step from subject motion, so that
    finer easing-quality judgement is left to the DEEP vision reviewer;
    ``[]`` for clean-cut plans or when no semantic punch is wide enough.

    Args:
        final_path: Path to ``final.mp4``.
        plan: The edit plan (gating + the semantic punch windows).

    Returns:
        One FAIL per punch containing an unexpected hard splice, else a single
        PASS. Empty when not produced or no punch window is wide enough.
    """
    if not _is_produced(plan):
        return []
    punches = [p for p in plan.get("punchIns") or []
               if p.get("role") != "aliveness"
               and "outStart" in p and "outEnd" in p
               and float(p["outEnd"]) - float(p["outStart"]) >= 2 * SMOOTH_EDGE_PAD_S]
    if not punches:
        return []
    cut_times = _cut_boundaries(plan)
    results: list[CheckResult] = []
    for p in punches:
        start, end = float(p["outStart"]), float(p["outEnd"])
        if _has_mid_snap(final_path, start, end, cut_times):
            results.append(CheckResult(
                "motion_smoothness", FAIL,
                f"smoothness: unexpected hard splice in push {start:.1f}-{end:.1f}s",
                f"cut-level scene change (>{SMOOTH_THR}) inside an eased push"))
    if results:
        return results
    return [CheckResult(
        "motion_smoothness", PASS, f"{len(punches)} punch window(s) smooth",
        f"no mid-window scene change > {SMOOTH_THR}")]
