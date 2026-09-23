#!/usr/bin/env python3
"""overlays — stage 3 (Phase 2): hook-card overlays over the reframed video.

Renders the brain's ``titleCards`` as the operator's brand hook card — a white
rounded container with black bold-sans text — and composites each onto the 9:16
cut for its output-time window (docs/producer/PRODUCER_PLAN.md §4.3). Two concerns:

* :func:`build_card_png` — Pillow renders ONE card to a tight RGBA PNG that hugs
  its text. The font auto-sizes down from ``font_size_range`` max until the
  widest line fits the safe box AND the whole card fits the upper-third hook
  band, so a card can never overrun either. Deterministic, $0.
* :func:`apply_cards` — a single ffmpeg pass overlays every card PNG on the
  video: centered on the right-rail-corrected visual center, vertically centered
  in the hook band, shown only for its ``between(t, outStart, outEnd)`` window,
  each with a short alpha fade-out at the tail. Mezzanine-quality re-encode
  (CRF 12); master burns captions on top downstream (bands never collide).

Card TEXT is validated upstream by ``plan_lint_overlays.check_title_cards`` (<=2 lines,
<=8 words, fits the safe box) — this stage only renders what the gate passed.

CLI: overlays.py <in.mp4> <cards.json> <out.mp4>
  cards.json = the plan's ``titleCards`` array; PNGs are built into a temp dir
  beside <out.mp4>. An empty array is an identity passthrough (stated plainly).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # run-by-path: producer pkg root on sys.path
from media_probe import _fps_fraction, display_dims, probe_video
from producer_config import CANVAS, ENCODE, HOOK_CARD
from captions.title_card_layout import CardLayout, layout_for_canvas

_STYLE = HOOK_CARD["style"]
_ALPHA = int(round(_STYLE["container_alpha"] * 255))
_FADE_S = 0.25                      # alpha fade-out at the tail of each window

# Operator brand font is Inter Bold; degrade only to a real bold sans, never to
# a thin/synthetic face. Each entry is (loader_arg, kwargs, label); the first
# that actually loads — an absolute path that exists OR a Pillow-resolvable
# family name — wins and is cached for the run.
_REPO_FONTS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "..", "..", "assets", "fonts")
_FONT_CANDIDATES = [
    # Repo-vendored brand font first (PROJECT_SNIPER/assets/fonts/, OFL Inter v4.1) —
    # works without any system font install.
    (os.path.abspath(os.path.join(_REPO_FONTS, "Inter-Bold.ttf")), {}, "Inter Bold"),
    ("/Library/Fonts/Inter-Bold.ttf", {}, "Inter Bold"),
    (os.path.expanduser("~/Library/Fonts/Inter-Bold.ttf"), {}, "Inter Bold"),
    ("Inter-Bold.ttf", {}, "Inter Bold"),
    ("Inter Bold", {}, "Inter Bold"),
    ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", {}, "Arial Bold"),
    ("/Library/Fonts/Arial Bold.ttf", {}, "Arial Bold"),
    ("Helvetica-Bold", {}, "Helvetica Bold"),
    ("/System/Library/Fonts/Helvetica.ttc", {"index": 1}, "Helvetica Bold"),
    ("Arial Bold.ttf", {}, "Arial Bold"),
    ("DejaVuSans-Bold.ttf", {}, "DejaVu Sans Bold"),
]

_resolved: tuple[str, dict, str] | None = None
_SCRATCH = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

_DEFAULT_LAYOUT = layout_for_canvas(CANVAS["width"], CANVAS["height"])


def emit(**fields) -> None:
    """One NDJSON status line on stdout (matches the sibling render stages)."""
    print(json.dumps(fields), flush=True)


def _run(cmd: list[str]) -> None:
    """Run an ffmpeg command; raise RuntimeError with the stderr tail on failure."""
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or proc.stdout).strip().splitlines()[-8:])
        raise RuntimeError(f"{cmd[0]} failed ({proc.returncode}):\n{tail}")


# --------------------------------------------------------------------------- #
# Font resolution + text measurement
# --------------------------------------------------------------------------- #
def _resolve_font() -> tuple[str, dict, str]:
    """Pick the best available bold font once; warn which was used."""
    global _resolved
    if _resolved is not None:
        return _resolved
    for arg, kwargs, label in _FONT_CANDIDATES:
        try:
            ImageFont.truetype(arg, 24, **kwargs)
        except (OSError, ValueError):
            continue
        _resolved = (arg, kwargs, label)
        status = "font" if label == "Inter Bold" else "font_fallback"
        emit(stage="overlays", status=status, font=label)
        return _resolved
    raise RuntimeError("no usable bold font found (tried Inter/Arial/Helvetica/DejaVu)")


def _font_at(size: int) -> ImageFont.FreeTypeFont:
    """Load the resolved bold font at ``size``."""
    arg, kwargs, _ = _resolve_font()
    return ImageFont.truetype(arg, size, **kwargs)


def _line_spacing(size: int) -> int:
    """Inter-line gap ~16% of the font size (roomier than Pillow's 4px default)."""
    return int(round(size * 0.16))


def _text_bbox(text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int, int, int]:
    """Tight (l, t, r, b) ink box of the centered multi-line text at ``font``."""
    return _SCRATCH.multiline_textbbox(
        (0, 0), text, font=font, align="center", spacing=_line_spacing(font.size))


def _fit(
        text: str, layout: CardLayout,
) -> tuple[ImageFont.FreeTypeFont, tuple[int, int, int, int]]:
    """Largest font whose text fits BOTH the safe-box width and the hook band.

    Shrinks from ``font_size_range`` max toward min; the width rule (§4.3) plus a
    band-height rule together guarantee the card never overruns the safe box or
    the upper-third band. If even the floor size overflows, the floor is used
    (the overlay-side clamp keeps it on canvas) — never smaller than min.
    """
    text_max = (
        layout.width - layout.safe["left"] - layout.safe["right"]
        - 2 * layout.padding)
    band_height = layout.y_range[1] - layout.y_range[0]
    for size in range(layout.font_range[1], layout.font_range[0] - 1, -1):
        font = _font_at(size)
        l, t, r, b = _text_bbox(text, font)
        if (r - l) <= text_max \
                and (b - t) + 2 * layout.padding <= band_height:
            return font, (l, t, r, b)
    font = _font_at(layout.font_range[0])
    return font, _text_bbox(text, font)


# --------------------------------------------------------------------------- #
# Card rendering
# --------------------------------------------------------------------------- #
def build_card_png(text: str, out_path: str, layout: CardLayout | None = None) -> tuple[int, int]:
    """Retired card renderer; titles must use source-bound native catalog designs."""
    raise ValueError("Legacy rounded hook cards are retired; select a HyperFrames catalog title")


# --------------------------------------------------------------------------- #
# Overlay compositing
# --------------------------------------------------------------------------- #
def _overlay_xy(
        card_w: int, card_h: int,
        layout: CardLayout | None = None) -> tuple[int, int]:
    """Overlay top-left: centered on VISUAL_CENTER_X and in the hook band,
    clamped so the card stays inside the safe box / band even if oversized."""
    layout = layout or _DEFAULT_LAYOUT
    x = int(round(layout.visual_center_x - card_w / 2.0))
    x = max(layout.safe["left"],
            min(x, layout.width - layout.safe["right"] - card_w))
    low, high = layout.y_range
    y = int(round((low + high) / 2.0 - card_h / 2.0))
    y = max(low, min(y, high - card_h))
    return x, y


def _build_filter(cards: list[dict]) -> tuple[str, str]:
    """Assemble the filter_complex for N pre-sized cards; return (graph, label).

    Each card input (index i+1) is faded on its own aligned timeline, then
    chain-overlaid onto the running video with an ``enable`` window. The tail
    fade + the enable window close together so the card exits cleanly.
    """
    parts: list[str] = []
    for i, c in enumerate(cards):
        st = max(0.0, float(c["outEnd"]) - _FADE_S)
        parts.append(f"[{i + 1}:v]format=rgba,"
                     f"fade=t=out:st={st:.4f}:d={_FADE_S}:alpha=1[c{i}]")
    prev = "[0:v]"
    for i, c in enumerate(cards):
        s, e = float(c["outStart"]), float(c["outEnd"])
        label = f"[o{i}]"
        parts.append(f"{prev}[c{i}]overlay=x={c['_x']}:y={c['_y']}:"
                     f"enable='between(t,{s:.4f},{e:.4f})'{label}")
        prev = label
    return ";".join(parts), prev


def apply_cards(
        video_in: str, cards: list[dict], video_out: str,
        layout: CardLayout | None = None) -> None:
    """Overlay every card PNG onto ``video_in`` in one ffmpeg pass.

    ``cards`` = ``[{"png", "outStart", "outEnd"}, ...]``. Video re-encodes to the
    mezzanine profile (CRF 12); audio is copied through untouched, and the frame
    count is preserved (overlay is bound to the main input).
    """
    if not cards:
        raise ValueError("apply_cards: no cards to apply")
    layout = layout or _DEFAULT_LAYOUT
    ordered = sorted(cards, key=lambda c: float(c["outStart"]))
    for c in ordered:
        with Image.open(c["png"]) as im:
            c["_x"], c["_y"] = _overlay_xy(*im.size, layout)
    rate = _fps_fraction(probe_video(video_in)["r_frame_rate"])
    rate_token = f"{rate.numerator}/{rate.denominator}"
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", video_in]
    for c in ordered:
        cmd += ["-loop", "1", "-framerate", rate_token,
                "-t", f"{float(c['outEnd']):.4f}", "-i", c["png"]]
    graph, final = _build_filter(ordered)
    cmd += ["-filter_complex", graph, "-map", final, "-map", "0:a?",
            "-c:v", ENCODE["vcodec"], "-crf", str(ENCODE["mezzanine_crf"]),
            "-preset", ENCODE["mezzanine_preset"], "-pix_fmt", CANVAS["pix_fmt"],
            "-c:a", "copy", "-movflags", "+faststart", video_out]
    _run(cmd)


def build_and_apply(video_in: str, title_cards: list[dict],
                    video_out: str, png_dir: str) -> dict:
    """Build a PNG per title card into ``png_dir``, then overlay them all."""
    stream = probe_video(video_in)
    layout = layout_for_canvas(*display_dims(stream))
    built: list[dict] = []
    for i, tc in enumerate(title_cards):
        png = os.path.join(png_dir, f"card_{i:02d}.png")
        w, h = build_card_png(str(tc.get("text", "")), png, layout)
        built.append({"png": png, "outStart": float(tc["outStart"]),
                      "outEnd": float(tc["outEnd"]), "dims": [w, h],
                      "canvas": [layout.width, layout.height]})
    apply_cards(video_in, built, video_out, layout)
    return {"cards": len(built), "out": video_out,
            "dims": [b["dims"] for b in built],
            "canvas": [layout.width, layout.height]}


def _passthrough(video_in: str, video_out: str) -> None:
    """No cards → stream-copy identity (no re-encode)."""
    _run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", video_in,
          "-c", "copy", "-movflags", "+faststart", video_out])


def main() -> None:
    ap = argparse.ArgumentParser(description="PRODUCER stage 3: hook-card overlays")
    ap.add_argument("in_path")
    ap.add_argument("cards_path", help="the plan's titleCards array (JSON)")
    ap.add_argument("out_path")
    args = ap.parse_args()
    try:
        with open(args.cards_path) as f:
            cards = json.load(f)
        if not cards:
            _passthrough(args.in_path, args.out_path)
            print(json.dumps({"status": "done", "cards": 0, "out": args.out_path,
                              "note": "no title cards — passthrough"}))
            return
        png_dir = tempfile.mkdtemp(
            prefix="producer-cards-",
            dir=os.path.dirname(os.path.abspath(args.out_path)))
        summary = build_and_apply(args.in_path, cards, args.out_path, png_dir)
        print(json.dumps({"status": "done", **summary}))
    except (OSError, json.JSONDecodeError, KeyError, ValueError, RuntimeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
