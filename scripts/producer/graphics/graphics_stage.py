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

CLI: graphics_stage.py <video_in> <graphics_track.json> <video_out>
       [--cache-dir DIR] [--ass in.ass --ass-out out.ass]
  graphics_track.json = the plan's ``graphicsTrack`` array. Empty = passthrough.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # run-by-path: producer pkg root on sys.path
from planner.eye_trace import placement_row
from planner.graphics_anchors import (FACE_ANCHORS, _clip_dims, _content_bbox,
                              resolve_offset, resolve_offset_v2, scale_geometry)
from graphics.delivery_geometry import (
    fallback_placement_evidence as _fallback_placement_evidence,
    fit_delivery_geometry as _delivery_geometry,
)
from graphics.exit_on_cut import TAKEOVER_BASES
from graphics.graphics_render import render_entry
from graphics.pip_hole import entry_has_hole, hole_clip_fields
from motion.recompose import requires_recompose
from producer_config import ENCODE, CANVAS, PLACEMENT_SCALE

# Chunk cap on overlay inputs per ffmpeg pass — big filter graphs get fragile
# (§5.5.3). ≤ this many clips composite in one pass; more spill into extra passes.
_CHUNK = 8

# Focus-shift blur (R5): a full-frame data graphic over a BLURRED base — the
# speaker recedes, the data stars, the speaker returns. boxblur luma radius 20
# is the operator's calibration (docs/studies/REFERENCE_STYLE_STUDY.md R5). The blur is
# gated to the graphic's own window (split -> blur -> overlay=enable), a hard
# but ROBUST + deterministic gate — the alpha graphic's own 0.5s fade-in masks
# the onset, and enable-gating (vs an xfade) keeps the frame count exact so the
# ±1 timeline assertion still holds. Captions are NOT suppressed under it (unlike
# own-screen): the screen blurs back, so the speaker keeps talking under it.
_FOCUS_BLUR = 20

# Blur+desat takeover base (G5 — JADEN_STYLE.md §5.4 E4, 8 instances/4 reels
# HIGH): the live frame goes gaussian-blurred + DESATURATED mid-shot (measured
# apply 1-2 frames; σ≈20-30) while VO continues, sharp content pops over it,
# and a hard cut restores colour/sharp in 1 frame. Gated to an explicit plan
# request only: entry ``"takeoverBase": "blur-desat"``. Same enable-gate
# pattern as focus-shift (1-frame on/off = the measured hard apply/restore;
# pair the entry with ``exitOnCut`` so the restore rides the cut), with
# gblur (true gaussian) + hue=s=0 instead of boxblur.
_TAKEOVER_SIGMA = 24


def emit(**fields) -> None:
    """One NDJSON status line on stdout (matches the sibling render stages)."""
    print(json.dumps(fields), flush=True)


def _run(cmd: list[str]) -> None:
    """Run an ffmpeg command; raise RuntimeError with the stderr tail on failure."""
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or proc.stdout).strip().splitlines()[-8:])
        raise RuntimeError(f"{cmd[0]} failed ({proc.returncode}):\n{tail}")


def _probe_frames(path: str) -> int:
    """Exact video frame count via PACKET count (container read, no decode).

    ``-count_frames`` fully DECODES the stream (measured 16.5s on the 108s e2e
    base). On our own H.264 MP4s every video packet is exactly one access unit
    = one frame (progressive, one-frame-per-packet muxing — no field pairing),
    so ``nb_read_packets == nb_read_frames``; verified identical (2598) on the
    e2e base while running 0.085s instead of 16.5s.
    """
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
         "-show_entries", "stream=nb_read_packets", "-of",
         "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}: {proc.stderr.strip()[-200:]}")
    return int(proc.stdout.strip())


# --------------------------------------------------------------------------- #
# Compositing — single-pass overlay batching (§5.5.3), chunked for robustness
# --------------------------------------------------------------------------- #
@dataclass
class _Graph:
    """filter_complex accumulator — carries the parts list + the eof_action mode
    so ``_overlay_clip`` stays ≤4 params (the house limit)."""

    parts: list[str]
    eof_pass: bool = False


def _overlay_clip(prev: str, clip: dict, idx: int, g: _Graph) -> str:
    """Composite one clip onto ``prev``; return the new head label.

    focus-shift (R5) first BLURS the base under the window (split → boxblur →
    overlay=enable), then the alpha graphic composites on top. Every other anchor
    overlays the graphic directly. A face-relative offset ``x``/``y`` translates
    the overlay; ``x=0:y=0`` reproduces the byte-stable MG-1 string exactly.

    ``g.eof_pass`` appends ``:eof_action=pass`` to the graphic overlay — MANDATORY
    when compositing many short clips over a long base (the assemble path): with
    the ffmpeg default (``repeat``) the frame scheduler juggling several
    ended-but-repeating inputs duplicates ~1-in-4 OUTPUT frames (a CFR-costumed
    judder, invisible to frame counts) — the video-editor's incremental-graphics
    stutter trap. Off by default so the mid-pipeline pass stays byte-stable.
    """
    s, e = float(clip["outStart"]), float(clip["outEnd"])
    gate = f"enable='between(t,{s:.4f},{e:.4f})'"
    if clip.get("pipHole"):
        # NATEHERK item 9: fill the hole-comp's transparent face hole — crop
        # the BASE to the hole's aspect (face-centred), scale it into the
        # rect and overlay it UNDER the comp, gated to the window. The comp's
        # rounded mask covers the rectangle's corners (rounding is free) and
        # its ring/shadow draws over the footage. Timestamps are untouched:
        # the PIP shows the SAME instant as the base (the live face bridge).
        cw, ch, cx, cy = clip["pipHole"]["crop"]
        hx, hy, hw, hh = clip["pipHole"]["rect"]
        g.parts.append(f"{prev}split[ph{idx}a][ph{idx}b]")
        g.parts.append(f"[ph{idx}b]crop={cw}:{ch}:{cx}:{cy},"
                       f"scale={hw}:{hh}:flags=lanczos[ph{idx}s]")
        based = f"[phb{idx}]"
        g.parts.append(f"[ph{idx}a][ph{idx}s]overlay=x={hx}:y={hy}:{gate}{based}")
        prev = based
    if clip.get("takeoverBase") == "blur-desat":
        # G5: gaussian blur + desaturate the FOOTAGE under this window (E4).
        # Enable-gating = the measured 1-2 frame hard apply/restore.
        g.parts.append(f"{prev}split[tb{idx}a][tb{idx}b]")
        g.parts.append(f"[tb{idx}b]gblur=sigma={_TAKEOVER_SIGMA},"
                       f"hue=s=0[tb{idx}bd]")
        based = f"[tbb{idx}]"
        g.parts.append(f"[tb{idx}a][tb{idx}bd]overlay={gate}{based}")
        prev = based
    if clip.get("anchor") == "focus-shift":
        g.parts.append(f"{prev}split[fb{idx}a][fb{idx}b]")
        g.parts.append(f"[fb{idx}b]boxblur={_FOCUS_BLUR}[fb{idx}bl]")
        blurred = f"[fbl{idx}]"
        g.parts.append(f"[fb{idx}a][fb{idx}bl]overlay={gate}{blurred}")
        prev = blurred
    x, y = int(clip.get("x", 0)), int(clip.get("y", 0))
    xy = f"x={x}:y={y}:" if (x or y) else ""
    eof = ":eof_action=pass" if g.eof_pass else ""
    out = f"[gc{idx}]"
    g.parts.append(f"{prev}[ov{idx}]overlay={xy}{gate}:format=auto{eof}{out}")
    return out


def _build_graph(clips: list[dict], eof_pass: bool = False) -> tuple[str, str]:
    """filter_complex overlaying N clips (inputs 1..N) onto the base (input 0).

    Each clip is time-shifted so its frame 0 lands at ``outStart`` and gated to
    its window; ``format=auto`` lets ProRes alpha blend and opaque takeovers
    cover. Returns ``(graph, final_label)`` — the proven MG-1 recipe, generalized
    to N and to the R5 focus-shift + R3/R4 face-relative anchors. A clip with
    ``scaleDims`` (placement.scale ≠ 1) is resized to those EVEN dims (lanczos —
    the crispest resampler for graphic edges) before the PTS shift; without the
    key the chain string is byte-identical to the unscaled recipe.
    """
    g = _Graph(parts=[], eof_pass=eof_pass)
    for i, c in enumerate(clips):
        s = float(c["outStart"])
        pre = ""
        if c.get("scaleDims"):
            sw, sh = c["scaleDims"]
            pre = f"scale={sw}:{sh}:flags=lanczos,"
        g.parts.append(f"[{i + 1}:v]{pre}setpts=PTS-STARTPTS+{s:.4f}/TB[ov{i}]")
    prev = "[0:v]"
    for i, c in enumerate(clips):
        prev = _overlay_clip(prev, c, i, g)
    return ";".join(g.parts), prev


@dataclass
class _PassOpts:
    """Per-pass compositing options (keeps the pass functions ≤4 params)."""

    eof_pass: bool = False
    ydif_file: str | None = None   # inline smoothness tap (final pass only)


def _composite_pass(video_in: str, clips: list[dict], video_out: str,
                    opts: _PassOpts) -> None:
    """One ffmpeg pass: overlay ``clips`` onto ``video_in`` → mezzanine ``video_out``.

    Video re-encodes at CRF 12 with ``ENCODE['composite_preset']`` (veryfast —
    measured 16.9s→9.4s vs mezzanine_preset with CRF still governing quality);
    audio is copied through, and the frame count is preserved (overlay is bound
    to the main input). With ``opts.ydif_file`` the final label is split and a
    signalstats YDIF metadata dump rides the same encode pass as a second null
    output — folding the smoothness probe INTO the composite (one decode
    instead of a separate 11.6s full-decode probe). NOTE: the tap measures the
    PRE-encode filtergraph frames — the eof_action dup bug is produced by the
    overlay frame scheduler, so it is fully visible here (the encoder itself
    never duplicates frames); the 0.08 threshold in assemble.py is unchanged.
    """
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", video_in]
    for c in clips:
        cmd += ["-i", c["path"]]
    graph, final = _build_graph(clips, opts.eof_pass)
    map_label, extra = final, []
    if opts.ydif_file:
        esc = opts.ydif_file.replace("'", r"'\''")
        graph += (f";{final}split[venc][vchk];"
                  f"[vchk]signalstats,metadata=print:key=lavfi.signalstats.YDIF"
                  f":file='{esc}'[vydif]")
        map_label, extra = "[venc]", ["-map", "[vydif]", "-f", "null", "-"]
    cmd += ["-filter_complex", graph, "-map", map_label, "-map", "0:a?",
            "-c:v", ENCODE["vcodec"], "-crf", str(ENCODE["mezzanine_crf"]),
            "-preset", ENCODE["composite_preset"], "-pix_fmt", CANVAS["pix_fmt"],
            "-c:a", "copy", "-movflags", "+faststart", video_out, *extra]
    _run(cmd)


def composite(video_in: str, clips: list[dict], video_out: str,
              opts: _PassOpts | None = None) -> int:
    """Overlay all ``clips`` onto ``video_in``; chunk into ≤``_CHUNK`` per pass.

    Returns the number of ffmpeg passes. Chunked passes chain through temp
    intermediates (base of pass k+1 = output of pass k) beside ``video_out``.
    ``opts`` forwards the stutter-guard eof_action (see ``_overlay_clip``) and
    the inline YDIF tap — the tap rides the FINAL pass only (it must measure
    the finished composite, not an intermediate chunk).
    """
    opts = opts or _PassOpts()
    ordered = sorted(clips, key=lambda c: float(c["outStart"]))
    chunks = [ordered[i:i + _CHUNK] for i in range(0, len(ordered), _CHUNK)]
    if len(chunks) == 1:
        _composite_pass(video_in, chunks[0], video_out, opts)
        return 1
    mid = _PassOpts(eof_pass=opts.eof_pass, ydif_file=None)
    tmp = tempfile.mkdtemp(prefix="graphics-passes-",
                           dir=os.path.dirname(os.path.abspath(video_out)))
    try:
        src = video_in
        for idx, chunk in enumerate(chunks):
            last = idx == len(chunks) - 1
            dst = video_out if last else os.path.join(tmp, f"pass_{idx:02d}.mp4")
            _composite_pass(src, chunk, dst, opts if last else mid)
            src = dst
        return len(chunks)
    finally:
        for name in os.listdir(tmp):
            os.remove(os.path.join(tmp, name))
        os.rmdir(tmp)


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


def _placement_xy(entry: dict) -> tuple[float, float]:
    """Validate + unpack an entry's explicit ``placement`` — fail loud, never guess.

    Contract: ``placement = {"x": px, "y": px}`` in COMP-CANVAS px (the comp's
    authored 1080x1920 / 1920x1080 canvas). ``_delivery_geometry`` scales this
    authored geometry when delivery is a higher same-aspect resolution.
    own-screen takeovers are full-frame and never placed.
    """
    p = entry["placement"]
    if entry.get("anchor", "free-band") == "own-screen":
        raise ValueError("own-screen takeovers are full-frame — placement is illegal")
    if not isinstance(p, dict):
        raise ValueError(f"placement must be an object {{x, y}}; got {p!r}")
    for name in ("x", "y"):
        v = p.get(name)
        if isinstance(v, bool) or not isinstance(v, (int, float)) \
                or not math.isfinite(float(v)):
            raise ValueError(f"placement.{name} must be a finite number; got {v!r}")
    return float(p["x"]), float(p["y"])


def _placement_scale(entry: dict) -> float:
    """Validated ``placement.scale`` (1.0 when absent) — fail loud, never clamp.

    Contract: an optional uniform scale on the rendered comp clip, applied about
    the placement point (the SCALED content bbox top-left stays pinned at
    {x, y}). Bounds are ``PLACEMENT_SCALE`` — the raster-quality band: comps
    raster at their authored canvas, so downscaling stays crisp while upscaling
    interpolates (soft); ≤1.5 keeps that softness invisible at delivery res.
    own-screen is already unplaceable (``_placement_xy``), so it is unscalable.
    """
    s = entry["placement"].get("scale")
    if s is None:
        return 1.0
    if isinstance(s, bool) or not isinstance(s, (int, float)) \
            or not math.isfinite(float(s)):
        raise ValueError(f"placement.scale must be a finite number; got {s!r}")
    lo, hi = PLACEMENT_SCALE["min"], PLACEMENT_SCALE["max"]
    if not lo <= float(s) <= hi:
        raise ValueError(f"placement.scale {float(s):g} outside [{lo},{hi}]")
    return float(s)


def _explicit_offset(entry: dict, mov_path: str) -> tuple[int, int, dict]:
    """Overlay ``(dx, dy)`` pinning the comp's rendered CONTENT top-left at the
    entry's explicit ``placement`` point (comp-canvas px). The operator's drag
    WINS over every anchor heuristic; measurement failure raises (an explicit
    pin must never silently fall back to an anchor guess). An optional
    ``placement.scale`` resizes the clip uniformly about the pin (the scaled
    content top-left stays at {x, y}); absent = the untouched 1.0 path — no
    dims probe, byte-identical offsets and filter graph."""
    x, y = _placement_xy(entry)
    scale = _placement_scale(entry)
    content = _content_bbox(mov_path)
    meta = {"anchor": entry.get("anchor", "free-band"),
            "region": "explicit-placement", "fallback": False,
            "placement": [x, y], "contentBBox": list(content)}
    if scale == 1.0:
        dx, dy = int(round(x - content[0])), int(round(y - content[1]))
        meta["placedBBox"] = [content[0] + dx, content[1] + dy,
                              content[2] + dx, content[3] + dy]
        return dx, dy, meta
    geo = scale_geometry(content, (x, y), _clip_dims(mov_path), scale)
    meta.update(scale=scale, scaledDims=[geo["w"], geo["h"]],
                placedBBox=list(geo["placed"]))
    return geo["dx"], geo["dy"], meta


def _fixed_overlay_offset(entry: dict, mov_path: str) -> tuple[int, int, dict]:
    """Keep a full-canvas edge rail at its authored origin."""
    content = _content_bbox(mov_path)
    meta = {"anchor": entry.get("anchor", "beside-face"),
            "region": "fixed-canvas", "fallback": False,
            "contentBBox": list(content), "placedBBox": list(content)}
    return 0, 0, meta


def _placement(entry: dict, mov_path: str, video_in: str) -> tuple[int, int, dict]:
    """Resolve one entry's overlay offset — explicit placement, else anchors.

    PRECEDENCE: an explicit ``entry.placement`` {x, y} wins outright (see
    ``_explicit_offset``) and never falls back. Otherwise the anchor path is
    UNTOUCHED: Placement v2 measures the frame's free space + the clip's own
    footprint and places it into the emptiest legal region (the fix for
    graphics-on-the-face). If measurement can't run (no cv2, no face + no bbox
    hint, ffmpeg probe fail) it degrades to the v1 deviation nudge and SAYS SO
    — never a silent mis-place.
    """
    anchor = entry.get("anchor", "free-band")
    if anchor == "own-screen" and entry.get("placement") is None:
        comp_w, comp_h = _clip_dims(mov_path)
        video_w, video_h = _clip_dims(video_in)
        comp_aspect = comp_w / comp_h
        video_aspect = video_w / video_h
        if abs(comp_aspect - video_aspect) > 0.002:
            raise ValueError(
                f"own-screen comp {comp_w}x{comp_h} does not match delivery "
                f"aspect {video_w}x{video_h}")
        meta = {"anchor": anchor, "region": "full-frame", "fallback": False,
                "contentBBox": [0, 0, comp_w, comp_h],
                "placedBBox": [0, 0, video_w, video_h],
                "canvas": [video_w, video_h]}
        if (comp_w, comp_h) != (video_w, video_h):
            meta["scaledDims"] = [video_w, video_h]
        return 0, 0, meta
    if entry.get("placement") is not None:
        return _explicit_offset(entry, mov_path)
    if requires_recompose(entry):
        return _fixed_overlay_offset(entry, mov_path)
    try:
        x, y, meta = resolve_offset_v2(entry, mov_path, video_in)
        return x, y, meta
    except (RuntimeError, ValueError, OSError, ImportError, KeyError) as exc:
        x, y = resolve_offset(entry)
        return x, y, {"anchor": entry.get("anchor", "free-band"),
                      "region": "v1-fallback", "fallback": True,
                      "reason": str(exc)[:200]}


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


def _render_all(track: list[dict], cache_dir: str | None,
                video_in: str) -> tuple[list[dict], list[dict]]:
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
        x, y, meta = _placement(entry, res["path"], video_in)
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


def _verify_placements(clips: list[dict], video_out: str) -> None:
    """Opt-in (env SNIPER_VERIFY_PLACEMENT): re-measure the composite; raise on hit.

    For each face-anchor clip, probe its content footprint, apply the placement
    offset, and assert the graphic clears the RE-MEASURED face+hair in the final
    render (the sibling ``--verify`` concept — an independent post-composite check,
    not the render-time prediction). Emits a status per clip; raises so a strict
    verify run exits non-zero. Off by default: no cost / no behaviour change.
    """
    from planner.free_space import verify_placement

    failures = []
    for clip in clips:
        # An explicit placement is the operator's pin — face clearance is their
        # call (lint already warned on SAFE_BOX taste); only verify anchor picks.
        if clip.get("placed") or clip.get("anchor") not in FACE_ANCHORS:
            continue
        placed = clip.get("placedBBox")
        if placed is None:
            content = _content_bbox(clip["path"])
            dx, dy = int(clip.get("x", 0)), int(clip.get("y", 0))
            placed = (content[0] + dx, content[1] + dy,
                      content[2] + dx, content[3] + dy)
        ok, detail = verify_placement(video_out, clip["outStart"], clip["outEnd"], placed)
        emit(stage="graphics", status="placement_verified",
             anchor=clip.get("anchor"), **detail)
        if not ok:
            failures.append(detail)
    if failures:
        raise RuntimeError(f"placement verify failed for {len(failures)} graphic(s)")


def run_graphics_stage(job: GraphicsJob) -> dict:
    """Render → composite → assert frames → suppress takeover captions."""
    if not job.track:
        _passthrough(job)
        emit(stage="graphics", status="passthrough", reason="no graphics")
        return {"graphics": 0, "passes": 0, "out": job.video_out}

    clips, rows = _render_all(job.track, job.cache_dir, job.video_in)
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
    if os.environ.get("SNIPER_VERIFY_PLACEMENT"):
        _verify_placements(clips, job.video_out)

    summary = {"graphics": len(clips), "passes": passes, "out": job.video_out,
               "frames_in": frames_in, "frames_out": frames_out}
    if job.ass_in and job.ass_out:
        windows = [(float(e["outStart"]), float(e["outEnd"])) for e in job.track
                   if e.get("anchor") == "own-screen"]
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
    args = ap.parse_args()
    if bool(args.ass_in) != bool(args.ass_out):
        ap.error("--ass and --ass-out must be given together")
    try:
        with open(args.track_path) as f:
            track = json.load(f)
        job = GraphicsJob(video_in=args.video_in, video_out=args.video_out,
                          track=track, cache_dir=args.cache_dir,
                          ass_in=args.ass_in, ass_out=args.ass_out,
                          placements_out=args.placements_out)
        summary = run_graphics_stage(job)
        emit(status="done", **summary)
    except (OSError, json.JSONDecodeError, KeyError, ValueError, RuntimeError) as exc:
        emit(error=str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
