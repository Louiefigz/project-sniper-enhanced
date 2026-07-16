#!/usr/bin/env python3
"""reframe — stage 2: turn the stage-1 mezzanine into a 1080x1920 vertical cut.

The input ``<in.mp4>`` is the CONCATENATED cut+speed mezzanine, so the crop
windows from ``face_track.py`` apply to OUTPUT time ranges (each window carries
its ``outStart``/``outEnd``). Strategies (docs/producer/PRODUCER_PLAN.md §4.2):

- ``face``   — per-shot crop at each window's ``cropCenterX`` (center-fallback
  windows are already centered), scaled to canvas. Implemented as per-range
  extract → crop → concat (robust: each range independently encoded) rather
  than one fragile mega filtergraph. Ranges are cut on the mezzanine's FRAME
  GRID (``trim=start_frame`` on shared, endpoint-pinned frame indexes), not in
  seconds, so the parts telescope to EXACTLY the input frame count with no
  per-range rounding drift (edge F7); audio is copy-muxed from the mezzanine
  once at the end, since the reframe only touches the video side.
- ``center`` — one centered largest-possible 9:16 crop over the whole file
  (deterministic geometry; needs no detection).
- ``blurpad``— full frame fit inside the canvas over a blurred, darkened
  fill of itself (for content that must not be cropped).
- ``none``   — passthrough stream-copy (longform 16:9 keeps its frame).

All re-encodes are near-lossless x264 (CRF from ``ENCODE['mezzanine_crf']``);
output is ``setsar=1``, ``yuv420p``, fps left untouched (passthrough).

CLI: reframe.py <in.mp4> <windows.json> <out.mp4> --strategy face|center|blurpad|none
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from fractions import Fraction

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # run-by-path: producer pkg root on sys.path
from producer_config import CANVAS, ENCODE

_CW, _CH = CANVAS["width"], CANVAS["height"]
_PIX = CANVAS["pix_fmt"]


# --------------------------------------------------------------------------- #
# ffmpeg / ffprobe helpers.
# --------------------------------------------------------------------------- #
def _run(cmd: list[str]) -> None:
    """Run an ffmpeg/ffprobe command, raising with stderr on failure."""
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-6:])
        raise RuntimeError(f"{cmd[0]} failed ({proc.returncode}):\n{tail}")


def probe_dims(path: str) -> tuple[int, int]:
    """Return the (width, height) of the first video stream via ffprobe."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", path],
        capture_output=True, text=True)
    if out.returncode != 0 or "x" not in out.stdout:
        raise RuntimeError(f"ffprobe could not read dimensions of {path}")
    w, h = out.stdout.strip().split("x")[:2]
    return int(w), int(h)


def _even(n: float) -> int:
    return int(round(n / 2.0)) * 2


def _video_only_args() -> list[str]:
    """Near-lossless x264 VIDEO args. The face parts deliberately omit audio —
    they carry it via a final copy-mux from the mezzanine, not per-part."""
    return ["-c:v", ENCODE["vcodec"], "-crf", str(ENCODE["mezzanine_crf"]),
            "-preset", ENCODE["mezzanine_preset"], "-pix_fmt", _PIX]


def _video_encode_args() -> list[str]:
    """Near-lossless x264 + normalised audio — the center/blurpad uniform paths
    re-encode both streams in a single pass (no frame drift to worry about)."""
    return _video_only_args() + [
        "-c:a", ENCODE["acodec"], "-b:a", ENCODE["audio_bitrate"],
        "-ar", str(ENCODE["audio_rate"]), "-ac", str(ENCODE["audio_channels"])]


def _fps_and_frames(path: str) -> tuple[Fraction, int]:
    """Exact CFR fps + total video frame count (packet count, no decode).

    The frame count is the grid length the face parts must telescope to, and
    the fps converts each window's ``outStart`` (seconds) to a grid index.
    """
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
         "-show_entries", "stream=r_frame_rate,nb_read_packets", "-of", "json",
         path], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"ffprobe could not read fps/frames of {path}")
    st = json.loads(out.stdout)["streams"][0]
    num, den = (str(st["r_frame_rate"]).split("/") + ["1"])[:2]
    return Fraction(int(num), int(den)), int(st["nb_read_packets"])


# --------------------------------------------------------------------------- #
# Filter builders (pure strings — easy to eyeball/verify).
# --------------------------------------------------------------------------- #
def crop_scale_vf(frame_w: int, frame_h: int) -> str:
    """Largest centered 9:16 crop of any frame, scaled to the canvas.

    Wider-than-9:16 frames are cropped on width, taller ones on height — so a
    landscape source keeps native resolution and a portrait one passes through.
    """
    target = _CW / _CH
    if frame_w / frame_h > target:                 # landscape / square
        cw, ch = min(_even(frame_h * _CW / _CH), _even(frame_w)), _even(frame_h)
    else:                                          # portrait
        cw, ch = _even(frame_w), min(_even(frame_w * _CH / _CW), _even(frame_h))
    x, y = _even((frame_w - cw) / 2.0), _even((frame_h - ch) / 2.0)
    return (f"crop={cw}:{ch}:{x}:{y},scale={_CW}:{_CH}:flags=bicubic,"
            f"setsar=1,format={_PIX}")


def face_window_vf(window: dict) -> str:
    """Crop a single shot at its ``cropCenterX`` then scale to the canvas."""
    fw, fh = int(window["frameWidth"]), int(window["frameHeight"])
    if window.get("strategy") == "portrait-passthrough":
        return crop_scale_vf(fw, fh)
    cw = min(_even(window["cropWidth"]), _even(fw))
    x = _even(min(max(window["cropCenterX"] - cw / 2.0, 0), fw - cw))
    return (f"crop={cw}:{fh}:{x}:0,scale={_CW}:{_CH}:flags=bicubic,"
            f"setsar=1,format={_PIX}")


def blurpad_filter() -> str:
    """Frame fitted inside a blurred, darkened cover of itself (filter_complex)."""
    return (
        "[0:v]split=2[bg][fg];"
        f"[bg]scale={_CW}:{_CH}:force_original_aspect_ratio=increase,"
        f"crop={_CW}:{_CH},boxblur=20:2,eq=brightness=-0.12[bgb];"
        f"[fg]scale={_CW}:{_CH}:force_original_aspect_ratio=decrease:flags=bicubic[fgs];"
        f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1,format={_PIX}[v]")


# --------------------------------------------------------------------------- #
# Strategy renderers.
# --------------------------------------------------------------------------- #
def reframe_uniform(in_path: str, out_path: str, strategy: str) -> None:
    """One filter over the whole file: center / blurpad / none."""
    if strategy == "none":
        _run(["ffmpeg", "-y", "-i", in_path, "-c", "copy",
              "-movflags", "+faststart", out_path])
        return
    if strategy == "blurpad":
        cmd = ["ffmpeg", "-y", "-i", in_path, "-filter_complex", blurpad_filter(),
               "-map", "[v]", "-map", "0:a?"]
    else:                                           # center
        w, h = probe_dims(in_path)
        cmd = ["ffmpeg", "-y", "-i", in_path, "-vf", crop_scale_vf(w, h),
               "-map", "0:v:0", "-map", "0:a?"]
    _run(cmd + _video_encode_args() + ["-movflags", "+faststart", out_path])


def _frame_boundaries(windows: list[dict], fps: Fraction, total: int) -> list[int]:
    """Shared frame-grid cut points ``[0, ..., total]`` for adjacent windows.

    Boundaries are frame INDEXES on the mezzanine grid, never seconds — the fix
    for edge F7. The first is pinned to frame 0 and the last to the mezzanine's
    exact frame count, so the parts telescope to EXACTLY the input length with
    zero per-range rounding drift. Each interior boundary is computed once from
    its window's ``outStart`` and reused as the previous part's end, so adjacent
    parts share it with no gap or overlap. ``max(.., prev)`` keeps it monotonic.
    """
    bounds = [0]
    for win in windows[1:]:
        frame = int(round(float(win["outStart"]) * float(fps)))
        bounds.append(min(max(frame, bounds[-1]), total))
    bounds.append(total)
    return bounds


def _extract_part(in_path: str, window: dict, span: tuple[int, int],
                  dst: str) -> None:
    """Crop ONE frame-exact range ``[start, end)`` of frames to canvas → dst.

    Selecting by absolute frame number (``trim=start_frame``) — never by seconds
    — is what makes each part exactly ``end - start`` frames on the shared grid;
    ``setpts=N/FRAME_RATE/TB`` rebuilds CFR timestamps from a zero origin so the
    parts concat cleanly. Video only: audio is copy-muxed from the mezzanine
    once at the end (see :func:`_concat_mux`), its exact timeline untouched.
    """
    start_f, end_f = span
    vf = (f"trim=start_frame={start_f}:end_frame={end_f},"
          f"setpts=N/FRAME_RATE/TB,{face_window_vf(window)}")
    _run(["ffmpeg", "-y", "-i", in_path, "-vf", vf, "-map", "0:v:0", "-an",
          "-fps_mode", "cfr"] + _video_only_args() + [dst])


def _reframe_single(in_path: str, window: dict, out_path: str) -> None:
    """Single-shot short: one crop pass over the whole file (1:1 frames → frame
    exact by construction) carrying the source audio through untouched."""
    _run(["ffmpeg", "-y", "-i", in_path, "-vf", face_window_vf(window),
          "-map", "0:v:0", "-map", "0:a?", "-c:a", "copy"]
         + _video_only_args() + ["-movflags", "+faststart", out_path])


def reframe_face(in_path: str, out_path: str, windows: list[dict]) -> None:
    """Per-shot crop → concat, frame-exact. Single-window shorts skip concat."""
    if not windows:
        raise RuntimeError("face strategy requires a non-empty windows.json")
    ordered = sorted(windows, key=lambda w: float(w["outStart"]))
    if len(ordered) == 1:
        _reframe_single(in_path, ordered[0], out_path)
        return
    fps, total = _fps_and_frames(in_path)
    bounds = _frame_boundaries(ordered, fps, total)
    workdir = tempfile.mkdtemp(prefix="producer-reframe-")
    try:
        parts: list[str] = []
        for i, win in enumerate(ordered):
            dst = os.path.join(workdir, f"seg_{i:04d}.mp4")
            _extract_part(in_path, win, (bounds[i], bounds[i + 1]), dst)
            parts.append(dst)
        _concat_mux(parts, in_path, workdir, out_path)
    finally:
        for name in os.listdir(workdir):
            os.remove(os.path.join(workdir, name))
        os.rmdir(workdir)


def _concat_mux(parts: list[str], audio_src: str, workdir: str,
                out_path: str) -> None:
    """Concat the video-only parts losslessly, then mux the mezzanine's audio
    via stream copy — the reframe is video-side only, so audio passes through
    untouched (no per-part re-extraction that would re-introduce drift)."""
    vonly = os.path.join(workdir, "video_only.mp4")
    list_path = os.path.join(workdir, "list.txt")
    with open(list_path, "w") as f:
        for p in parts:
            f.write(f"file '{p}'\n")
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
          "-c", "copy", vonly])
    _run(["ffmpeg", "-y", "-i", vonly, "-i", audio_src, "-map", "0:v:0",
          "-map", "1:a?", "-c:v", "copy", "-c:a", "copy",
          "-movflags", "+faststart", out_path])


def reframe(in_path: str, windows_path: str, out_path: str, strategy: str) -> None:
    """Dispatch to the chosen strategy. Only ``face`` reads the windows file."""
    if strategy == "face":
        with open(windows_path) as f:
            reframe_face(in_path, out_path, json.load(f))
    elif strategy in ("center", "blurpad", "none"):
        reframe_uniform(in_path, out_path, strategy)
    else:
        raise RuntimeError(f"unknown strategy {strategy!r}")


def main() -> None:
    ap = argparse.ArgumentParser(description="9:16 reframe (stage 2)")
    ap.add_argument("in_path")
    ap.add_argument("windows_path")
    ap.add_argument("out_path")
    ap.add_argument("--strategy", default="face",
                    choices=["face", "center", "blurpad", "none"])
    args = ap.parse_args()
    try:
        reframe(args.in_path, args.windows_path, args.out_path, args.strategy)
        w, h = probe_dims(args.out_path)
        print(json.dumps({"status": "done", "strategy": args.strategy,
                          "out": args.out_path, "width": w, "height": h}))
    except (OSError, json.JSONDecodeError, KeyError, RuntimeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
