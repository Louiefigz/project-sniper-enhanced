#!/usr/bin/env python3
"""baseline_look — the BASELINE-LOOK stage: tight chest-up recrop + warm grade.

Doctrine (REFERENCE_STYLE_STUDY.md R16; audit record in
INTRO_MACHINE_VS_PRO_AUDIT.md §1/§6): even a "static" talking head is an
edit — a tight chest-up crop of the 4K frame with a subtle warm grade —
while an unedited cut ships the raw wide framing, flat. The audit ranked
this as a large share of the perceived-quality gap for near-zero effort.
This stage bakes that default: crop a window of (inW/zoom × inH/zoom) centred
on (centerX·inW, centerY·inH) — clamped so the window never leaves the frame —
scale it to outW×outH (lanczos), and optionally apply the fixed warm grade.
Designed for a 4K source cropped to a 1080p master so the window stays at or
above native pixel density; a 1080p input still works but upscales (warned via
NDJSON, never fatal).

The warm grade is DELIBERATELY subtle (broadcast-ish, never an Instagram
filter); its fixed constants live in ``WARM_GRADE`` below.

Frame count is preserved (probe assertion — the same contract as punch_in:
crop/scale/grade add and drop nothing); video re-encodes at the mezzanine spec
(CRF 12) and audio is stream-copied.

CLI:
    baseline_look.py <in.mp4> <out.mp4> --spec <spec.json | inline-json>
where the spec is:
    ``{"zoom": 1.28, "centerX": 0.5, "centerY": 0.44, "grade": "warm" | "none",
       "outW": 1920, "outH": 1080}``
(centerX/Y are 0..1 fractions of the SOURCE frame; every key is optional and
defaults to the values above — the R16 default chest-up framing.) The
editorial bands (zoom 1.0–1.5, centers 0.2–0.8) live in the plan lint's
``baselineLook`` check; the primitive enforces only wider hard-safety ranges.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cut_speed import probe_video_frames, run_ff  # noqa: E402
from producer_config import ENCODE  # noqa: E402
from motion.punch_in import probe_dims  # noqa: E402

# Hard-safety ranges for the PRIMITIVE (wider than the editorial bands the plan
# lint enforces on ``baselineLook``: zoom 1.0-1.5, centers 0.2-0.8). Zoom 2.0
# crops a 4K frame to exactly 1920x1080 — anything past it upscales even from
# 4K, so it is the sane hard ceiling.
ZOOM_MIN_HARD = 1.0
ZOOM_MAX_HARD = 2.0
GRADES = ("warm", "none")
# Output-timeline frame tolerance for the preserve-count assertion (same as
# punch_in: ±1 only absorbs container/muxer rounding).
FRAME_TOL = 1

# The warm grade — fixed, deterministic, deliberately SUBTLE. Constants (R16:
# the baseline look is subtly warm, and between events it never moves):
#   colorbalance  midtone red +0.03 / blue -0.03, highlight red +0.02 /
#                 blue -0.02 -> the warmth push. Shadows are untouched so
#                 blacks stay neutral (no orange mud in the dark end).
#   eq            contrast 1.05, saturation 1.08 -> a gentle pop, inside the
#                 subtle 1.04-1.06 / 1.06-1.10 broadcast band.
#   curves        master shoulder 0.85->0.83, 1.0->0.97 -> very gentle
#                 highlight rolloff (a film-ish shoulder that softens
#                 clipped-white harshness without visibly dimming the frame).
WARM_GRADE = (
    "colorbalance=rm=0.03:bm=-0.03:rh=0.02:bh=-0.02,"
    "eq=contrast=1.05:saturation=1.08,"
    "curves=master='0/0 0.5/0.5 0.85/0.83 1/0.97'"
)


def emit(**fields) -> None:
    """One JSON status object per line on stdout (NDJSON, like the sibling stages)."""
    print(json.dumps(fields), flush=True)


@dataclass(frozen=True)
class BaselineSpec:
    """The whole-video baseline treatment: crop-in target + grade + canvas.

    ``zoom`` is the crop-in factor (window = source dims / zoom); ``center_x``
    / ``center_y`` are 0..1 fractions of the SOURCE frame the window centres
    on (clamped inside the frame); ``grade`` selects the fixed warm grade or
    none; ``out_w`` × ``out_h`` is the delivery canvas the window scales to.
    Defaults are the R16 chest-up framing (Sniper design parameters).
    """

    zoom: float = 1.28
    center_x: float = 0.5
    center_y: float = 0.44
    grade: str = "warm"
    out_w: int = 1920
    out_h: int = 1080


def parse_spec(raw: object) -> BaselineSpec:
    """Validate a raw spec object into a ``BaselineSpec`` (raises on bad input).

    Args:
        raw: The decoded JSON spec (must be an object; all keys optional).

    Returns:
        The validated, typed spec.
    """
    if not isinstance(raw, dict):
        raise ValueError("spec must be a JSON object")
    zoom = float(raw.get("zoom", BaselineSpec.zoom))
    if not (ZOOM_MIN_HARD <= zoom <= ZOOM_MAX_HARD):
        raise ValueError(f"zoom {zoom} outside hard [{ZOOM_MIN_HARD},{ZOOM_MAX_HARD}]")
    cx = float(raw.get("centerX", BaselineSpec.center_x))
    cy = float(raw.get("centerY", BaselineSpec.center_y))
    if not (0.0 <= cx <= 1.0 and 0.0 <= cy <= 1.0):
        raise ValueError("centerX/centerY must be in [0,1]")
    grade = raw.get("grade", BaselineSpec.grade)
    if grade not in GRADES:
        raise ValueError(f"grade {grade!r} not in {GRADES}")
    out_w = int(raw.get("outW", BaselineSpec.out_w))
    out_h = int(raw.get("outH", BaselineSpec.out_h))
    if out_w <= 0 or out_h <= 0 or out_w % 2 or out_h % 2:
        raise ValueError("outW/outH must be positive even integers")
    return BaselineSpec(zoom, cx, cy, grade, out_w, out_h)


def _even(v: float) -> int:
    """Floor to the nearest even integer (yuv420p needs even dims/offsets)."""
    return int(v) & ~1


def crop_window(in_w: int, in_h: int, spec: BaselineSpec) -> tuple[int, int, int, int]:
    """The source-frame crop rect ``(w, h, x, y)`` for a spec — pure math.

    The window is (in_w/zoom × in_h/zoom) centred on (center_x·in_w,
    center_y·in_h); the offset clamps so the window stays fully inside the
    frame. Dims/offsets snap even for yuv420p chroma alignment.
    """
    cw = min(in_w, _even(round(in_w / spec.zoom)))
    ch = min(in_h, _even(round(in_h / spec.zoom)))
    x = _even(min(max(spec.center_x * in_w - cw / 2.0, 0), in_w - cw))
    y = _even(min(max(spec.center_y * in_h - ch / 2.0, 0), in_h - ch))
    return cw, ch, x, y


def build_filter(in_dims: tuple[int, int], spec: BaselineSpec) -> str:
    """One ``-vf`` chain: crop → lanczos scale → optional grade → pix_fmt."""
    cw, ch, x, y = crop_window(in_dims[0], in_dims[1], spec)
    parts = [f"crop={cw}:{ch}:{x}:{y}",
             f"scale={spec.out_w}:{spec.out_h}:flags=lanczos", "setsar=1"]
    if spec.grade == "warm":
        parts.append(WARM_GRADE)
    parts.append(f"format={ENCODE['pix_fmt']}")
    return ",".join(parts)


def _warn_geometry(crop: tuple[int, int, int, int], spec: BaselineSpec) -> None:
    """NDJSON warnings for legal-but-suspect geometry (never fatal)."""
    cw, ch = crop[0], crop[1]
    if cw < spec.out_w or ch < spec.out_h:
        emit(stage="baseline_look", status="warn", reason="upscale",
             cropWindow=[cw, ch], out=[spec.out_w, spec.out_h],
             detail="crop window below the output canvas — source under 4K? "
                    "The look still renders but below native pixel density.")
    if abs((cw / ch) / (spec.out_w / spec.out_h) - 1.0) > 0.01:
        emit(stage="baseline_look", status="warn", reason="aspect-distortion",
             cropAspect=round(cw / ch, 4),
             outAspect=round(spec.out_w / spec.out_h, 4))


def apply_baseline_look(src_path: str, spec: BaselineSpec, out_path: str) -> dict:
    """Render ``src_path`` with the baseline look into ``out_path``.

    Video re-encodes at mezzanine CRF; audio (if any) is stream-copied.
    Asserts the output frame count matches the input within ``FRAME_TOL``.
    """
    in_w, in_h = probe_dims(src_path)
    in_frames = probe_video_frames(src_path)
    crop = crop_window(in_w, in_h, spec)
    _warn_geometry(crop, spec)
    cmd = baseline_command(src_path, spec, out_path, (in_w, in_h))
    run_ff(cmd)
    out_frames = probe_video_frames(out_path)
    drift = abs(out_frames - in_frames)
    result = {"inRes": [in_w, in_h], "outRes": [spec.out_w, spec.out_h],
              "cropWindow": list(crop), "zoom": spec.zoom, "grade": spec.grade,
              "inFrames": in_frames, "outFrames": out_frames,
              "driftFrames": drift}
    if drift > FRAME_TOL:
        raise RuntimeError(
            f"baseline-look changed frame count: in {in_frames} -> out "
            f"{out_frames} (drift {drift} > {FRAME_TOL})")
    return result


def baseline_command(
        src_path: str, spec: BaselineSpec, out_path: str,
        dimensions: tuple[int, int] | None = None) -> list[str]:
    """Return the exact deterministic ffmpeg command used by the stage."""
    in_dims = dimensions or probe_dims(src_path)
    return [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", src_path, "-map", "0:v:0", "-map", "0:a?",
        "-vf", build_filter(in_dims, spec),
        "-c:v", "libx264", "-crf", str(ENCODE["mezzanine_crf"]),
        "-preset", ENCODE["mezzanine_preset"], "-pix_fmt", ENCODE["pix_fmt"],
        "-fps_mode", "passthrough", "-c:a", "copy",
        "-movflags", "+faststart", out_path,
    ]


def _load_spec(spec: str) -> object:
    """The spec is either a path to a JSON file or an inline JSON string."""
    if os.path.exists(spec):
        with open(spec) as f:
            return json.load(f)
    return json.loads(spec)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="PRODUCER baseline look: tight chest-up recrop of the raw "
                    "frame + subtle warm grade (the R16 default framing)")
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--spec", required=True,
                    help="JSON file path OR inline JSON object "
                         '(zoom/centerX/centerY/grade/outW/outH)')
    args = ap.parse_args()
    try:
        spec = parse_spec(_load_spec(args.spec))
        emit(stage="baseline_look", status="start", zoom=spec.zoom,
             grade=spec.grade)
        result = apply_baseline_look(args.src, spec, args.out)
        emit(stage="baseline_look", status="done", **result)
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError) as exc:
        emit(error=str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
