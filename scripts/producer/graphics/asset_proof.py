"""Deterministic proof that a rendered graphic is safe to hand to Palmier."""
from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any

from graphics.template_contract import planned_copy, resolved_assets
from graphics.frame_oracles import terminal_alpha
from graphics.frame_quantization import rounded_frame_index

_SAMPLE_WIDTH, _SAMPLE_HEIGHT, _SAMPLE_FPS = 96, 54, 10
_MIN_AREA_RATIO, _MIN_SUSTAINED_FRACTION, _MIN_PIXEL_DELTA = 0.001, 0.5, 6


@dataclass(frozen=True)
class AssetProofRequest:
    """All immutable inputs required to prove one rendered asset."""

    path: str
    entry: dict
    fmt: str
    dimensions: tuple[int, int]
    expected_duration: float
    render_key: str
    expected_fps: float = 30.0
    comp_html: str | None = None
    require_terminal_clear: bool = False
    sealed_asset_inputs: tuple[dict, ...] | None = None


def _proof_tool(env_key: str, fallback: str) -> str:
    raw = os.environ.get(env_key, "").strip()
    if not raw:
        if os.environ.get("SNIPER_RENDER_IMAGE_ID"):
            raise RuntimeError(f"{env_key} is required for container render proof")
        return fallback
    if not os.path.isabs(raw):
        raise RuntimeError(f"{env_key} must be an absolute executable path")
    path = os.path.realpath(raw)
    if not os.path.isfile(path) or not os.access(path, os.X_OK):
        raise RuntimeError(f"{env_key} is not executable: {raw}")
    return path


def _proof_env() -> dict[str, str]:
    path = ("/usr/bin:/bin" if os.environ.get("SNIPER_RENDER_IMAGE_ID")
            else os.environ.get("PATH", "/usr/bin:/bin"))
    return {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
            "PATH": path, "TZ": "UTC"}


def _probe(path: str) -> dict:
    cmd = [_proof_tool("SNIPER_PROOF_FFPROBE_PATH", "ffprobe"),
           "-v", "error", "-show_entries", "stream=index,codec_type,codec_name,"
           "profile,pix_fmt,width,height,duration,nb_frames,avg_frame_rate,"
           "r_frame_rate:format=format_name,duration,size,nb_streams",
           "-of", "json", path]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, env=_proof_env())
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


def _copy_proof(entry: dict, render_key: str, comp_html: str | None = None) -> dict:
    copy = planned_copy(entry, comp_html)
    encoded = json.dumps(copy, ensure_ascii=False, separators=(",", ":"))
    return {"method": "validated-template-input", "expected": copy,
            "sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
            "renderInputKey": render_key,
            "note": "Template contract + content-addressed render; not OCR"}


def _raw_frames(path: str, filters: str, pixel_format: str,
                channels: int) -> list[bytes]:
    cmd = [_proof_tool("SNIPER_PROOF_FFMPEG_PATH", "ffmpeg"),
           "-nostdin", "-v", "error", "-i", path, "-vf", filters,
           "-an", "-f", "rawvideo", "-pix_fmt", pixel_format, "-"]
    proc = subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL,
                          env=_proof_env())
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", errors="replace").strip()[-240:]
        raise RuntimeError(f"graphic occupancy sampling failed: {message}")
    size = _SAMPLE_WIDTH * _SAMPLE_HEIGHT * channels
    if not proc.stdout or len(proc.stdout) % size:
        raise RuntimeError("graphic occupancy produced incomplete frame samples")
    return [proc.stdout[index:index + size]
            for index in range(0, len(proc.stdout), size)]


def _full_decode(path: str) -> dict:
    cmd = [_proof_tool("SNIPER_PROOF_FFMPEG_PATH", "ffmpeg"), "-nostdin",
           "-v", "error", "-xerror", "-i", path, "-map", "0:v:0",
           "-an", "-f", "null", "-"]
    proc = subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL,
                          env=_proof_env())
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", errors="replace").strip()[-240:]
        raise RuntimeError(f"graphic asset full decode failed: {message}")
    return {"method": "ffmpeg-full-xerror", "decoded": True}


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


def _occupancy(entry: dict, fmt: str, dimensions: tuple[int, int],
               measured: dict | None) -> dict:
    width, height = dimensions
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


def _asset_inputs(entry: dict,
                  sealed: tuple[dict, ...] | None = None) -> list[dict]:
    if sealed is not None:
        return [dict(row) for row in sealed]
    return [{"field": row["field"], "selector": row["selector"],
             "sha256": _sha256(row["path"])}
            for row in resolved_assets(entry)]


def _validate_codec(stream: dict, fmt: str) -> None:
    expected = ({"codec_name": "prores", "profile": "4444",
                 "pix_fmt": "yuva444p12le"} if fmt == "mov" else
                {"codec_name": "h264", "pix_fmt": "yuv420p"})
    for key, value in expected.items():
        if stream.get(key) != value:
            raise RuntimeError(f"graphic {fmt} requires {key}={value!r}; "
                               f"got {stream.get(key)!r}")


def _validate_stream(stream: dict,
                     request: AssetProofRequest) -> tuple[float, int, int, int]:
    width, height = int(stream.get("width", 0)), int(stream.get("height", 0))
    if stream.get("codec_type") != "video":
        raise RuntimeError("graphic asset's sole stream must be video")
    if (width, height) != request.dimensions:
        raise RuntimeError(
            f"graphic asset dimensions {(width, height)} != {request.dimensions}")
    duration = _number(stream.get("duration"))
    if duration is None or duration <= 0:
        raise RuntimeError("graphic asset has no positive video duration")
    fps = _fps(stream.get("avg_frame_rate"))
    real_fps = _fps(stream.get("r_frame_rate"))
    if fps is None or real_fps is None or abs(fps - request.expected_fps) > 1e-6 \
            or abs(real_fps - request.expected_fps) > 1e-6:
        raise RuntimeError(f"graphic asset fps must be {request.expected_fps:g}")
    tolerance = max(1.0 / fps + 0.005, 0.04)
    if abs(duration - request.expected_duration) > tolerance:
        raise RuntimeError(f"graphic asset duration {duration:.4f}s != "
                           f"planned {request.expected_duration:.4f}s "
                           f"(tol {tolerance:.4f}s)")
    frames = int(_number(stream.get("nb_frames")) or 0)
    expected_frames = rounded_frame_index(request.expected_duration, request.expected_fps)
    if frames != expected_frames or frames <= 0:
        raise RuntimeError(f"graphic asset frame count {frames} != {expected_frames}")
    _validate_codec(stream, request.fmt)
    return duration, width, height, frames


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


def prove_rendered_asset(request: AssetProofRequest) -> dict:
    """Fail closed on asset shape, then persist proof beside the cache file."""
    path, entry, fmt = request.path, request.entry, request.fmt
    if not os.path.isfile(path) or os.path.getsize(path) <= 0:
        raise RuntimeError(f"graphic asset is missing or empty: {path}")
    probe = _probe(path)
    streams = probe.get("streams") if isinstance(probe, dict) else None
    if not isinstance(streams, list) or len(streams) != 1:
        raise RuntimeError("graphic asset must contain one video stream and no others")
    duration, width, height, frame_count = _validate_stream(streams[0], request)
    decode = _full_decode(path)
    measured = _visible_alpha(path) if fmt == "mov" else _visible_opaque(path)
    terminal = terminal_alpha(path, frame_count, _proof_tool(
        "SNIPER_PROOF_FFMPEG_PATH", "ffmpeg"), _proof_env()) \
        if request.require_terminal_clear else None
    proof = {"schemaVersion": 1, "kind": entry.get("kind"),
             "asset": {"sha256": _sha256(path), "sizeBytes": os.path.getsize(path),
                       "codec": streams[0].get("codec_name"),
                       "profile": streams[0].get("profile"),
                       "pixelFormat": streams[0].get("pix_fmt"), "width": width,
                       "height": height, "durationS": duration,
                       "frameCount": frame_count, "fps": request.expected_fps},
             "decode": decode,
             "terminalFrame": terminal,
             "alphaMode": "required" if fmt == "mov" else "opaque",
             "occupancy": _occupancy(entry, fmt, (width, height), measured),
             "assetInputs": _asset_inputs(entry, request.sealed_asset_inputs),
             "copy": _copy_proof(entry, request.render_key, request.comp_html)}
    proof["sidecar"] = _write_sidecar(path, proof)
    return proof
