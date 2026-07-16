#!/usr/bin/env python3
"""reframe_split — stage 2 manual-geometry reframe: split layout + fill crop.

Executes the ``plan.reframe`` LAYOUT CONTRACT (2026-07-09) that
``plan_lint_reframe`` gates. Two entry points:

- ``apply_split`` — layout "split": TWO normalized crops of the SAME source
  (a StreamYard-style screen-share recording where the webcam inset and the
  shared screen are baked into one 16:9 frame), each scaled to COVER its cell
  (aspect-preserving, center-crop overflow — never letterbox), vstacked to
  the 1080x1920 canvas. ``frac`` = top cell's share of output height:
  H_top = even(round(1920*frac)), H_bottom = 1920 - H_top.
- ``apply_fill`` — layout "fill" with a manual ``crop`` override: ONE
  normalized crop scaled to cover the full canvas, replacing the automatic
  face crop (the auto path in reframe.py stays untouched).

Crops are [x,y,w,h] normalized to the SOURCE frame AS DISPLAYED. The renderer
denormalizes against the DISPLAY dims (cut_speed.display_dims, edge I9:
rotation side data swaps the canvas) — the operator drew the rect on the
display-oriented frame, and ffmpeg's filterchain sees display-oriented frames
too (autorotate is on by default) — snaps every value to even pixels, and
FAILS LOUDLY on any rect that leaves the frame after snapping (no clamping —
fix the plan).
Single filter_complex pass → output frames are 1:1 with the input (render.py's
``_assert_reframe_frames`` invariant holds by construction). Video re-encodes
with the ENCODE mezzanine settings like the sibling stages; audio -c:a copy
(this stage is video-side only).

CLI: reframe_split.py <in.mp4> <spec.json> <out.mp4>
     spec.json = {"layout":"split","split":{...}} | {"layout":"fill","crop":[...]}
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # run-by-path: producer pkg root on sys.path
from cut_speed import display_dims, probe_video
from motion.reframe import _run
from producer_config import CANVAS, ENCODE, REFRAME_SPLIT

_CW, _CH = CANVAS["width"], CANVAS["height"]
_PIX = CANVAS["pix_fmt"]


def emit(**fields) -> None:
    """Emit one JSON status line on stdout (NDJSON, like the sibling stages)."""
    print(json.dumps(fields), flush=True)


def even(n: float) -> int:
    """Nearest even int (yuv420p crop/scale geometry must be even)."""
    return int(round(n / 2.0)) * 2


def probe_display_dims(path: str) -> tuple[int, int]:
    """(width, height) of the first video stream AS DISPLAYED.

    Manual crops are drawn on what the operator SEES, and ffmpeg's filterchain
    also receives display-oriented frames (autorotate). Raw stored dims would
    denormalize a rotated-portrait source against the wrong canvas (edge I9 —
    see cut_speed.display_dims: rotation side data swaps width/height).
    """
    return display_dims(probe_video(path))


def denorm_crop(crop: list[float], src_w: int, src_h: int,
                tag: str) -> tuple[int, int, int, int]:
    """Normalized [x,y,w,h] → even-snapped pixel rect on the source frame.

    Fails loudly when the snapped rect leaves the frame (even-snapping can
    round a borderline rect outward) — never clamps: a crop that does not fit
    is a plan bug the operator must see, not silently shrink.
    """
    x, y, w, h = (float(v) for v in crop)
    px, py = even(x * src_w), even(y * src_h)
    pw, ph = even(w * src_w), even(h * src_h)
    if px < 0 or py < 0 or pw < 2 or ph < 2 or px + pw > src_w or py + ph > src_h:
        raise RuntimeError(
            f"{tag}: crop {crop} denormalized to [x={px}, y={py}, w={pw}, "
            f"h={ph}] leaves the {src_w}x{src_h} source frame")
    return px, py, pw, ph


def cell_heights(frac: float) -> tuple[int, int]:
    """Split cell heights: H_top = even(round(CANVAS_H*frac)), bottom = rest.

    CANVAS height (1920) is even, so both cells come out even. The frac range
    is re-checked here (executor's own sanity guard, like the sibling
    primitives) even though plan_lint_reframe already gates it.
    """
    lo, hi = REFRAME_SPLIT["frac_range"]
    if not lo <= frac <= hi:
        raise RuntimeError(f"split.top.frac {frac} outside [{lo},{hi}]")
    h_top = even(_CH * frac)
    return h_top, _CH - h_top


def _cover_chain(rect: tuple[int, int, int, int], out_w: int, out_h: int) -> str:
    """crop rect → scale to COVER out_w x out_h (center-crop overflow)."""
    x, y, w, h = rect
    return (f"crop={w}:{h}:{x}:{y},"
            f"scale={out_w}:{out_h}:force_original_aspect_ratio=increase:"
            f"flags=bicubic,crop={out_w}:{out_h},setsar=1")


def _encode_args() -> list[str]:
    """Mezzanine x264 video (like sibling intermediates) + audio stream copy."""
    return ["-c:v", ENCODE["vcodec"], "-crf", str(ENCODE["mezzanine_crf"]),
            "-preset", ENCODE["mezzanine_preset"], "-pix_fmt", _PIX,
            "-c:a", "copy", "-movflags", "+faststart"]


def apply_split(video_in: str, spec: dict, video_out: str) -> dict:
    """Render the split layout; ``spec`` = plan.reframe.split (top/bottom)."""
    src_w, src_h = probe_display_dims(video_in)
    frac = float(spec["top"].get("frac", REFRAME_SPLIT["frac_default"]))
    h_top, h_bottom = cell_heights(frac)
    top = denorm_crop(spec["top"]["crop"], src_w, src_h, "split.top")
    bottom = denorm_crop(spec["bottom"]["crop"], src_w, src_h, "split.bottom")
    resolved = {"layout": "split", "srcDims": [src_w, src_h], "frac": frac,
                "topRect": list(top), "bottomRect": list(bottom),
                "cellHeights": [h_top, h_bottom], "out": video_out}
    emit(status="split_resolved", **{k: v for k, v in resolved.items()
                                     if k != "out"})
    fc = (f"[0:v]{_cover_chain(top, _CW, h_top)}[top];"
          f"[0:v]{_cover_chain(bottom, _CW, h_bottom)}[bottom];"
          f"[top][bottom]vstack=inputs=2,setsar=1,format={_PIX}[v]")
    _run(["ffmpeg", "-y", "-i", video_in, "-filter_complex", fc,
          "-map", "[v]", "-map", "0:a?"] + _encode_args() + [video_out])
    return resolved


def apply_fill(video_in: str, crop: list[float], video_out: str) -> dict:
    """Fill-mode manual crop: one rect scaled to cover the full 9:16 canvas."""
    src_w, src_h = probe_display_dims(video_in)
    rect = denorm_crop(crop, src_w, src_h, "reframe.crop")
    resolved = {"layout": "fill", "srcDims": [src_w, src_h],
                "rect": list(rect), "canvas": [_CW, _CH], "out": video_out}
    emit(status="fill_crop_resolved", **{k: v for k, v in resolved.items()
                                         if k != "out"})
    vf = f"{_cover_chain(rect, _CW, _CH)},format={_PIX}"
    _run(["ffmpeg", "-y", "-i", video_in, "-vf", vf,
          "-map", "0:v:0", "-map", "0:a?"] + _encode_args() + [video_out])
    return resolved


def apply(video_in: str, spec: dict, video_out: str) -> dict:
    """Dispatch on spec.layout — the CLI entry render.py's stage calls."""
    layout = spec.get("layout")
    if layout == "split":
        return apply_split(video_in, spec["split"], video_out)
    if layout == "fill":
        return apply_fill(video_in, spec["crop"], video_out)
    raise RuntimeError(f"spec.layout must be 'split' or 'fill' (got {layout!r})")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="split-layout / manual-crop 9:16 reframe (stage 2)")
    ap.add_argument("in_path")
    ap.add_argument("spec_path")
    ap.add_argument("out_path")
    args = ap.parse_args()
    try:
        with open(args.spec_path) as f:
            spec = json.load(f)
        result = apply(args.in_path, spec, args.out_path)
        w, h = probe_display_dims(args.out_path)
        emit(status="done", width=w, height=h, **result)
    except (OSError, json.JSONDecodeError, KeyError,
            ValueError, RuntimeError) as exc:
        emit(error=str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
