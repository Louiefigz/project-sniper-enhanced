"""Real-media helpers shared by the retained P4 exit cohort."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess

import numpy as np
from PIL import Image, ImageDraw
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from current_render_graph_contract import canonical_bytes, file_hash
from graphics.render_tools import resolve_tools
from graphics.scene_oracle import decoded_frame_hashes


def run(command: list[str], timeout: int = 300) -> bytes:
    """Run one closed media command and retain a useful failure tail."""
    result = subprocess.run(
        command, stdin=subprocess.DEVNULL, capture_output=True,
        timeout=timeout, check=False)
    if result.returncode:
        detail = (result.stderr or result.stdout).decode(
            "utf-8", errors="replace")[-800:]
        raise RuntimeError(f"media command failed: {detail}")
    return result.stdout


def ffmpeg(*arguments: str, timeout: int = 300) -> bytes:
    tool = resolve_tools()["ffmpeg"]
    return run([
        tool, "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
        *arguments,
    ], timeout)


@dataclass(frozen=True)
class ProgramSpec:
    """Small deterministic real-media fixture description."""

    dims: tuple[int, int]
    fps: int
    duration: float
    pattern: str = "testsrc2"


def make_program(path: Path, spec: ProgramSpec) -> None:
    """Create a deterministic populated video+audio project master."""
    width, height = spec.dims
    if spec.pattern == "green":
        source = (
            f"color=c=0x00ff00:s={width}x{height}:"
            f"r={spec.fps}:d={spec.duration}")
    elif spec.pattern == "flat":
        source = (
            f"color=c=0x204060:s={width}x{height}:"
            f"r={spec.fps}:d={spec.duration}")
    else:
        source = (
            f"testsrc2=s={width}x{height}:r={spec.fps}:d={spec.duration}")
    ffmpeg(
        "-f", "lavfi", "-i", source,
        "-f", "lavfi", "-i",
        f"sine=frequency=440:sample_rate=48000:duration={spec.duration}",
        "-map", "0:v:0", "-map", "1:a:0", "-shortest",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "12",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(path),
    )


def probe(path: Path) -> dict:
    """Decode-count and return the exact picture/audio stream surface."""
    tool = resolve_tools()["ffprobe"]
    raw = run([
        tool, "-v", "error", "-count_frames", "-show_entries",
        "stream=codec_type,width,height,pix_fmt,r_frame_rate,"
        "nb_read_frames,sample_rate,channels", "-of", "json", str(path),
    ])
    streams = json.loads(raw).get("streams") or []
    video = next(row for row in streams if row["codec_type"] == "video")
    audio = next(
        (row for row in streams if row["codec_type"] == "audio"), None)
    rate = Fraction(video["r_frame_rate"])
    return {
        "width": int(video["width"]), "height": int(video["height"]),
        "pixelFormat": video["pix_fmt"],
        "frameRate": f"{rate.numerator}/{rate.denominator}",
        "decodedFrames": int(video["nb_read_frames"]),
        "audio": None if audio is None else {
            "sampleRate": int(audio["sample_rate"]),
            "channels": int(audio["channels"]),
        },
    }


def prove_decode(path: Path) -> dict:
    """Require a full picture+audio decode, not merely a successful probe."""
    tool = resolve_tools()["ffmpeg"]
    run([
        tool, "-nostdin", "-v", "error", "-xerror", "-i", str(path),
        "-map", "0:v:0", "-map", "0:a?", "-f", "null", "-",
    ])
    return probe(path)


def cache_media(directory: Path) -> dict[str, dict]:
    """Stable media-only cache inventory; locks and proofs are excluded."""
    rows = {}
    for path in sorted(directory.iterdir()):
        if path.suffix not in {".mov", ".mp4"}:
            continue
        rows[path.name] = {
            "sha256": file_hash(path),
            "sizeBytes": path.stat().st_size,
            "mtimeNs": str(path.stat().st_mtime_ns),
        }
    return rows


def _rgb_frame(path: Path, frame: int) -> tuple[int, int, bytes]:
    """Decode one exact frame; never infer artwork placement from container metadata."""
    facts = probe(path)
    width, height = facts["width"], facts["height"]
    tool = resolve_tools()["ffmpeg"]
    raw = run([
        tool, "-nostdin", "-v", "error", "-i", str(path),
        "-vf", f"select=eq(n\\,{frame})", "-vsync", "0",
        "-frames:v", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "-",
    ])
    expected = width * height * 3
    if len(raw) != expected:
        raise RuntimeError("pixel probe decoded the wrong frame size")
    return width, height, raw


def frame_green_border_fraction(path: Path, frame: int, border: int = 8) -> float:
    """Fraction of delivery-edge pixels still dominated by fixture green."""
    width, height, raw = _rgb_frame(path, frame)
    green = total = 0
    for y in range(height):
        edge_y = y < border or y >= height - border
        for x in range(width):
            if not edge_y and border <= x < width - border:
                continue
            offset = (y * width + x) * 3
            red, channel, blue = raw[offset:offset + 3]
            green += channel > red + 60 and channel > blue + 60
            total += 1
    return round(green / total, 9)


def _card_white_region(rgb: np.ndarray, scale: int) -> np.ndarray:
    """Isolate the card from the equally white opaque-video background.

    The authored shadow separates the card's settled white padding from the
    background. Flood from padding, outside both text lines, without clipping
    to the expected card bounds; a missing shadow or displaced card must fail.
    """
    white = (rgb.min(axis=2) >= 245) & (np.ptp(rgb, axis=2) <= 20)
    seed = (495 * scale, 770 * scale)
    if not white[seed[1], seed[0]]:
        return np.zeros(white.shape, dtype=bool)
    mask = Image.fromarray(white.astype(np.uint8) * 255).copy()
    ImageDraw.floodfill(mask, seed, 127)
    return np.asarray(mask) == 127


def frame_card_geometry(path: Path, frame: int, scale: int) -> dict:
    """Measure this explicit line-swap fixture's settled card and nonempty text.

    The shadow-separated white component must match the authored card bounds.
    Canvas-wide white, missing artwork and incorrect scaling fail independently.
    """
    width, height, raw = _rgb_frame(path, frame)
    rgb = np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 3)
    white = _card_white_region(rgb, scale)
    ys, xs = np.nonzero(white)
    if not xs.size:
        raise RuntimeError("line-swap settled frame has no neutral-white card")
    bbox = [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
    expected = [value * scale for value in (60, 751.5, 930, 958.5)]
    left, top, right, bottom = [round(value * scale) for value in (116, 795.5, 874, 914.5)]
    text = rgb[top:bottom, left:right]
    dark_fraction = float((text.max(axis=2) <= 80).mean())
    left, top, right, bottom = [round(value * scale) for value in (120, 765, 870, 780)]
    padding_fraction = float(white[top:bottom, left:right].mean())
    area_fraction = float(white.sum()) / (870 * 207 * scale * scale)
    bounds_ok = all(abs(actual - target) <= 3 * scale for actual, target in zip(bbox, expected))
    return {"frame": frame, "scale": scale, "whiteBBox": bbox,
            "whiteAreaFraction": round(area_fraction, 9),
            "paddingWhiteFraction": round(padding_fraction, 9),
            "textDarkFraction": round(dark_fraction, 9),
            "passed": bounds_ok and area_fraction >= 0.70 and padding_fraction >= 0.95
                      and 0.005 <= dark_fraction <= 0.30}


def changed_picture_frames(left: Path, right: Path) -> list[int]:
    """Indices whose fully decoded picture hash changed."""
    before = decoded_frame_hashes(str(left))
    after = decoded_frame_hashes(str(right))
    if len(before) != len(after):
        raise RuntimeError("picture comparison has different frame counts")
    return [index for index, pair in enumerate(zip(before, after))
            if pair[0] != pair[1]]


def packet_hash(path: Path) -> str:
    """SHA-256 of the encoded video elementary stream."""
    output = ffmpeg(
        "-i", str(path), "-map", "0:v:0", "-c", "copy",
        "-f", "hash", "-hash", "sha256", "-",
    ).decode().strip()
    if not output.startswith("SHA256="):
        raise RuntimeError("video packet hash returned no SHA-256")
    return output.partition("=")[2].lower()


def file_identity(path: Path) -> dict:
    return {
        "sha256": file_hash(path),
        "sizeBytes": path.stat().st_size,
        "mtimeNs": str(path.stat().st_mtime_ns),
    }


def source_closure(repo: Path, names: tuple[str, ...]) -> dict:
    return {name: file_hash(repo / name) for name in names}


def toolchain() -> dict:
    rows = {}
    for name, raw in sorted(resolve_tools().items()):
        path = Path(os.path.realpath(raw))
        rows[name] = {"path": str(path), "sha256": file_hash(path)}
    return rows


def write_canonical(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value) + b"\n")
