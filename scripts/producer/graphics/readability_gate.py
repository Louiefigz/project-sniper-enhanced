"""Measured text contrast against the actual underlying footage interval."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from dataclasses import dataclass

from media_probe import _fps_fraction, probe_video, probe_video_frames

_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_SAMPLE_EDGE = 8
_MAX_SAMPLES = 9


@dataclass(frozen=True)
class ReadabilityRequest:
    """Bounded inputs for one visible text interval."""

    footage_path: str
    frame_range: tuple[int, int]
    text_box: tuple[float, float, float, float]
    treatment: dict


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _media_path(path: object) -> str:
    if not isinstance(path, str) or not os.path.isabs(path):
        raise ValueError("readability footage path must be absolute")
    real = os.path.realpath(path)
    if real != path or os.path.islink(path) or not os.path.isfile(path):
        raise ValueError("readability footage must be a canonical regular file")
    return real


def _color(value: object, label: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or not _COLOR.fullmatch(value):
        raise ValueError(f"{label} must be #RRGGBB")
    return tuple(int(value[index:index + 2], 16) for index in (1, 3, 5))


def _treatment(value: object) -> tuple[tuple[int, int, int], float, dict | None]:
    if not isinstance(value, dict) or set(value) - {
            "textColor", "minimumContrast", "backing"} \
            or "textColor" not in value:
        raise ValueError("readability treatment has unsupported fields")
    text = _color(value["textColor"], "textColor")
    threshold = value.get("minimumContrast", 4.5)
    if type(threshold) not in {int, float} or not 1 <= float(threshold) <= 21:
        raise ValueError("minimumContrast must be within 1..21")
    backing = value.get("backing")
    if backing is None:
        return text, float(threshold), None
    keys = {"color", "opacity", "assetProofSha256"}
    if not isinstance(backing, dict) or set(backing) != keys:
        raise ValueError("readability backing proof is incomplete")
    color = _color(backing["color"], "backing.color")
    opacity = backing["opacity"]
    if type(opacity) not in {int, float} or not 0 < float(opacity) <= 1:
        raise ValueError("backing.opacity must be within (0,1]")
    if not isinstance(backing["assetProofSha256"], str) \
            or not _DIGEST.fullmatch(backing["assetProofSha256"]):
        raise ValueError("backing.assetProofSha256 must be a SHA-256")
    return text, float(threshold), {
        "color": color, "opacity": float(opacity),
        "assetProofSha256": backing["assetProofSha256"],
    }


def _frames(value: object, total: int) -> list[int]:
    valid = isinstance(value, tuple) and len(value) == 2 \
        and all(type(item) is int for item in value)
    if not valid:
        raise ValueError("readability frame_range must be an integer pair")
    start, end = value
    if not 0 <= start < end <= total:
        raise ValueError("readability frame range is outside the footage")
    count = min(_MAX_SAMPLES, end - start)
    if count == 1:
        return [start]
    return sorted({start + round(index * (end - start - 1) / (count - 1))
                   for index in range(count)})


def _crop(value: object, width: int, height: int) -> tuple[int, int, int, int]:
    valid = isinstance(value, tuple) and len(value) == 4 \
        and all(type(item) in {int, float} for item in value)
    if not valid:
        raise ValueError("readability text_box must be a normalized xywh tuple")
    x, y, w, h = (float(item) for item in value)
    if not (0 <= x < 1 and 0 <= y < 1 and w > 0 and h > 0
            and x + w <= 1 and y + h <= 1):
        raise ValueError("readability text_box leaves the footage canvas")
    left, top = round(x * width), round(y * height)
    right = min(width, max(left + 1, round((x + w) * width)))
    bottom = min(height, max(top + 1, round((y + h) * height)))
    return left, top, right - left, bottom - top


def _ffmpeg() -> str:
    raw = os.environ.get("SNIPER_PROOF_FFMPEG_PATH", "").strip()
    path = os.path.realpath(raw) if raw else shutil.which("ffmpeg")
    if not path or not os.path.isabs(path) or not os.access(path, os.X_OK):
        raise RuntimeError("readability gate requires a pinned/executable ffmpeg")
    return path


def _sample(path: str, indices: list[int],
            crop: tuple[int, int, int, int]) -> tuple[bytes, str]:
    ffmpeg = _ffmpeg()
    selector = "+".join(f"eq(n\\,{index})" for index in indices)
    x, y, width, height = crop
    filters = (
        f"select='{selector}',crop={width}:{height}:{x}:{y},"
        f"scale={_SAMPLE_EDGE}:{_SAMPLE_EDGE}:flags=area,format=rgb24"
    )
    command = [
        ffmpeg, "-v", "error", "-i", path, "-vf", filters,
        "-fps_mode", "passthrough", "-f", "rawvideo", "-",
    ]
    proc = subprocess.run(command, stdin=subprocess.DEVNULL,
                          capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "readability footage decode failed: " +
            proc.stderr.decode("utf-8", "replace").strip()[-500:])
    expected = len(indices) * _SAMPLE_EDGE * _SAMPLE_EDGE * 3
    if len(proc.stdout) != expected:
        raise RuntimeError(
            f"readability decode returned {len(proc.stdout)}/{expected} bytes")
    return proc.stdout, ffmpeg


def _luminance(rgb: tuple[float, float, float]) -> float:
    values = []
    for channel in rgb:
        normalized = channel / 255
        values.append(normalized / 12.92 if normalized <= 0.04045
                      else ((normalized + 0.055) / 1.055) ** 2.4)
    return 0.2126 * values[0] + 0.7152 * values[1] + 0.0722 * values[2]


def _contrast(foreground: tuple[int, int, int],
              background: tuple[float, float, float]) -> float:
    first, second = _luminance(foreground), _luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def _effective(rgb: tuple[int, int, int],
               backing: dict | None) -> tuple[float, float, float]:
    if backing is None:
        return rgb
    alpha = backing["opacity"]
    return tuple(alpha * front + (1 - alpha) * back
                 for front, back in zip(backing["color"], rgb))


def measure_readability(request: ReadabilityRequest) -> dict:
    """Measure the worst sampled contrast; missing evidence raises."""
    path = _media_path(request.footage_path)
    stream = probe_video(path)
    width, height = int(stream["width"]), int(stream["height"])
    total = probe_video_frames(path)
    indices = _frames(request.frame_range, total)
    crop = _crop(request.text_box, width, height)
    text, threshold, backing = _treatment(request.treatment)
    pixels, ffmpeg = _sample(path, indices, crop)
    contrasts = []
    for offset in range(0, len(pixels), 3):
        rgb = tuple(pixels[offset:offset + 3])
        contrasts.append(_contrast(text, _effective(rgb, backing)))
    minimum = min(contrasts)
    fps = _fps_fraction(str(stream["r_frame_rate"]))
    backing_receipt = None if backing is None else {
        "color": request.treatment["backing"]["color"],
        "opacity": backing["opacity"],
        "assetProofSha256": backing["assetProofSha256"],
    }
    return {
        "schemaVersion": 1, "passed": minimum + 1e-9 >= threshold,
        "method": "actual-footage-box-worst-pixel-v1",
        "sourceSha256": _sha256(path),
        "sourceFps": {
            "numerator": str(fps.numerator),
            "denominator": str(fps.denominator),
        },
        "frameRange": {
            "startFrame": request.frame_range[0],
            "endFrameExclusive": request.frame_range[1],
        },
        "sampleFrames": indices, "samplePixelCount": len(contrasts),
        "textBoxPixels": list(crop),
        "textColor": request.treatment["textColor"],
        "backing": backing_receipt, "minimumContrast": round(minimum, 6),
        "requiredContrast": threshold,
        "ffmpegSha256": _sha256(ffmpeg),
    }


def prove_readability(request: ReadabilityRequest) -> dict:
    """Require measured contrast or a hash-bound backing treatment."""
    receipt = measure_readability(request)
    if not receipt["passed"]:
        raise RuntimeError(
            "real-footage readability failed: minimum contrast "
            f"{receipt['minimumContrast']} < {receipt['requiredContrast']}")
    return receipt
