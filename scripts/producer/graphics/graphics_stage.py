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
   Overlay count does not add full-duration picture generations; the frame count
   is asserted unchanged (±1) so the timeline cannot drift.
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
from graphics.caption_suppression import _overlaps, suppress_captions
from graphics.frame_quantization import bind_graphic_frame_windows, require_graphic_frame_clock
from graphics.exit_on_cut import TAKEOVER_BASES
from graphics.graphics_render import render_entry_at_rate as render_entry
from graphics.pip_hole import entry_has_hole, hole_clip_fields
from graphics.placement_verify import (VerifyContext, resolve_severity,
                                       run_verify)
from graphics.stage_placement import emit, resolve_placement
from graphics.owned_execution import (
    GraphicsComposition, OwnedGraphicsExecution, compose_owned, current, render_owned,
)
from planner import geometry_calibration


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
    graphic_frame_clock: tuple[str, int] | None = None  # Internal exact-frame opt-in.
    owned_graphics: OwnedGraphicsExecution | None = None  # Internal live owner only.


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
                           ("placedBBox", "placedBBox"),
                           ("expandedFace", "expandedFace")):
        if meta.get(source):
            clip[target] = meta[source]
    if meta.get("faceAware"):
        clip["faceAware"] = True
    if entry_has_hole(entry):
        clip["pipHole"] = hole_clip_fields(entry, video_in)
        emit(stage="graphics", status="pip_hole", kind=rendered["kind"],
             crop=list(clip["pipHole"]["crop"]),
             rect=list(clip["pipHole"]["rect"]))
    return clip


def _clip_fps(video_in: str) -> object:
    """Exact-stream rate projected to HyperFrames' positive numeric CLI."""
    from media_probe import _fps_fraction, probe_video
    fps = _fps_fraction(probe_video(video_in)["r_frame_rate"])
    if fps <= 0:
        raise RuntimeError("graphics base video has no positive frame rate")
    return fps


def _render_all(job: GraphicsJob) -> tuple[list[dict], list[dict]]:
    """Render/reuse entries with Placement v2 and emit Audit B eye-trace rows."""
    clips: list[dict] = []
    rows: list[dict] = []
    video_in, canvas = job.video_in, _clip_dims(job.video_in)
    fps, owned = _clip_fps(video_in), current(job)
    for order, entry in enumerate(job.track):
        res = (render_owned(owned, entry, order) if owned
               else render_entry(entry, job.cache_dir, fps))
        anchor = entry.get("anchor", "free-band")
        x, y, meta = resolve_placement(entry, res["path"], video_in,
                                       job.band_y_offset_px)
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


def _compose_actual(job: GraphicsJob, clips: list[dict]) -> tuple[int, dict]:
    """Keep one ordinary graph; an owned encode returns its exact prefix proof."""
    clock, owned = job.graphic_frame_clock, current(job)
    options = _PassOpts(eof_pass=job.eof_pass, ydif_file=job.ydif_file,
                       frame_rate=clock[0] if clock else None, video_only=clock is not None)
    if owned is None:
        return composite(job.video_in, clips, job.video_out, options), {}
    if clock is None or not job.eof_pass:
        raise RuntimeError("owned graphics requires an exact-frame EOF-pass composition")
    value = GraphicsComposition(job.video_in, job.video_out, tuple(clips), options,
                                tuple(_clip_dims(job.video_in)), clock)
    return 1, {"ownedCompositionEvidence": compose_owned(owned, value)}


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


def _write_placements(path: str | None, rows: list[dict]) -> None:
    """Persist placement evidence when the caller requested a sidecar."""
    if not path:
        return
    with open(path, "w") as handle:
        json.dump(rows, handle, indent=1)
    emit(stage="graphics", status="placements_written",
         out=path, entries=len(rows))


def run_graphics_stage(job: GraphicsJob) -> dict:
    """Render → composite → assert frames → suppress takeover captions."""
    clock = job.graphic_frame_clock
    owned = current(job)
    if owned is not None and (clock is None or not job.eof_pass):
        raise RuntimeError("owned graphics requires an exact-frame EOF-pass composition")
    if clock is not None:
        clock = require_graphic_frame_clock(clock, (_clip_fps(job.video_in), _probe_frames(job.video_in)))
        bind_graphic_frame_windows(job.track, clock)  # Fail before any catalog execution.
    if not job.track and owned is None:
        _clear_stale_placements(job.placements_out)
        _passthrough(job)
        emit(stage="graphics", status="passthrough", reason="no graphics")
        return {"graphics": 0, "passes": 0, "out": job.video_out}

    clips, rows = _render_all(job)
    clips = bind_graphic_frame_windows(clips, clock) if clock is not None else clips
    _write_placements(job.placements_out, rows)
    frames_in = clock[1] if clock is not None else _probe_frames(job.video_in)
    passes, owned_evidence = _compose_actual(job, clips)
    frames_out = _verified_frame_count(job, frames_in)
    emit(stage="graphics", status="composited", passes=passes,
         clips=len(clips), frames_in=frames_in, frames_out=frames_out)
    if job.producer_dir:
        # Journal BEFORE verify: even a verify-blocked run yields honest
        # residual samples (the measurement succeeded; the placement didn't).
        geometry_calibration.journal_actuals(job.producer_dir, rows, emit)
    # Existing post-composite verification keeps its A3-calibrated severity.
    severity, note = resolve_severity(job.producer_dir)
    run_verify(clips, job.video_out,
               VerifyContext(severity=severity, occlusions=job.occlusions,
                             emit=emit, note=note))

    summary = {"graphics": len(clips), "passes": passes, "out": job.video_out,
               "frames_in": frames_in, "frames_out": frames_out, **owned_evidence}
    _suppress_authored_captions(job, summary)
    current(job)
    return summary


def _suppress_authored_captions(job: GraphicsJob, summary: dict) -> None:
    """Retain the ordinary takeover/text-caption rule for both execution paths."""
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


def _verified_frame_count(job: GraphicsJob, frames_in: int) -> int:
    """Retain legacy tolerance; exact-frame callers cannot lose or gain a frame."""
    frames_out = _probe_frames(job.video_out)
    tolerance = 0 if job.graphic_frame_clock is not None else 1
    if abs(frames_out - frames_in) > tolerance:
        raise RuntimeError(f"graphics compositing changed the timeline: {frames_in} -> "
                           f"{frames_out} frames (tolerance {tolerance})")
    return frames_out


def main() -> None:
    """Keep the existing ordinary CLI; owned execution is not a command flag."""
    from graphics.graphics_stage_cli import main as cli_main
    cli_main()


if __name__ == "__main__":
    main()
