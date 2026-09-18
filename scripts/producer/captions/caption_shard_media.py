#!/usr/bin/env python3
"""Decode-prove caption shard clock, alpha edges, and shaped safe bounds."""
from __future__ import annotations

import json
import re
import subprocess
from fractions import Fraction

from captions.caption_contract import CaptionContractError

_ALPHA_MAX_RE = re.compile(r"lavfi\.signalstats\.YMAX=([0-9.]+)")
_BBOX_RE = re.compile(r"lavfi\.bbox\.(x1|x2|y1|y2)=([0-9]+)")


def _rate(compilation: dict) -> tuple[Fraction, str]:
    fps = compilation.get("fps")
    try:
        rate = Fraction(int(fps["numerator"]), int(fps["denominator"]))
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise CaptionContractError("caption shard fps is malformed") from exc
    return rate, f"{rate.numerator}/{rate.denominator}"


def _probe(path: str) -> dict:
    command = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-count_frames", "-show_entries",
        "stream=codec_name,pix_fmt,width,height,r_frame_rate,nb_read_frames",
        "-of", "json", path,
    ]
    process = subprocess.run(command, capture_output=True, text=True)
    try:
        streams = json.loads(process.stdout).get("streams") or []
    except json.JSONDecodeError as exc:
        raise RuntimeError("caption shard ffprobe returned invalid JSON") from exc
    if process.returncode or len(streams) != 1:
        raise RuntimeError(
            "caption shard cannot be decoded: " + process.stderr[-500:])
    return streams[0]


def _alpha_edge_maxima(path: str, frames: int) -> list[float]:
    selected = "eq(n,0)" if frames == 1 \
        else f"eq(n,0)+eq(n,{frames - 1})"
    graph = (
        f"select='{selected}',alphaextract,signalstats,"
        "metadata=print:key=lavfi.signalstats.YMAX:file=-"
    )
    process = subprocess.run([
        "ffmpeg", "-v", "error", "-i", path, "-vf", graph,
        "-vsync", "0", "-an", "-f", "null", "-",
    ], capture_output=True, text=True)
    if process.returncode:
        raise RuntimeError(
            "caption shard alpha proof failed: " + process.stderr[-500:])
    return [
        float(value) for value in _ALPHA_MAX_RE.findall(
            process.stdout + process.stderr)
    ]


def _shaped_bounds(path: str, frames: int) -> dict:
    process = subprocess.run([
        "ffmpeg", "-v", "error", "-i", path, "-vf",
        "alphaextract,bbox=min_val=1,metadata=print:file=-",
        "-an", "-f", "null", "-",
    ], capture_output=True, text=True)
    if process.returncode:
        raise RuntimeError(
            "caption shard shaped-bounds proof failed: "
            + process.stderr[-500:])
    values = {key: [] for key in ("x1", "x2", "y1", "y2")}
    for key, raw in _BBOX_RE.findall(process.stdout + process.stderr):
        values[key].append(int(raw))
    if any(len(rows) != frames for rows in values.values()):
        raise RuntimeError(
            "caption shard has an unmeasured or empty shaped frame")
    return {
        "minX": min(values["x1"]), "maxX": max(values["x2"]),
        "minY": min(values["y1"]), "maxY": max(values["y2"]),
        "framesMeasured": frames,
    }


def _expected_probe(compilation: dict, frames: int) -> dict:
    destination = compilation["destination"]
    _, token = _rate(compilation)
    return {
        "codec_name": "png", "pix_fmt": "rgba",
        "width": destination["width"], "height": destination["height"],
        "r_frame_rate": token, "nb_read_frames": str(frames),
    }


def _validate_safe_bounds(bounds: dict, destination: dict) -> None:
    safe = destination["safeZones"]
    outside = (
        bounds["minX"] < safe["left"]
        or bounds["maxX"] >= destination["width"] - safe["right"]
        or bounds["minY"] < safe["top"]
        or bounds["maxY"] >= destination["height"] - safe["bottom"]
    )
    if outside:
        raise CaptionContractError(
            "shaped caption glyphs exceed the destination safe zone")


def prove_caption_shard_media(path: str, compilation: dict,
                              frames: int) -> dict:
    """Fail closed unless every decoded frame meets the shard media contract."""
    if isinstance(frames, bool) or not isinstance(frames, int) or frames < 1:
        raise CaptionContractError("caption shard frame count is invalid")
    probe = _probe(path)
    expected = _expected_probe(compilation, frames)
    if any(probe.get(key) != value for key, value in expected.items()):
        raise RuntimeError(
            f"caption shard media contract failed: {probe!r} != {expected!r}")
    maxima = _alpha_edge_maxima(path, frames)
    expected_edges = 1 if frames == 1 else 2
    if len(maxima) != expected_edges or min(maxima) <= 0 \
            or max(maxima) > 255:
        raise RuntimeError(
            "caption shard first/last frames have no proved alpha occupancy")
    bounds = _shaped_bounds(path, frames)
    _validate_safe_bounds(bounds, compilation["destination"])
    return {
        "stream": expected, "edgeAlphaMax": maxima,
        "shapedSafeBounds": bounds,
    }
