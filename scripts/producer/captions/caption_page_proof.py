"""Strict page-only decoded proof parsing; no media execution or authority."""
from __future__ import annotations

import hashlib
import math
import re
from fractions import Fraction

from audit.audit_glitch_scan import _block_int, _progress_blocks

MAX_LOG_BYTES = 16 * 1024 * 1024
MAX_PROGRESS_BYTES = 64 * 1024
_MD5 = re.compile(r"\s*0,\s*(-?\d+),\s*(-?\d+),\s*(\d+),\s*(\d+),\s*([a-f0-9]{32})\s*")
_NUMBER = r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"
_FRAME = re.compile(rf"frame:\s*(\d+)\s+pts:\s*(-?\d+)\s+pts_time:\s*({_NUMBER})\s*")
_ALPHA = re.compile(rf"lavfi\.signalstats\.YMAX=({_NUMBER})")


def page_progress(raw: str, frames: int) -> None:
    """Require one terminal exact-count report, allowing a one-frame zero PTS."""
    if len(raw.encode("utf8")) > MAX_PROGRESS_BYTES:
        raise RuntimeError("caption page progress exceeds its bound")
    blocks = _progress_blocks(raw)
    if not blocks or blocks[-1]["progress"] != "end" \
            or any(row["progress"] != "continue" for row in blocks[:-1]):
        raise RuntimeError("caption page lacks one final progress=end")
    counts = [_block_int(row, "frame") for row in blocks]
    if counts[-1] != frames or any(count < 0 for count in counts) \
            or any(right < left for left, right in zip(counts, counts[1:])):
        raise RuntimeError("caption page terminal decoded frame count differs")
    if _block_int(blocks[-1], "out_time_us") < 0:
        raise RuntimeError("caption page terminal presentation time is negative")
    for row in blocks:
        if _block_int(row, "dup_frames") or _block_int(row, "drop_frames"):
            raise RuntimeError("caption page proof duplicated or dropped frames")


def page_frame_md5(raw: str, expected: dict) -> str:
    """Validate every whole RGBA frame and retain the EXACT old framemd5 bytes."""
    if len(raw.encode("utf8")) > MAX_LOG_BYTES:
        raise RuntimeError("caption page framemd5 exceeds its bound")
    rows, headers = _frame_rows(raw)
    frames = int(expected["nb_read_frames"])
    if len(rows) != frames:
        raise RuntimeError("caption page framemd5 is frame-incomplete")
    _frame_headers(headers, expected)
    size = expected["width"] * expected["height"] * 4
    for index, (dts, pts, duration, measured_size, _md5) in enumerate(rows):
        if (int(dts), int(pts), int(duration), int(measured_size)) != (index, index, 1, size):
            raise RuntimeError("caption page framemd5 clock or full RGBA size differs")
    return hashlib.sha256(raw.encode("utf8")).hexdigest()


def _frame_rows(raw: str) -> tuple[list[tuple[str, ...]], list[str]]:
    """Separate the unchanged muxer header from strictly parsed complete rows."""
    lines = raw.splitlines()
    split = next((index for index, line in enumerate(lines)
                  if not line.startswith("#")), len(lines))
    matches = [_MD5.fullmatch(line) for line in lines[split:]]
    if any(match is None for match in matches):
        raise RuntimeError("caption page framemd5 row or late header is malformed")
    return [match.groups() for match in matches], lines[:split]


def _frame_headers(headers: list[str], expected: dict) -> None:
    """Bind the sole rawvideo stream's exact rational clock and canvas."""
    required = {"#format: frame checksums", "#version: 2", "#hash: MD5",
                "#media_type 0: video", "#codec_id 0: rawvideo",
                f"#dimensions 0: {expected['width']}x{expected['height']}"}
    if not required.issubset(headers) or len(headers) != len(set(headers)):
        raise RuntimeError("caption page framemd5 stream headers differ")
    times = [line.removeprefix("#tb 0: ") for line in headers if line.startswith("#tb ")]
    if len(times) != 1:
        raise RuntimeError("caption page framemd5 time base differs")
    try:
        valid = Fraction(times[0]) == 1 / Fraction(expected["r_frame_rate"])
    except (ValueError, ZeroDivisionError) as error:
        raise RuntimeError("caption page framemd5 time base is malformed") from error
    if not valid:
        raise RuntimeError("caption page framemd5 time base differs")


def page_alpha(raw: str, expected: dict) -> dict:
    """Require exactly one finite bounded alpha maximum per decoded frame."""
    if len(raw.encode("utf8")) > MAX_LOG_BYTES:
        raise RuntimeError("caption page alpha metadata exceeds its bound")
    lines = raw.splitlines()
    frames = int(expected["nb_read_frames"])
    if len(lines) != frames * 2:
        raise RuntimeError("caption page alpha metadata is frame-incomplete")
    maxima, points = [], []
    for index in range(frames):
        header, value = _FRAME.fullmatch(lines[index * 2]), _ALPHA.fullmatch(lines[index * 2 + 1])
        if header is None or value is None or int(header[1]) != index:
            raise RuntimeError("caption page alpha frame/value pairing differs")
        point, alpha = float(header[3]), float(value[1])
        if int(header[2]) < 0 or not math.isfinite(point) or point < 0 \
                or not math.isfinite(alpha) or not 0 <= alpha <= 255:
            raise RuntimeError("caption page alpha measurement is invalid")
        maxima.append(alpha)
        points.append((int(header[2]), point))
    if points[0] != (0, 0.0) or any(right[0] <= left[0] or right[1] <= left[1]
                                   for left, right in zip(points, points[1:])):
        raise RuntimeError("caption page alpha decoded clock is offset or unordered")
    if max(maxima) <= 0:
        raise RuntimeError("caption page has no bounded alpha occupancy")
    return {"alphaMax": max(maxima), "framesMeasured": len(maxima)}
