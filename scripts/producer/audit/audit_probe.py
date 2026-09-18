#!/usr/bin/env python3
"""audit_probe — measurement primitives for Audit B (ffprobe / ffmpeg / PIL).

Raw measurement only — NO pass/fail judgment (that lives in audit_checks). These
wrappers mirror the sibling stages' ffprobe/ffmpeg patterns
(``cut_speed.probe_video_frames``, ``master.measure_integrated_lufs``) so the QC
pass measures exactly what the renderer asserted. Image helpers are PIL-only
(no OpenCV) per the Audit B spec. See docs/producer/PRODUCER_PLAN.md §5 Audit B.
"""

from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageChops  # noqa: E402
from palmier.process_deadline import process_timeout  # noqa: E402
from audio.audio_mix_delivery import measure_delivery  # noqa: E402

def run_ff(cmd: list[str]) -> subprocess.CompletedProcess:
    """Run an ffmpeg/ffprobe command, capturing stdout+stderr as text."""
    return subprocess.run(
        cmd, capture_output=True, text=True,
        timeout=process_timeout())


def ffprobe_json(path: str) -> dict:
    """Full ``-show_streams -show_format`` JSON for a media file.

    Returns an empty dict on any probe/parse failure (the caller turns a
    missing stream into an explicit failed check rather than crashing).
    """
    proc = run_ff(["ffprobe", "-v", "error", "-show_streams", "-show_format",
                   "-of", "json", path])
    if proc.returncode != 0:
        return {}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {}


def first_stream(probe: dict, codec_type: str) -> Optional[dict]:
    """First stream of ``codec_type`` ("video"/"audio"), or None if absent."""
    for stream in probe.get("streams", []):
        if stream.get("codec_type") == codec_type:
            return stream
    return None


def video_frame_count(path: str) -> Optional[int]:
    """Exact video frame count via packet count (no decode) — the timeline
    length that matters, free of the AAC padding that inflates format duration
    (matches ``cut_speed.probe_video_frames``). None if it can't be read."""
    proc = run_ff(["ffprobe", "-v", "error", "-select_streams", "v:0",
                   "-count_packets", "-show_entries", "stream=nb_read_packets",
                   "-of", "default=noprint_wrappers=1:nokey=1", path])
    text = proc.stdout.strip().splitlines()
    try:
        return int(text[0])
    except (IndexError, ValueError):
        return None


def same_frame_rate(rate_a: object, rate_b: object) -> bool:
    """True if two ffprobe rate strings ("30/1", "60/2") are the same rational.

    Compares by value, not text, so an equal-but-differently-written pair does
    not read as variable frame rate. Falls back to raw equality when unparsable.
    """
    from fractions import Fraction
    try:
        return Fraction(str(rate_a)) == Fraction(str(rate_b))
    except (ValueError, ZeroDivisionError):
        return rate_a == rate_b


def fps_from_stream(stream: dict) -> Optional[float]:
    """Decode ``r_frame_rate`` ("30/1") to a float, or None if degenerate."""
    raw = stream.get("r_frame_rate") or ""
    try:
        num, den = (raw.split("/") + ["1"])[:2]
        value = float(num) / float(den)
        return value if value > 0 else None
    except (ValueError, ZeroDivisionError):
        return None


def measure_loudness(path: str) -> tuple[Optional[float], Optional[float]]:
    """Shared whole-decode observation; partial statistics are unmeasured."""
    observed = measure_delivery(path)
    return observed["integratedLufs"], observed["truePeakDbtp"]


def is_faststart(path: str) -> Optional[bool]:
    """True when the ``moov`` atom precedes ``mdat`` (progressive-download
    ready). Walks the top-level atom table, honoring 64-bit extended sizes.
    None if either atom is absent or the file can't be parsed."""
    try:
        moov = mdat = None
        pos = 0
        with open(path, "rb") as handle:
            while True:
                header = handle.read(8)
                if len(header) < 8:
                    break
                size = struct.unpack(">I", header[:4])[0]
                atom = header[4:8]
                if size == 1:                       # 64-bit extended size
                    ext = handle.read(8)
                    if len(ext) < 8:
                        break
                    size = struct.unpack(">Q", ext)[0]
                if atom == b"moov" and moov is None:
                    moov = pos
                if atom == b"mdat" and mdat is None:
                    mdat = pos
                if moov is not None and mdat is not None:
                    break
                if size < 8:                        # size 0 = extends to EOF
                    break
                pos += size
                handle.seek(pos)
        if moov is None or mdat is None:
            return None
        return moov < mdat
    except OSError:
        return None


def mean_luma(path: str) -> Optional[float]:
    """Mean luma (0-255) of an image, or None if unreadable. Used to catch a
    near-black cover frame (the de-facto thumbnail / loop start — edge C9)."""
    try:
        with Image.open(path) as image:
            grey = image.convert("L")
            histogram = grey.histogram()
            total = sum(histogram)
            if not total:
                return None
            weighted = sum(level * count for level, count in enumerate(histogram))
            return weighted / total
    except (OSError, ValueError):
        return None


def image_size(path: str) -> Optional[tuple[int, int]]:
    """(width, height) of an image, or None if unreadable."""
    try:
        with Image.open(path) as image:
            return image.size
    except (OSError, ValueError):
        return None


def extract_frame(src: str, timestamp: float, out_path: str) -> bool:
    """Write one JPG at ``timestamp`` (input-side seek) for visual review.

    Fast seek is fine for QC stills. Returns True on success.
    """
    proc = run_ff(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                   "-ss", f"{max(0.0, timestamp):.3f}", "-i", src,
                   "-frames:v", "1", "-q:v", "3", out_path])
    return proc.returncode == 0 and os.path.exists(out_path)


def edge_density_image(image: Image.Image, y0: int, y1: int,
                       threshold: int = 40) -> Optional[float]:
    """Measure one held raster; invalid or unmeasurable bands return None."""
    width, height = image.size
    if any(type(value) is not int for value in (y0, y1, threshold)):
        return None
    if not 0 <= y0 < y1 <= height or y1 - y0 < 2 or width < 2:
        return None
    if not 0 <= threshold <= 255:
        return None
    band = image.convert("L").crop((0, y0, width, y1))
    band_w, band_h = band.size
    left = band.crop((0, 0, band_w - 1, band_h))
    right = band.crop((1, 0, band_w, band_h))
    diff = ImageChops.difference(left, right)
    strong = diff.point(lambda p: 255 if p > threshold else 0).histogram()[255]
    return strong / ((band_w - 1) * band_h)


def edge_density(path: str, y0: int, y1: int, threshold: int = 40) -> Optional[float]:
    """Measure actual band pixels; never confuse a missing band with zero."""
    try:
        with Image.open(path) as image:
            return edge_density_image(image, y0, y1, threshold)
    except (OSError, ValueError, Image.DecompressionBombError):
        return None
