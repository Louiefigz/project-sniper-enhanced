"""Bounded nearby review samples, preserving original PTS and every label.

This changes extraction work only, never the required sample set or quality.
Unsupported sources keep the existing single-frame path. A failed eligible
batch stays failed; old images cannot turn a partial attempt into evidence.
"""
from __future__ import annotations

import math
import os
import stat
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

from PIL import Image

from audit.audit_probe import run_ff

MAX_OUTPUTS = 6
MAX_SPAN_MS = 1500
MAX_GAP_MS = 750
MAX_JPEG_BYTES = 64 * 1024 * 1024
QUALIFIED_RATES = frozenset(Fraction(rate) for rate in (
    "24", "24000/1001", "25", "30000/1001", "30", "50", "60000/1001", "60"))


@dataclass(frozen=True)
class FrameTarget:
    """Original list identity with the same millisecond seek as legacy FFmpeg."""

    index: int
    milliseconds: int
    path: str


def review_batch_eligible(probe: dict | None) -> bool:
    """Select only ordinary zero-origin CFR H.264/yuv420p final streams."""
    if type(probe) is not dict:
        return False
    streams = probe.get("streams")
    if type(streams) is not list or any(type(row) is not dict for row in streams) or type(probe.get("format")) is not dict:
        return False
    videos = [row for row in streams if row.get("codec_type") == "video"]
    if len(videos) != 1:
        return False
    video = videos[0]
    if type(video.get("tags", {})) is not dict or type(video.get("disposition", {})) is not dict:
        return False
    if video.get("codec_name") != "h264" or video.get("pix_fmt") != "yuv420p" or video.get("sample_aspect_ratio") != "1:1" \
            or video.get("side_data_list") or video.get("tags", {}).get("rotate", "0") != "0" \
            or video.get("disposition", {}).get("attached_pic", 0):
        return False
    try:
        rate = Fraction(video["r_frame_rate"])
        return (rate == Fraction(video["avg_frame_rate"]) and rate in QUALIFIED_RATES
                and Fraction(video["start_time"]) == Fraction(probe["format"]["start_time"]) == 0
                and Fraction(video["time_base"]) > 0
                and all(type(video.get(key)) is int and 0 < video[key] <= 4096 for key in ("width", "height")))
    except (KeyError, ValueError, TypeError, ZeroDivisionError):
        return False


def group_targets(requested: list[tuple[float, str]]) -> list[list[FrameTarget]]:
    """Group nearby times without losing original ordering or duplicate events."""
    targets = []
    for index, (timestamp, destination) in enumerate(requested):
        if not math.isfinite(timestamp):
            raise ValueError("Review frame timestamp is unavailable")
        milliseconds = int(Decimal(f"{max(0.0, timestamp):.3f}") * 1000)
        targets.append(FrameTarget(index, milliseconds, destination))
    groups: list[list[FrameTarget]] = []
    for target in sorted(targets, key=lambda row: (row.milliseconds, row.index)):
        if not groups or len(groups[-1]) >= MAX_OUTPUTS \
                or target.milliseconds - groups[-1][0].milliseconds > MAX_SPAN_MS \
                or target.milliseconds - groups[-1][-1].milliseconds > MAX_GAP_MS:
            groups.append([])
        groups[-1].append(target)
    return groups


def _command(src: str, targets: list[FrameTarget], directory: Path) -> list[str]:
    """Keep global PTS: subtracting a decimal seek can move exact-boundary frames."""
    filters = [f"[0:v:0]split={len(targets)}" + "".join(f"[s{i}]" for i in range(len(targets)))]
    filters.extend(f"[s{i}]select=gte(t\\,{row.milliseconds / 1000:.3f}),setpts=PTS-STARTPTS[v{i}]"
                   for i, row in enumerate(targets))
    command = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-copyts",
               "-ss", f"{targets[0].milliseconds / 1000:.3f}", "-i", src,
               "-filter_complex", ";".join(filters)]
    for index in range(len(targets)):
        command += ["-map", f"[v{index}]", "-frames:v", "1", "-q:v", "3", str(directory / f"{index}.jpg")]
    return command


def _decode_jpeg(file: Path) -> bool:
    """Verify dimensions and full decode without changing the encoded image."""
    with Image.open(file) as image:
        if image.format != "JPEG" or not 0 < image.width <= 4096 or not 0 < image.height <= 4096:
            return False
        image.load()
    return True


def _valid_jpeg(file: Path) -> bool:
    """Require a freshly written regular, fully decodable JPEG before publication."""
    try:
        info = file.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= MAX_JPEG_BYTES:
            return False
        return _decode_jpeg(file)
    except (OSError, ValueError):
        return False


def _publish_batch(directory: Path, targets: list[FrameTarget]) -> bool:
    """Select no members if any validated image cannot be published."""
    try:
        for index, target in enumerate(targets):
            os.replace(directory / f"{index}.jpg", target.path)
    except OSError:
        return False
    return True


def _extract_batch(src: str, targets: list[FrameTarget]) -> bool:
    """No output is selected until every member is present; failures never fall back."""
    parent = Path(targets[0].path).parent
    if any(Path(row.path).parent != parent for row in targets):
        raise ValueError("Review batch destinations must share one evidence directory")
    with tempfile.TemporaryDirectory(prefix=".frame-batch-", dir=parent) as temporary:
        directory = Path(temporary)
        result = run_ff(_command(src, targets, directory))
        if result.returncode or not all(_valid_jpeg(directory / f"{index}.jpg") for index in range(len(targets))):
            return False
        return _publish_batch(directory, targets)


def extract_nearby_frames(src: str, requested: list[tuple[float, str]],
                          extract_one: Callable[[str, float, str], bool]) -> list[bool]:
    """Return a result for every original request; sparse samples stay individual."""
    results = [False] * len(requested)
    for targets in group_targets(requested):
        batched = len(targets) >= 3 and len({target.path for target in targets}) == len(targets)
        outcomes = ([_extract_batch(src, targets)] * len(targets) if batched else
                    [extract_one(src, target.milliseconds / 1000, target.path) for target in targets])
        for target, passed in zip(targets, outcomes):
            results[target.index] = passed
    return results
