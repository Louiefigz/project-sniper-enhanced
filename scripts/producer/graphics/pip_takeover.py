#!/usr/bin/env python3
"""pip_takeover — the long-form TAKEOVER footage move (liquid-glass hero move).

The takeover is the signature long-form beat (liquid-glass-style.md "the two
footage moves"): the speaker's frame RESIZES + slides into a rounded 4:5 card on
one side while the spotlight-grid ``glass-takeover-bg`` fills the frame and a
``glass-rail`` builds in behind it; on restore the face un-crops back to full
frame, sweeping OVER the graphics. It is FOOTAGE motion, so it lives here as a
pure-ffmpeg renderer beside ``reframe.py`` / ``punch_in.py`` — never in render.py.

Composite order for the takeover window: bg (opaque, bottom) → optional rail
(alpha) → the base video as a rounded 4:5 card (top). The card's size + position
are animated per frame:

* SCALE ramp — ``scale=eval=frame`` grows/shrinks the rounded card (seed = the
  native 4:5 crop at full height; settled = the target card rect). No upscaling
  past native, so the card stays crisp.
* POSITION ramp — the ``overlay`` x/y expressions blend a centred "seed" pose
  into the settled card rect with the SAME eased progress ``P(t)``.

Rounded corners: an alpha MASK PNG is rendered once (a single ``geq`` rounded-rect
frame) and ``alphamerge``d onto the crop BEFORE the scale, so the corners scale
with the card and no per-frame ``geq`` runs. (Chosen over an inline per-frame
geq: one static mask is far cheaper and byte-stable.)

``build_demo`` stitches full-frame → takeover → full-frame with two ``xfade``
dissolves whose overlap covers the SAME base timestamps as the takeover edges, so
the talking is perfectly continuous across the seams (the dissolve is what reads
as the face resizing in / sweeping back). Continuous base audio is muxed last.

CLI:
    pip_takeover.py segment <base.mp4> <bg.mp4> <out.mp4> [--rail rail.mov]
        --window S E [--card X Y W H] [--face-cx F] [--ramp R]
    pip_takeover.py demo <base.mp4> <bg.mp4> <out.mp4> [--rail rail.mov]
        --window S E [--card ...] [--lead 1.6] [--tail 1.3] [--xfade 0.3]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from producer_config import ENCODE  # noqa: E402

# Long-form canvas + the reserved face-PiP region, KEYED BY BACKDROP comp.
# Each entry's RESERVED must match the empty rect the comp leaves for the card
# (glass-takeover-bg: right side x[1180,1820] y[140,940]; canvas-pip-list:
# left-of-center x[140,660] y[190,890] — the canvas-pip-list reserved rect); the
# default 4:5 settled card is inset inside it. Change a comp, change its entry.
LF_W, LF_H = 1920, 1080
RESERVED_BY_BG = {
    "glass-takeover-bg": ((1180, 140, 640, 800), (1200, 164, 600, 750)),
    "canvas-pip-list": ((140, 190, 520, 700), (150, 228, 500, 625)),
}
RESERVED, DEFAULT_CARD = RESERVED_BY_BG["glass-takeover-bg"]  # legacy default
CORNER_RADIUS = 36                       # at NATIVE crop res; scales with the card
DEFAULT_RAMP_S = 0.4
DEFAULT_XFADE_S = 0.3


def emit(**fields) -> None:
    """One NDJSON status line on stdout (matches the sibling render stages)."""
    print(json.dumps(fields), flush=True)


def run_ff(cmd: list[str]) -> str:
    """Run an ffmpeg/ffprobe command; raise RuntimeError with the stderr tail."""
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or proc.stdout).strip().splitlines()[-12:])
        raise RuntimeError("\n".join([f"{cmd[0]} failed:", tail]))
    return proc.stdout.strip()


def _even(v: float) -> int:
    """Nearest even integer (yuv420p needs even dims)."""
    return int(round(v / 2.0)) * 2


def probe_dims(path: str) -> tuple[int, int]:
    """(width, height) of the first video stream (raises if none)."""
    out = run_ff(["ffprobe", "-v", "error", "-select_streams", "v:0",
                  "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", path])
    w, h = out.split("x")[:2]
    return int(w), int(h)


def _encode_args() -> list[str]:
    """Near-lossless x264 video args shared by every intermediate (CRF 18)."""
    return ["-c:v", ENCODE["vcodec"], "-crf", "18",
            "-preset", ENCODE["mezzanine_preset"], "-pix_fmt", ENCODE["pix_fmt"],
            "-fps_mode", "cfr"]


# --------------------------------------------------------------------------- #
# Geometry — pure + unit-testable (see selftest.py PipTakeoverTests)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CardGeom:
    """Everything the filtergraph needs: the native 4:5 crop + the settled rect."""

    cw: int          # native crop width  (largest 4:5 of the source)
    ch: int          # native crop height
    cx: int          # native crop x offset (centred on the face)
    cy: int          # native crop y offset
    card: tuple[int, int, int, int]   # settled card rect (x, y, w, h)


def crop_4x5(src_w: int, src_h: int, face_cx: float) -> tuple[int, int, int, int]:
    """Largest 4:5 (w:h) centre-crop of the source, centred on ``face_cx`` (0..1).

    Wider-than-4:5 sources crop on width (keep full height); taller ones crop on
    height. The x offset tracks the face fraction, clamped inside the frame; y is
    centred. Even dims/offsets for yuv420p.
    """
    if src_w / src_h > 4.0 / 5.0:                 # wider than 4:5 -> crop width
        ch = _even(src_h)
        cw = min(_even(ch * 4.0 / 5.0), _even(src_w))
    else:                                          # taller -> crop height
        cw = _even(src_w)
        ch = min(_even(cw * 5.0 / 4.0), _even(src_h))
    cx = _even(min(max(face_cx * src_w - cw / 2.0, 0), src_w - cw))
    cy = _even(min(max(src_h / 2.0 - ch / 2.0, 0), src_h - ch))
    return cw, ch, cx, cy


def make_geom(src_w: int, src_h: int, card: tuple[int, int, int, int],
              face_cx: float) -> CardGeom:
    """Build the CardGeom for a source + settled card rect (validates the rect)."""
    validate_card(card)
    cw, ch, cx, cy = crop_4x5(src_w, src_h, face_cx)
    return CardGeom(cw, ch, cx, cy, card)


def validate_card(card: tuple[int, int, int, int],
                  reserved: tuple[int, int, int, int] = RESERVED) -> None:
    """Raise if the settled card falls outside the reserved PiP region."""
    x, y, w, h = card
    rx, ry, rw, rh = reserved
    if x < rx or y < ry or x + w > rx + rw or y + h > ry + rh:
        raise ValueError(f"card {card} escapes reserved region {reserved}")
    if w <= 0 or h <= 0:
        raise ValueError(f"card {card} has non-positive size")


def progress(t: float, ramp: float, length: float) -> float:
    """Eased trapezoid P(t) in [0,1]: 0 at both ends, 1 across the hold.

    The Python mirror of :func:`progress_expr` (the ffmpeg string) — keep them in
    lock-step; the selftests pin the endpoints/knees on this one.
    """
    pe = min(max(t / ramp, 0.0), 1.0)
    px = min(max((length - t) / ramp, 0.0), 1.0)
    p = min(pe, px)
    return p * p * (3 - 2 * p)                     # smoothstep


def progress_expr(ramp: float, length: float) -> str:
    """ffmpeg expression for P(t) — mirrors :func:`progress` exactly."""
    praw = f"min(clip(t/{ramp:g}\\,0\\,1)\\,clip(({length:g}-t)/{ramp:g}\\,0\\,1))"
    return f"({praw})*({praw})*(3-2*({praw}))"


def scale_exprs(geom: CardGeom, p: str) -> tuple[str, str]:
    """(w, h) scale=eval=frame expressions: native crop at P=0 -> card at P=1."""
    _, _, w, h = geom.card
    we = f"{geom.cw}+({w}-{geom.cw})*({p})"
    he = f"{geom.ch}+({h}-{geom.ch})*({p})"
    return we, he


def overlay_exprs(geom: CardGeom, p: str) -> tuple[str, str]:
    """(x, y) overlay expressions: centred "seed" pose at P=0 -> card rect at P=1."""
    x, y, _, _ = geom.card
    xe = f"(W-w)/2*(1-({p}))+{x}*({p})"
    ye = f"(H-h)/2*(1-({p}))+{y}*({p})"
    return xe, ye


# --------------------------------------------------------------------------- #
# ffmpeg builders
# --------------------------------------------------------------------------- #
def render_mask(geom: CardGeom, out_png: str) -> None:
    """Render the rounded-rect alpha mask once (a single geq frame at crop res)."""
    r = CORNER_RADIUS
    lum = (f"255*lte(hypot(max(0,max({r}-X,X-(W-{r}))),"
           f"max(0,max({r}-Y,Y-(H-{r})))),{r})")
    run_ff(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=white:s={geom.cw}x{geom.ch}:d=0.1",
            "-vf", f"format=gray,geq=lum='{lum}'", "-frames:v", "1", out_png])


def build_graph(geom: CardGeom, length: float, has_rail: bool) -> str:
    """filter_complex: rounded 4:5 card (scale+pos ramp) over bg (+ rail).

    Inputs: [0]=bg  [1]=base slice  [2]=mask.png  [3]=rail(optional).
    """
    p = progress_expr(DEFAULT_RAMP_S, length)
    we, he = scale_exprs(geom, p)
    xe, ye = overlay_exprs(geom, p)
    parts = [
        f"[1:v]crop={geom.cw}:{geom.ch}:{geom.cx}:{geom.cy},setsar=1,format=rgba[face]",
        "[2:v]format=gray[m]",
        "[face][m]alphamerge[card0]",
        f"[card0]scale=w='{we}':h='{he}':eval=frame[card]",
    ]
    if has_rail:
        parts.append("[0:v][3:v]overlay=0:0:format=auto[stage]")
        base = "[stage]"
    else:
        base = "[0:v]"
    parts.append(f"{base}[card]overlay=x='{xe}':y='{ye}':eval=frame:format=auto[v]")
    return ";".join(parts)


@dataclass
class TakeoverInputs:
    """The four media paths a takeover render consumes (keeps calls ≤4 params)."""

    slice_path: str      # base video slice for the window (used whole)
    bg_path: str         # opaque spotlight-grid backdrop render
    mask_path: str       # rounded-rect alpha mask PNG
    rail_path: str | None = None


def render_takeover(inp: TakeoverInputs, geom: CardGeom, length: float,
                    out_path: str) -> None:
    """Retired house-layout compositor; use a source-bound native composition."""
    raise ValueError("Legacy glass takeover layouts are retired; select a HyperFrames catalog layout or an explicit current-job reference/custom design")


# --------------------------------------------------------------------------- #
# Segment + demo orchestration
# --------------------------------------------------------------------------- #
@dataclass
class Spec:
    """One takeover request (keeps the entry points ≤4 params)."""

    base: str
    bg: str
    out: str
    rail: str | None = None
    window: tuple[float, float] = (0.0, 4.0)
    card: tuple[int, int, int, int] = DEFAULT_CARD
    face_cx: float = 0.5


def _cut(src: str, ss: float, dur: float, out: str) -> None:
    """Accurate (output-seek) re-encode of ``src[ss, ss+dur]`` → CFR ``out``."""
    run_ff(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", src, "-ss", f"{ss:g}", "-t", f"{dur:g}", "-map", "0:v:0",
            "-an"] + _encode_args() + [out])


def _window_slice(base: str, ss: float, dur: float, out: str) -> None:
    """Fast (input-seek) extract of a continuous base window (video+audio) → out."""
    run_ff(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{ss:g}", "-i", base, "-t", f"{dur:g}",
            "-map", "0:v:0", "-map", "0:a?"] + _encode_args()
           + ["-c:a", "aac", out])


def _prepare(spec: Spec, work: str) -> tuple[CardGeom, float, str]:
    """Shared setup: geom, window length, rendered mask. Returns (geom, L, mask)."""
    src_w, src_h = probe_dims(spec.base)
    geom = make_geom(src_w, src_h, spec.card, spec.face_cx)
    length = float(spec.window[1]) - float(spec.window[0])
    if length <= 0:
        raise ValueError(f"window {spec.window} is non-positive")
    mask = os.path.join(work, "mask.png")
    render_mask(geom, mask)
    return geom, length, mask


def run_segment(spec: Spec) -> dict:
    """Retired house-layout compositor; use a source-bound native composition."""
    raise ValueError("Legacy glass takeover layouts are retired; select a HyperFrames catalog layout or an explicit current-job reference/custom design")


def run_demo(spec: Spec, lead_s: float, tail_s: float, xfade_s: float) -> dict:
    """Retired house-layout compositor; use a source-bound native composition."""
    raise ValueError("Legacy glass takeover layouts are retired; select a HyperFrames catalog layout or an explicit current-job reference/custom design")


def _stitch_demo(pieces: tuple[str, str, str], timing: tuple[float, float, float],
                 audio_src: str, out: str) -> None:
    """Chain two xfades over (lead, take, tail) and mux the continuous audio."""
    lead_full, take, tail_full = pieces
    lead_s, length, xfade_s = timing
    off1 = lead_s
    off2 = lead_s + length - xfade_s
    graph = (f"[0:v][1:v]xfade=transition=fade:duration={xfade_s:g}:offset={off1:g}[m];"
             f"[m][2:v]xfade=transition=fade:duration={xfade_s:g}:offset={off2:g}[v]")
    run_ff(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", lead_full, "-i", take, "-i", tail_full, "-i", audio_src,
            "-filter_complex", graph, "-map", "[v]", "-map", "3:a?",
            "-shortest"] + _encode_args()
           + ["-c:a", "aac", "-movflags", "+faststart", out])


def _rmtree(path: str) -> None:
    """Remove a temp work dir (files are flat, one level)."""
    for name in os.listdir(path):
        os.remove(os.path.join(path, name))
    os.rmdir(path)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _spec_from_args(args: argparse.Namespace) -> Spec:
    card = tuple(args.card) if args.card else DEFAULT_CARD
    return Spec(base=args.base, bg=args.bg, out=args.out, rail=args.rail,
                window=(args.window[0], args.window[1]), card=card,
                face_cx=args.face_cx)


def main() -> int:
    ap = argparse.ArgumentParser(description="PRODUCER long-form takeover renderer")
    ap.add_argument("mode", choices=["segment", "demo"])
    ap.add_argument("base"); ap.add_argument("bg"); ap.add_argument("out")
    ap.add_argument("--rail", default=None)
    ap.add_argument("--window", type=float, nargs=2, metavar=("S", "E"), required=True)
    ap.add_argument("--card", type=int, nargs=4, default=None,
                    metavar=("X", "Y", "W", "H"))
    ap.add_argument("--face-cx", type=float, default=0.5, dest="face_cx")
    ap.add_argument("--lead", type=float, default=1.6)
    ap.add_argument("--tail", type=float, default=1.3)
    ap.add_argument("--xfade", type=float, default=DEFAULT_XFADE_S)
    args = ap.parse_args()
    try:
        spec = _spec_from_args(args)
        emit(stage="pip_takeover", status="start", mode=args.mode)
        if args.mode == "segment":
            result = run_segment(spec)
        else:
            result = run_demo(spec, args.lead, args.tail, args.xfade)
        emit(stage="pip_takeover", status="done", **result)
        return 0
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        emit(error=str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
