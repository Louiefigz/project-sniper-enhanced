#!/usr/bin/env python3
"""graphics_stage — MG compositing stage (Phase MG-2), sibling to overlays.py.

Where ``overlays.py`` overlays the brand hook CARDS, this stage overlays the
brain's ``graphicsTrack`` MOTION graphics (stat cards, list builds, kinetic-quote
takeovers) — the alpha-video half of docs/producer/PRODUCER_MOTION_GRAPHICS_PLAN.md §3.3.
Neither stage touches the other; they run back to back on the same 9:16 cut.

Pipeline for one run:

1. RENDER each entry to an overlay clip via :mod:`graphics_render` (hyperframes +
   content-hash cache). ``free-band`` → transparent ProRes ``.mov``; ``own-screen``
   → opaque ``.mp4`` takeover.
2. COMPOSITE every clip onto the base in ONE ffmpeg pass — each clip's PTS is
   shifted to its ``outStart`` and it is ``enable``-gated to its window (§5.5.3).
   More than ``_CHUNK`` overlays split into extra passes to keep the filter graph
   robust; the frame count is asserted unchanged (±1) so the timeline can't drift.
3. SUPPRESS captions under own-screen takeovers: any burned-caption ASS event that
   overlaps a takeover window is dropped from ``--ass`` into ``--ass-out`` (§2.1 —
   the screen IS the visual; stacking captions on the takeover is double load).
4. VERIFY placements default-on (:mod:`graphics.placement_verify`, v3 item #5)
   + journal predicted-vs-measured geometry residuals to the A3 calibration
   ledger (:mod:`planner.geometry_calibration`) when ``--producer-dir`` is known.

CLI: graphics_stage.py <video_in> <graphics_track.json> <video_out>
       [--cache-dir DIR] [--ass in.ass --ass-out out.ass]
       [--occlusions occl.json] [--producer-dir DIR] [--band-y-offset PX]
  graphics_track.json = the plan's ``graphicsTrack`` array. Empty = passthrough.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # run-by-path: producer pkg root on sys.path
from planner.eye_trace import placement_row
from planner.graphics_anchors import _clip_dims
from graphics.delivery_geometry import (
    fallback_placement_evidence as _fallback_placement_evidence,
    fit_delivery_geometry as _delivery_geometry,
)
from graphics.composite_core import (
    CompositeOptions as _PassOpts,
    build_graph as _build_graph,
    composite,
    probe_frames as _probe_frames,
    run_command as _run,
)
from graphics.exit_on_cut import TAKEOVER_BASES
from graphics.graphics_render import render_entry
from graphics.pip_hole import entry_has_hole, hole_clip_fields
from graphics.placement_verify import (VerifyContext, resolve_severity,
                                       run_verify)
from graphics.stage_placement import emit, resolve_placement
from planner import geometry_calibration


# --------------------------------------------------------------------------- #
# Caption suppression under own-screen takeovers (§2.1)
# --------------------------------------------------------------------------- #
def _ass_time_to_s(stamp: str) -> float:
    """ASS ``H:MM:SS.cc`` timestamp → seconds."""
    hours, minutes, seconds = stamp.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _overlaps(start: float, end: float, windows: list[tuple[float, float]]) -> bool:
    """True if ``[start, end)`` intersects any ``[w0, w1)`` takeover window."""
    return any(start < w1 and end > w0 for w0, w1 in windows)


def suppress_captions(ass_in: str, ass_out: str,
                      windows: list[tuple[float, float]]) -> int:
    """Copy ``ass_in`` → ``ass_out``, dropping Dialogue events under takeovers.

    A ``Dialogue:`` line whose start/end (fields 2 and 3) overlaps any window is
    omitted; every other line — headers, styles, format rows, non-overlapping
    events — is passed through verbatim. Returns the dropped-event count.
    """
    with open(ass_in, encoding="utf-8") as f:
        lines = f.readlines()
    kept: list[str] = []
    dropped = 0
    for line in lines:
        if line.startswith("Dialogue:") and windows:
            fields = line.split(":", 1)[1].split(",")
            start, end = _ass_time_to_s(fields[1]), _ass_time_to_s(fields[2])
            if _overlaps(start, end, windows):
                dropped += 1
                continue
        kept.append(line)
    with open(ass_out, "w", encoding="utf-8") as f:
        f.writelines(kept)
    return dropped


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
@dataclass
class GraphicsJob:
    """One graphics-stage run (keeps the entry point ≤4 params)."""

    video_in: str
    video_out: str
    track: list[dict]
    cache_dir: str | None = None
    ass_in: str | None = None
    ass_out: str | None = None
    eof_pass: bool = False   # assemble path: guard the 1-in-4 dup stutter
    ydif_file: str | None = None   # inline YDIF metadata dump (assemble path)
    placements_out: str | None = None   # eye-trace placements sidecar (Audit B)
    occlusions: dict | None = None   # {broll: [[s,e]..], cards: [[s,e]..]} —
    #                                  the verify allow-vocabulary windows
    producer_dir: str | None = None  # dir owning geometry_predictions.json +
    #                                  the A3 residual ledger (calibration)
    band_y_offset_px: float = 0.0    # plan captions.bandYOffsetPx — occupancy
    #                                  models the band where captions render


def _clip_record(entry: dict, rendered: dict, video_in: str,
                 placed: tuple[int, int, dict]) -> dict:
    """Build one compositor record from rendered and delivery-space geometry."""
    x, y, meta = placed
    anchor = entry.get("anchor", "free-band")
    clip = {"path": rendered["path"], "outStart": float(entry["outStart"]),
            "outEnd": float(entry["outEnd"]), "anchor": anchor,
            "x": x, "y": y}
    base = entry.get("takeoverBase")
    if base is not None:
        if base not in TAKEOVER_BASES:
            raise ValueError(f"{rendered['kind']}: takeoverBase {base!r} not in "
                             f"{TAKEOVER_BASES}")
        clip["takeoverBase"] = base
    if entry.get("placement") is not None:
        clip["placed"] = True
    for source, target in (("scaledDims", "scaleDims"),
                           ("placedBBox", "placedBBox")):
        if meta.get(source):
            clip[target] = meta[source]
    if entry_has_hole(entry):
        clip["pipHole"] = hole_clip_fields(entry, video_in)
        emit(stage="graphics", status="pip_hole", kind=rendered["kind"],
             crop=list(clip["pipHole"]["crop"]),
             rect=list(clip["pipHole"]["rect"]))
    return clip


def _render_all(track: list[dict], cache_dir: str | None, video_in: str,
                band_y_offset_px: float = 0.0) -> tuple[list[dict], list[dict]]:
    """Render/reuse every entry; return ``(overlay clips, eye-trace rows)``.

    The anchor (for focus-shift blur) and the resolved face-relative ``(x, y)``
    offset are attached here so ``_build_graph`` stays a pure string-builder. The
    offset comes from Placement v2 (absolute free-space placement) using the
    just-rendered clip + the base ``video_in``; the status line carries the chosen
    region so a mis-place is visible in the log. The second list is one
    ``eye_trace.placement_row`` per entry (gaze read + landed bbox distance) —
    ``run_graphics_stage`` persists it for the Audit B advisory (LIAM move 4).
    """
    clips: list[dict] = []
    rows: list[dict] = []
    canvas = _clip_dims(video_in)
    for entry in track:
        res = render_entry(entry, cache_dir)
        anchor = entry.get("anchor", "free-band")
        x, y, meta = resolve_placement(entry, res["path"], video_in,
                                       band_y_offset_px)
        x, y, meta = _delivery_geometry(res["path"], (x, y), meta, canvas)
        meta = _fallback_placement_evidence(res["path"], (x, y), meta, canvas)
        row = placement_row(entry, meta, canvas)
        row["kind"] = res["kind"]
        rows.append(row)
        emit(stage="graphics", status="cached" if res["cached"] else "rendered",
             kind=res["kind"], key=res["key"], fmt=res["fmt"], anchor=anchor,
             offset=[x, y], region=meta.get("region"),
             fallback=meta.get("fallback", False),
             gazeDistFrac=row["gazeDistFrac"],
             outStart=float(entry["outStart"]), outEnd=float(entry["outEnd"]))
        clips.append(_clip_record(entry, res, video_in, (x, y, meta)))
    return clips, rows


def _passthrough(job: GraphicsJob) -> None:
    """No graphics → stream-copy the video and copy the ASS through untouched."""
    _run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", job.video_in,
          "-c", "copy", "-movflags", "+faststart", job.video_out])
    if job.ass_in and job.ass_out:
        suppress_captions(job.ass_in, job.ass_out, [])


def _clear_stale_placements(placements_out: str | None) -> None:
    """Remove a pre-existing placements sidecar an empty plan would strand.

    A seeded QC round copies the prior candidate's ``graphics_placements.json``
    beside the output; a repair that emptied ``graphicsTrack`` takes the
    passthrough, which never rewrites the sidecar — without this delete the
    prior round's stale placements would survive and be promoted as this
    round's evidence. ``os.remove`` failures raise (fail closed): never leave
    evidence behind that the current plan did not produce.
    """
    if not placements_out or not os.path.exists(placements_out):
        return
    os.remove(placements_out)
    emit(stage="graphics", status="placements_cleared", out=placements_out,
         reason="empty graphicsTrack owes no placements evidence")


def run_graphics_stage(job: GraphicsJob) -> dict:
    """Render → composite → assert frames → suppress takeover captions."""
    if not job.track:
        _clear_stale_placements(job.placements_out)
        _passthrough(job)
        emit(stage="graphics", status="passthrough", reason="no graphics")
        return {"graphics": 0, "passes": 0, "out": job.video_out}

    clips, rows = _render_all(job.track, job.cache_dir, job.video_in,
                              job.band_y_offset_px)
    if job.placements_out:
        # Eye-trace placements sidecar (LIAM move 4): the gaze read + landed
        # bbox per entry, persisted where Audit B can find it (advisory WARN).
        with open(job.placements_out, "w") as f:
            json.dump(rows, f, indent=1)
        emit(stage="graphics", status="placements_written",
             out=job.placements_out, entries=len(rows))
    frames_in = _probe_frames(job.video_in)
    passes = composite(job.video_in, clips, job.video_out,
                       _PassOpts(eof_pass=job.eof_pass, ydif_file=job.ydif_file))
    frames_out = _probe_frames(job.video_out)
    if abs(frames_out - frames_in) > 1:
        raise RuntimeError(
            f"graphics compositing changed the timeline: {frames_in} -> "
            f"{frames_out} frames (tolerance 1)")
    emit(stage="graphics", status="composited", passes=passes,
         clips=len(clips), frames_in=frames_in, frames_out=frames_out)
    if job.producer_dir:
        # Journal BEFORE verify: even a verify-blocked run yields honest
        # residual samples (the measurement succeeded; the placement didn't).
        geometry_calibration.journal_actuals(job.producer_dir, rows, emit)
    # Default-on post-composite verify (v3 item #5): WARN-with-evidence until
    # the A3 margin ledger calibrates, then FAIL; allow-vocabulary SKIPs and
    # operator-pin WARNs inside — a WARN-mode hit NEVER raises.
    severity, note = resolve_severity(job.producer_dir)
    run_verify(clips, job.video_out,
               VerifyContext(severity=severity, occlusions=job.occlusions,
                             emit=emit, note=note))

    summary = {"graphics": len(clips), "passes": passes, "out": job.video_out,
               "frames_in": frames_in, "frames_out": frames_out}
    if job.ass_in and job.ass_out:
        # Own-screen takeovers always suppress; a free-band TEXT card whose
        # copy verbatim-matches the spoken words may declare suppressCaptions
        # to discharge LESSON-022 (no frame shows captions + card text
        # simultaneously) - brain-declared intent, render-executed.
        windows = [(float(e["outStart"]), float(e["outEnd"])) for e in job.track
                   if e.get("anchor") == "own-screen"
                   or e.get("suppressCaptions") is True]
        dropped = suppress_captions(job.ass_in, job.ass_out, windows)
        emit(stage="graphics", status="captions_suppressed",
             takeovers=len(windows), dropped=dropped, out=job.ass_out)
        summary["captions_dropped"] = dropped
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="PRODUCER MG stage: graphics compositing")
    ap.add_argument("video_in")
    ap.add_argument("track_path", help="the plan's graphicsTrack array (JSON)")
    ap.add_argument("video_out")
    ap.add_argument("--cache-dir", default=None,
                    help="content-hash render cache (default: templates/motion/renders/cache)")
    ap.add_argument("--ass", dest="ass_in", default=None,
                    help="burned-caption ASS to filter under own-screen takeovers")
    ap.add_argument("--ass-out", dest="ass_out", default=None,
                    help="where the filtered ASS is written (required with --ass)")
    ap.add_argument("--placements-out", default=None,
                    help="write the eye-trace placements sidecar here (Audit B)")
    ap.add_argument("--occlusions", default=None,
                    help="JSON file {broll:[[s,e]..], cards:[[s,e]..]} — plan "
                         "windows the verify allow-vocabulary excuses")
    ap.add_argument("--producer-dir", default=None,
                    help="producer dir owning geometry_predictions.json + the "
                         "A3 residual ledger (flips verify WARN→FAIL)")
    ap.add_argument("--band-y-offset", type=float, default=0.0,
                    help="plan captions.bandYOffsetPx — model the caption "
                         "band where the captions actually render")
    args = ap.parse_args()
    if bool(args.ass_in) != bool(args.ass_out):
        ap.error("--ass and --ass-out must be given together")
    try:
        with open(args.track_path) as f:
            track = json.load(f)
        occlusions = None
        if args.occlusions:
            with open(args.occlusions) as f:
                occlusions = json.load(f)
        job = GraphicsJob(video_in=args.video_in, video_out=args.video_out,
                          track=track, cache_dir=args.cache_dir,
                          ass_in=args.ass_in, ass_out=args.ass_out,
                          placements_out=args.placements_out,
                          occlusions=occlusions,
                          producer_dir=args.producer_dir,
                          band_y_offset_px=args.band_y_offset)
        summary = run_graphics_stage(job)
        emit(status="done", **summary)
    except (OSError, json.JSONDecodeError, KeyError, ValueError, RuntimeError) as exc:
        emit(error=str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
