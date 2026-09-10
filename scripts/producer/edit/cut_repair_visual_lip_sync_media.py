"""Pinned bounded media decoding for the visual lip-sync oracle."""
from __future__ import annotations

import array
import subprocess

from edit.cut_repair_visual_lip_sync_types import (
    DecodedEvidence,
    FrameSpan,
    OracleRequest,
    RegionPpm,
    SampleSpan,
    VisualLipSyncBlocker,
)


def _run(command: list[str], label: str) -> bytes:
    try:
        result = subprocess.run(
            command, stdin=subprocess.DEVNULL, capture_output=True,
            timeout=180, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VisualLipSyncBlocker(
            "VISUAL_ORACLE_DECODE_FAILED",
            f"{label} could not execute") from exc
    if result.returncode:
        detail = result.stderr.decode(
            "utf-8", errors="replace").strip()[-600:]
        raise VisualLipSyncBlocker(
            "VISUAL_ORACLE_DECODE_FAILED",
            f"{label} failed ({result.returncode}): {detail}")
    return result.stdout


def _crop(region: RegionPpm) -> str:
    terms = (
        f"iw*{region.width}/1000000",
        f"ih*{region.height}/1000000",
        f"iw*{region.x}/1000000",
        f"ih*{region.y}/1000000",
    )
    return "crop=" + ":".join(terms)


def _visual_filter(
    span: FrameSpan,
    region: RegionPpm,
    dimensions: tuple[int, int],
) -> str:
    select = (
        f"select=between(n\\,{span.first}\\,{span.end_exclusive - 1})")
    scale = f"scale={dimensions[0]}:{dimensions[1]}:flags=area"
    return ",".join((select, _crop(region), scale, "format=gray"))


def _frames(
    request: OracleRequest,
    path: str,
    span: FrameSpan,
    dimensions: tuple[int, int],
) -> tuple[bytes, ...]:
    payload = _run([
        request.tools.ffmpeg_path,
        "-nostdin", "-v", "error", "-xerror", "-i", path,
        "-vf", _visual_filter(
            span, request.selection.visual_region, dimensions),
        "-fps_mode", "passthrough", "-an", "-f", "rawvideo",
        "-pix_fmt", "gray", "-",
    ], "visual speech-region decode")
    frame_size = dimensions[0] * dimensions[1]
    expected = span.end_exclusive - span.first
    if len(payload) != expected * frame_size:
        raise VisualLipSyncBlocker(
            "VISUAL_ORACLE_UNMEASURABLE",
            "visual speech region did not decode the exact selected frame range")
    return tuple(
        payload[index:index + frame_size]
        for index in range(0, len(payload), frame_size))


def _pcm(
    ffmpeg: str,
    path: str,
    span: SampleSpan,
    analysis_rate: int,
) -> tuple[int, ...]:
    filters = (
        f"atrim=start_sample={span.start}:"
        f"end_sample={span.end_exclusive},asetpts=PTS-STARTPTS")
    payload = _run([
        ffmpeg, "-nostdin", "-v", "error", "-xerror", "-i", path,
        "-map", "0:a:0", "-vn", "-af", filters, "-ac", "1",
        "-ar", str(analysis_rate), "-c:a", "pcm_s16le", "-f", "s16le", "-",
    ], "selected speech PCM decode")
    if not payload or len(payload) % 2:
        raise VisualLipSyncBlocker(
            "VISUAL_ORACLE_UNMEASURABLE",
            "selected speech PCM was absent or malformed")
    values = array.array("h")
    values.frombytes(payload)
    if values.itemsize != 2:
        raise VisualLipSyncBlocker(
            "VISUAL_ORACLE_UNMEASURABLE",
            "host PCM representation is unsupported")
    return tuple(values)


def decode_evidence(request: OracleRequest, policy: dict) -> DecodedEvidence:
    """Decode the exact source/output ranges under the pinned FFmpeg runtime."""
    selection = request.selection
    dimensions = (
        policy["analysisFrameWidth"], policy["analysisFrameHeight"])
    source_frames = _frames(
        request, selection.source_path, selection.source_frames, dimensions)
    candidate_frames = _frames(
        request, request.candidate.path, selection.output_frames, dimensions)
    source_pcm = _pcm(
        request.tools.ffmpeg_path, selection.source_path,
        selection.source_samples, policy["analysisAudioRate"])
    candidate_pcm = _pcm(
        request.tools.ffmpeg_path, request.candidate.path,
        selection.output_samples, policy["analysisAudioRate"])
    return DecodedEvidence(
        source_frames, candidate_frames, source_pcm, candidate_pcm)
