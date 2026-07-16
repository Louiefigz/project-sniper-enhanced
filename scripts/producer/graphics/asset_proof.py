#!/usr/bin/env python3
"""Deterministic proof that a rendered graphic is safe to hand to Palmier."""
from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import tempfile
from typing import Any

from graphics.template_contract import planned_copy, resolved_assets

_SAMPLE_WIDTH = 96
_SAMPLE_HEIGHT = 54
_SAMPLE_FPS = 10
_MIN_AREA_RATIO = 0.001
_MIN_SUSTAINED_FRACTION = 0.5
_MIN_PIXEL_DELTA = 6


def _probe(path: str) -> dict:
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream=codec_name,pix_fmt,width,height,duration,"
           "nb_frames,avg_frame_rate:format=duration,size", "-of", "json", path]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"graphic asset ffprobe failed: {proc.stderr.strip()[-240:]}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("graphic asset ffprobe returned invalid JSON") from exc


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _fps(value: Any) -> float | None:
    if not isinstance(value, str) or "/" not in value:
        return _number(value)
    numerator, denominator = value.split("/", 1)
    top, bottom = _number(numerator), _number(denominator)
    return top / bottom if top is not None and bottom not in (None, 0) else None


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_proof(entry: dict, render_key: str) -> dict:
    copy = planned_copy(entry)
    encoded = json.dumps(copy, ensure_ascii=False, separators=(",", ":"))
    return {"method": "validated-template-input", "expected": copy,
            "sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
            "renderInputKey": render_key,
            "note": "Template contract + content-addressed render; not OCR"}


def _raw_frames(path: str, filters: str, pixel_format: str,
                channels: int) -> list[bytes]:
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-i", path, "-vf", filters,
           "-an", "-f", "rawvideo", "-pix_fmt", pixel_format, "-"]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", errors="replace").strip()[-240:]
        raise RuntimeError(f"graphic occupancy sampling failed: {message}")
    size = _SAMPLE_WIDTH * _SAMPLE_HEIGHT * channels
    if not proc.stdout or len(proc.stdout) % size:
        raise RuntimeError("graphic occupancy produced incomplete frame samples")
    return [proc.stdout[index:index + size]
            for index in range(0, len(proc.stdout), size)]


def _sustained(ratios: list[float], blank: str) -> dict:
    if not ratios:
        raise RuntimeError("graphic occupancy produced no frame samples")
    meaningful = [ratio for ratio in ratios if ratio >= _MIN_AREA_RATIO]
    required = 1 if len(ratios) == 1 else max(
        2, math.ceil(len(ratios) * _MIN_SUSTAINED_FRACTION))
    if not meaningful:
        raise RuntimeError(f"{blank} (peak occupancy={max(ratios):.6f})")
    if len(meaningful) < required:
        raise RuntimeError(
            f"{blank} lacks sustained meaningful occupancy "
            f"({len(meaningful)}/{len(ratios)} frames; needs {required})")
    return {"peakRatio": max(ratios), "meanRatio": sum(ratios) / len(ratios),
            "sustainedRatio": min(meaningful),
            "meaningfulFrames": len(meaningful), "sampledFrames": len(ratios),
            "meaningfulFrameFraction": len(meaningful) / len(ratios)}


def _visible_alpha(path: str) -> dict:
    scale = f"scale={_SAMPLE_WIDTH}:{_SAMPLE_HEIGHT}:flags=area"
    frames = _raw_frames(path, f"alphaextract,{scale},fps={_SAMPLE_FPS}",
                         "gray", 1)
    ratios = [sum(frame) / (255.0 * len(frame)) for frame in frames]
    return {**_sustained(ratios, "graphic overlay is blank/transparent"),
            "method": "ffmpeg-alpha-sustained-area", "sampleFps": _SAMPLE_FPS}


def _content_ratio(frame: bytes) -> float:
    pixels = len(frame) // 3
    channels = [frame[offset::3] for offset in range(3)]
    medians = [sorted(channel)[pixels // 2] for channel in channels]
    meaningful = 0
    for index in range(pixels):
        if max(abs(channels[channel][index] - medians[channel])
               for channel in range(3)) >= _MIN_PIXEL_DELTA:
            meaningful += 1
    return meaningful / pixels


def _visible_opaque(path: str) -> dict:
    filters = (f"scale={_SAMPLE_WIDTH}:{_SAMPLE_HEIGHT}:flags=area,"
               f"fps={_SAMPLE_FPS}")
    frames = _raw_frames(path, filters, "rgb24", 3)
    ratios = [_content_ratio(frame) for frame in frames]
    return {**_sustained(ratios, "graphic own-screen render is blank/flat"),
            "method": "ffmpeg-rgb-sustained-content", "sampleFps": _SAMPLE_FPS}


def _occupancy(entry: dict, fmt: str, width: int, height: int,
               measured: dict | None) -> dict:
    anchor = entry.get("anchor", "free-band")
    if entry.get("presenterFilled"):
        return {"mode": "presenter-filled-card", "canvasPx": [width, height],
                "measured": measured,
                "basis": ("isolated cut-mapped presenter footage fills the "
                          "registered hole before Desktop import")}
    if anchor == "own-screen" and fmt == "mp4":
        return {"mode": "opaque-measured-content", "canvasPx": [width, height],
                "areaRatio": measured["sustainedRatio"], "measured": measured,
                "basis": "sustained spatial content measured from decoded frames"}
    if anchor == "own-screen":
        return {"mode": "alpha-hole-canvas", "canvasPx": [width, height],
                "measured": measured,
                "basis": "own-screen alpha template intentionally preserves a hole"}
    return {"mode": "alpha-overlay", "canvasPx": [width, height],
            "measured": measured,
            "basis": "alpha stream matches the composition canvas"}


def _asset_inputs(entry: dict) -> list[dict]:
    return [{"field": row["field"], "selector": row["selector"],
             "sha256": _sha256(row["path"])}
            for row in resolved_assets(entry)]


def _validate_stream(stream: dict, fmt: str, dimensions: tuple[int, int],
                     expected_duration: float) -> tuple[float, int, int]:
    width, height = int(stream.get("width", 0)), int(stream.get("height", 0))
    if (width, height) != dimensions:
        raise RuntimeError(f"graphic asset dimensions {(width, height)} != {dimensions}")
    duration = _number(stream.get("duration"))
    if duration is None or duration <= 0:
        raise RuntimeError("graphic asset has no positive video duration")
    fps = _fps(stream.get("avg_frame_rate")) or 30.0
    tolerance = max(1.0 / fps + 0.005, 0.04)
    if abs(duration - expected_duration) > tolerance:
        raise RuntimeError(f"graphic asset duration {duration:.4f}s != "
                           f"planned {expected_duration:.4f}s (tol {tolerance:.4f}s)")
    pix_fmt = str(stream.get("pix_fmt", ""))
    has_alpha = pix_fmt.startswith("yuva") or pix_fmt.startswith("rgba") \
        or pix_fmt.startswith("bgra") or pix_fmt.startswith("argb")
    if fmt == "mov" and not has_alpha:
        raise RuntimeError(f"graphic alpha asset lost alpha (pix_fmt={pix_fmt!r})")
    if fmt == "mp4" and has_alpha:
        raise RuntimeError(f"opaque graphic unexpectedly has alpha (pix_fmt={pix_fmt!r})")
    return duration, width, height


def _write_sidecar(path: str, proof: dict) -> str:
    sidecar = path + ".proof.json"
    directory = os.path.dirname(sidecar) or "."
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=directory, delete=False,
        prefix=os.path.basename(sidecar) + ".", suffix=".tmp")
    try:
        with handle:
            json.dump(proof, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(handle.name, sidecar)
    finally:
        if os.path.exists(handle.name):
            os.remove(handle.name)
    return sidecar


def prove_rendered_asset(path: str, entry: dict, fmt: str,
                         dimensions: tuple[int, int], expected_duration: float,
                         render_key: str) -> dict:
    """Fail closed on asset shape, then persist proof beside the cache file."""
    if not os.path.isfile(path) or os.path.getsize(path) <= 0:
        raise RuntimeError(f"graphic asset is missing or empty: {path}")
    probe = _probe(path)
    streams = probe.get("streams") if isinstance(probe, dict) else None
    if not isinstance(streams, list) or len(streams) != 1:
        raise RuntimeError("graphic asset must contain exactly one video stream")
    duration, width, height = _validate_stream(
        streams[0], fmt, dimensions, expected_duration)
    measured = _visible_alpha(path) if fmt == "mov" else _visible_opaque(path)
    frame_count = int(_number(streams[0].get("nb_frames")) or 0)
    if frame_count <= 0 and duration <= 0:
        raise RuntimeError("graphic asset contains no video frames")
    proof = {"schemaVersion": 1, "kind": entry.get("kind"),
             "asset": {"sha256": _sha256(path), "sizeBytes": os.path.getsize(path),
                       "codec": streams[0].get("codec_name"),
                       "pixelFormat": streams[0].get("pix_fmt"), "width": width,
                       "height": height, "durationS": duration,
                       "frameCount": frame_count},
             "alphaMode": "required" if fmt == "mov" else "opaque",
             "occupancy": _occupancy(entry, fmt, width, height, measured),
             "assetInputs": _asset_inputs(entry),
             "copy": _copy_proof(entry, render_key)}
    proof["sidecar"] = _write_sidecar(path, proof)
    return proof
