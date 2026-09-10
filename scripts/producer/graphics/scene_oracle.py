"""Decoded-frame, randomized-seek, and ordered-unit scene oracles."""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
from dataclasses import dataclass

from graphics.render_tools import resolve_tools
from graphics.scene_contract import SceneContractError, validate_scene

_FRAME_LINE = re.compile(
    r"^\d+,\s+\d+,\s+\d+,\s+\d+,\s+\d+,\s+([0-9a-fA-F]+)$")
_SSIM = re.compile(r"All:([0-9.]+)")


@dataclass(frozen=True)
class UnitMedia:
    """One rendered scene unit in explicit z-order."""

    unit_id: str
    z_index: int
    path: str


@dataclass(frozen=True)
class UnitOracleRequest:
    """Inputs for ordered unit-to-full-scene equivalence."""

    scene: dict
    full_scene_path: str
    units: tuple[UnitMedia, ...]
    output_path: str
    minimum_ssim: float = 0.995


def _run(command: list[str]) -> subprocess.CompletedProcess:
    result = subprocess.run(
        command, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()[-500:]
        raise SceneContractError(f"scene oracle command failed: {detail}")
    return result


def decoded_frame_hashes(path: str) -> tuple[str, ...]:
    """Hash every decoded frame; container bytes never substitute."""
    ffmpeg = resolve_tools()["ffmpeg"]
    command = [
        ffmpeg, "-nostdin", "-v", "error", "-i", path, "-map", "0:v:0",
        "-an", "-f", "framehash", "-hash", "sha256", "-",
    ]
    result = _run(command)
    hashes = []
    for line in result.stdout.splitlines():
        match = _FRAME_LINE.fullmatch(line.strip())
        if match:
            hashes.append(match.group(1).lower())
    if not hashes:
        raise SceneContractError("scene oracle decoded no frames")
    return tuple(hashes)


def assert_clean_render_match(first: str, second: str) -> dict:
    """Require every decoded frame from two clean renders to match exactly."""
    left = decoded_frame_hashes(first)
    right = decoded_frame_hashes(second)
    if left != right:
        mismatch = next((index for index, pair in enumerate(zip(left, right))
                         if pair[0] != pair[1]), min(len(left), len(right)))
        raise SceneContractError(
            f"clean scene renders diverge at decoded frame {mismatch}")
    sequence = hashlib.sha256("".join(left).encode("ascii")).hexdigest()
    return {"frameCount": len(left), "sequenceSha256": sequence}


def _single_frame_hash(path: str, frame: int) -> str:
    ffmpeg = resolve_tools()["ffmpeg"]
    select = f"select=eq(n\\,{frame})"
    command = [
        ffmpeg, "-nostdin", "-v", "error", "-i", path, "-vf", select,
        "-vsync", "0", "-frames:v", "1", "-an", "-f", "framehash",
        "-hash", "sha256", "-",
    ]
    result = _run(command)
    hashes = [match.group(1).lower() for line in result.stdout.splitlines()
              if (match := _FRAME_LINE.fullmatch(line.strip()))]
    if len(hashes) != 1:
        raise SceneContractError(f"randomized seek missed frame {frame}")
    return hashes[0]


def assert_random_seek_match(path: str, frames: tuple[int, ...]) -> dict:
    """Decode checkpoints in caller-supplied order and compare full sequence."""
    sequence = decoded_frame_hashes(path)
    checked = []
    for frame in frames:
        if type(frame) is not int or not 0 <= frame < len(sequence):
            raise SceneContractError(f"seek frame {frame!r} is outside the asset")
        if _single_frame_hash(path, frame) != sequence[frame]:
            raise SceneContractError(f"randomized seek changed decoded frame {frame}")
        checked.append(frame)
    return {"frameCount": len(sequence), "checkedFrames": checked}


def _duration(scene: dict) -> tuple[int, float, str]:
    timing = scene["timing"]
    frames = timing["endFrameExclusive"] - timing["startFrame"]
    numerator = int(timing["fps"]["numerator"])
    denominator = int(timing["fps"]["denominator"])
    return frames, frames * denominator / numerator, f"{numerator}/{denominator}"


def _ordered_units(request: UnitOracleRequest) -> tuple[UnitMedia, ...]:
    scene = validate_scene(request.scene)
    expected = [(row["unitId"], row["zIndex"])
                for row in sorted(scene["renderUnits"],
                                  key=lambda row: row["zIndex"])]
    actual = [(row.unit_id, row.z_index)
              for row in sorted(request.units, key=lambda row: row.z_index)]
    if actual != expected:
        raise SceneContractError("unit media does not match scene z-order")
    if any(not os.path.isfile(row.path) for row in request.units):
        raise SceneContractError("unit media is missing")
    return tuple(sorted(request.units, key=lambda row: row.z_index))


def _overlay_graph(unit_count: int) -> tuple[str, str]:
    previous = "[base]"
    parts = ["[0:v]format=rgba,colorchannelmixer=aa=0[base]"]
    for index in range(unit_count):
        output = f"[o{index}]"
        parts.append(
            f"{previous}[{index + 1}:v]overlay=0:0:format=auto:"
            f"eof_action=pass{output}")
        previous = output
    return ";".join(parts), previous


def _composite_units(request: UnitOracleRequest,
                     units: tuple[UnitMedia, ...]) -> None:
    ffmpeg = resolve_tools()["ffmpeg"]
    scene = validate_scene(request.scene)
    _, duration, rate = _duration(scene)
    width, height = scene["canvas"]["width"], scene["canvas"]["height"]
    source = f"color=c=black@0.0:s={width}x{height}:r={rate}:d={duration}"
    command = [ffmpeg, "-y", "-nostdin", "-v", "error",
               "-f", "lavfi", "-i", source]
    for unit in units:
        command.extend(("-i", unit.path))
    graph, output = _overlay_graph(len(units))
    command.extend((
        "-filter_complex", graph, "-map", output, "-an",
        "-c:v", "prores_ks", "-profile:v", "4",
        "-pix_fmt", "yuva444p10le", request.output_path,
    ))
    _run(command)


def _ssim(left: str, right: str, alpha: bool) -> float:
    ffmpeg = resolve_tools()["ffmpeg"]
    prefix = ("[0:v]alphaextract[a];[1:v]alphaextract[b];[a][b]"
              if alpha else "[0:v][1:v]")
    command = [
        ffmpeg, "-nostdin", "-v", "info", "-i", left, "-i", right,
        "-filter_complex", prefix + "ssim", "-an", "-f", "null", "-",
    ]
    result = _run(command)
    matches = _SSIM.findall(result.stderr)
    if not matches:
        raise SceneContractError("scene oracle produced no SSIM result")
    return float(matches[-1])


def prove_unit_equivalence(request: UnitOracleRequest) -> dict:
    """Composite ordered units and compare both color and alpha to full scene."""
    if not 0.9 <= request.minimum_ssim <= 1.0:
        raise SceneContractError("scene oracle SSIM threshold is invalid")
    units = _ordered_units(request)
    _composite_units(request, units)
    color = _ssim(request.full_scene_path, request.output_path, False)
    alpha = _ssim(request.full_scene_path, request.output_path, True)
    if min(color, alpha) < request.minimum_ssim:
        raise SceneContractError(
            f"ordered units differ from full scene: color={color}, alpha={alpha}")
    frames, _, _ = _duration(validate_scene(request.scene))
    return {"frameCount": frames, "colorSsim": color, "alphaSsim": alpha,
            "minimumSsim": request.minimum_ssim}
