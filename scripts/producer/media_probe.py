#!/usr/bin/env python3
"""media_probe — shared ffprobe/ffmpeg probing primitives (stage-1 family).

Split out of ``cut_speed.py`` (its 300-line budget); the public names remain
importable from ``cut_speed`` unchanged (it re-imports them), and
``study/deep_frames.py``'s ``cut_speed.display_dims`` contract still holds.
"""

from __future__ import annotations

import json
import subprocess
from fractions import Fraction

# Fallback CFR when a source reports an unusable r_frame_rate (e.g. "0/0").
CANVAS_FPS_FALLBACK = 30


def run_ff(cmd: list[str]) -> str:
    """Run an ffmpeg/ffprobe command; raise RuntimeError with the stderr tail."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        tail = (result.stderr or result.stdout).strip().splitlines()[-12:]
        raise RuntimeError("\n".join(tail) or f"{cmd[0]} failed")
    return result.stdout.strip()


def probe_video(path: str) -> dict:
    """First video stream's geometry/timing params (raises if there is none)."""
    out = run_ff(["ffprobe", "-v", "error", "-select_streams", "v:0",
                  "-show_entries",
                  "stream=width,height,r_frame_rate,pix_fmt:"
                  "stream_side_data=rotation",
                  "-of", "json", path])
    streams = json.loads(out).get("streams", [])
    if not streams:
        raise RuntimeError(f"{path}: no video stream")
    return streams[0]


def probe_duration(path: str) -> float:
    """Container duration in seconds (ffprobe ``format=duration``)."""
    out = run_ff(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                  "-of", "default=noprint_wrappers=1:nokey=1", path])
    return float(out.strip().splitlines()[0])


def probe_video_frames(path: str) -> int:
    """Exact video frame count via packet count (no decode) — the timeline
    length that matters, free of the AAC padding that inflates format duration."""
    out = run_ff(["ffprobe", "-v", "error", "-select_streams", "v:0",
                  "-count_packets", "-show_entries", "stream=nb_read_packets",
                  "-of", "default=noprint_wrappers=1:nokey=1", path])
    return int(out.strip().splitlines()[0])


def has_audio(path: str) -> bool:
    """True if the file has at least one audio stream."""
    out = run_ff(["ffprobe", "-v", "error", "-select_streams", "a:0",
                  "-show_entries", "stream=codec_type", "-of", "csv=p=0", path])
    return bool(out.strip())


def _fps_fraction(raw: str) -> Fraction:
    num, den = raw.split("/") if "/" in raw else (raw, "1")
    frac = Fraction(int(num), int(den))
    return frac if frac > 0 else Fraction(CANVAS_FPS_FALLBACK, 1)


def display_dims(stream: dict) -> tuple[int, int]:
    """Width/height AS DISPLAYED — phone footage stores landscape pixels plus
    a display-matrix rotation flag (edge I9: iPhone portrait = 3840x2160 +
    rotation=-90). ffmpeg's decoder auto-rotates frames, so a canvas built
    from raw dims letterboxes upright portrait into landscape. Swap on +/-90.
    """
    w, h = int(stream["width"]), int(stream["height"])
    for side in stream.get("side_data_list", []):
        try:
            if abs(int(float(side.get("rotation", 0)))) % 180 == 90:
                return h, w
        except (TypeError, ValueError):
            continue
    return w, h
