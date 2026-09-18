"""Existing final-picture arguments, caption filters and master request type.

Kept separate from shared audio DSP; public audio.master imports remain compatible.
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from typing import Callable, Optional, TYPE_CHECKING

from producer_config import ENCODE

if TYPE_CHECKING:
    from guided_source_color_consumption import SourceColorPictureConsumption


@dataclass
class MasterSpec:
    """One master render (kept to <=4 constructor args via a dataclass)."""

    src: str
    out: str
    ass: Optional[str] = None
    fps: int = 30
    # Exact rational frame rate (e.g. "24000/1001"). When set it is passed to
    # -r verbatim so an NTSC-fractional source is NOT retimed to the integer
    # rate — rounding 23.976 -> 24 duplicated ~1 frame/42s and slid every
    # downstream frame-indexed event off its seam (v2 intro, 2026-07-06).
    # ``fps`` (int) stays for GOP size / bitrate-table lookups only.
    fps_exact: Optional[str] = None
    cover: Optional[str] = None
    # Picture-derived duration clamp (+half frame in _encode). Callers should
    # derive this from frame_count / exact rational FPS, never from an MP4
    # stream/container duration that may include AAC tail padding (X9/X19).
    duration: Optional[float] = None
    # Pre-master picture packet count. When present, the final encode is
    # explicitly capped to this many video frames so CFR can never manufacture
    # frames from an AAC-padded or timestamp-inflated tail.
    frame_count: Optional[int] = None
    picture_consumption: SourceColorPictureConsumption | None = None  # Never a CLI/JSON field.


def _video_opts(fps: int, fps_exact: Optional[str] = None) -> list[str]:
    """H.264 High, CFR, closed GOP (2*fps), CABAC, target bitrate, faststart."""
    gop = 2 * fps
    rate = ENCODE["bitrate_by_fps"].get(fps, ENCODE["bitrate_by_fps"][30])
    bufsize = f"{int(str(rate).rstrip('M')) * 2}M"
    return [
        "-c:v", ENCODE["vcodec"], "-profile:v", ENCODE["profile"],
        "-pix_fmt", ENCODE["pix_fmt"],
        "-b:v", rate, "-maxrate", rate, "-bufsize", bufsize,
        "-g", str(gop), "-keyint_min", str(gop), "-sc_threshold", "0",
        "-flags", "+cgop", "-bf", str(ENCODE["bframes"]),
        "-coder", "1" if ENCODE["coder"] == "cabac" else "0",
        "-r", fps_exact or str(fps), "-fps_mode", "cfr",
        "-movflags", ENCODE["movflags"],
    ]


def _filter_quote(path: str) -> str:
    """Escape a path for a single-quoted ffmpeg filtergraph token.

    Inside single quotes ffmpeg honors NO backslash escapes, so a literal
    quote uses the close-reopen idiom ('…'\\''…') — the previous
    backslash-escaping produced a premature quote-close (review finding).
    """
    return path.replace("'", "'\\''")


def _subtitles_filter(ass_path: str) -> str:
    """`subtitles` (libass) filter with fontsdir fallback, path-escaped for the
    filtergraph. libass resolves the Inter font via fontconfig; if Inter is
    absent it substitutes a system sans (the caller warns)."""
    esc = _filter_quote(ass_path)
    fonts = os.environ.get("PRODUCER_FONTS_DIR")
    if fonts and os.path.isdir(fonts):
        return f"subtitles=filename='{esc}':fontsdir='{_filter_quote(fonts)}'"
    return f"subtitles=filename='{esc}'"


def _vendored_inter_available(fonts_dir: str | None) -> bool:
    """Check the same vendored Inter font names, retaining inaccessible-directory fallback."""
    if not fonts_dir or not os.path.isdir(fonts_dir):
        return False
    try:
        return any(name.lower().startswith("inter") and name.lower().endswith(".ttf")
                   for name in os.listdir(fonts_dir))
    except OSError:
        return False


def inter_available(run: Callable[[list[str]], subprocess.CompletedProcess]) -> bool:
    """True if Inter is reachable — repo fontsdir first, then system fonts.

    A vendored ``PRODUCER_FONTS_DIR`` containing Inter*.ttf satisfies libass
    via the subtitles filter's fontsdir, so it must count (the fc-list check
    alone false-positives the warning). Word-boundary match on fc-list so
    'Painter'/'Winter' don't read as hits."""
    if _vendored_inter_available(os.environ.get("PRODUCER_FONTS_DIR")):
        return True
    try:
        listing = run(["fc-list"])
    except (OSError, ValueError):
        return True   # cannot check → do not cry wolf
    if listing.returncode != 0:
        return True
    return re.search(r"(?i)\binter\b", listing.stdout) is not None
