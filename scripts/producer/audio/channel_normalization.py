"""Content-bound dead-channel authority for every program-audio consumer."""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
from dataclasses import dataclass

from audio.channel_normalization_receipt import (
    ChannelReceiptError,
    decision,
    peak_token,
    seal_channel_receipt,
    verify_channel_receipt as _verify_channel_receipt,
)
from fingerprints import file_sha256

_PEAK_RE = re.compile(
    r"Peak level dB:\s*(-?(?:inf|\d+(?:\.\d+)?))", re.I)


class ChannelNormalizationError(RuntimeError):
    """A program source cannot be normalized with exact authority."""


@dataclass(frozen=True)
class ChannelTools:
    """Byte-pinned local media executables."""

    ffmpeg_path: str
    ffmpeg_sha256: str
    ffprobe_path: str
    ffprobe_sha256: str


@dataclass(frozen=True)
class ChannelRequest:
    """One immutable source plus an explicit audio selector."""

    source_path: str
    source_sha256: str
    selector: str
    tools: ChannelTools


@dataclass(frozen=True)
class SourceIdentity:
    """Cheap post-render drift fields for one already-hashed source."""

    device: int
    inode: int
    size: int
    modified_ns: int
    changed_ns: int


@dataclass(frozen=True)
class ChannelAuthority:
    """Verified normalization decision and its held source identity."""

    request: ChannelRequest
    identity: SourceIdentity
    receipt: dict[str, object]

    def filter_for(self, target: str) -> str:
        """Return the exact proved mono or stereo normalization filter."""
        if target not in {"mono", "stereo"}:
            raise ChannelNormalizationError(
                f"unsupported channel-normalization target {target!r}")
        return str(self.receipt["decision"][f"{target}Filter"])  # type: ignore[index]

    def assert_stable(self) -> None:
        """Reject a source pathname that drifted while a consumer ran."""
        if _identity(self.request.source_path) != self.identity:
            raise ChannelNormalizationError(
                "program audio source identity changed during normalization")


def _run(command: list[str], label: str) -> str:
    result = subprocess.run(
        command, text=True, capture_output=True, check=False)
    if result.returncode:
        detail = (result.stderr or result.stdout)[-1200:].strip()
        raise ChannelNormalizationError(f"{label} failed: {detail}")
    return result.stdout or result.stderr


def _identity(path: str) -> SourceIdentity:
    try:
        info = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise ChannelNormalizationError(
            f"program audio source is unreadable: {exc}") from exc
    if not os.path.isfile(path):
        raise ChannelNormalizationError(
            "program audio source must be a regular file")
    return SourceIdentity(
        info.st_dev, info.st_ino, info.st_size,
        info.st_mtime_ns, info.st_ctime_ns)


def _canonical_file(path: str, label: str) -> str:
    canonical = os.path.realpath(os.path.abspath(path))
    if not os.path.isfile(canonical):
        raise ChannelNormalizationError(
            f"{label} is not a readable regular file: {path}")
    return canonical


def system_channel_tools() -> ChannelTools:
    """Resolve the local FFmpeg pair; observation pins each binary once."""
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise ChannelNormalizationError(
            "channel normalization requires local ffmpeg and ffprobe")
    ffmpeg = _canonical_file(ffmpeg, "ffmpeg")
    ffprobe = _canonical_file(ffprobe, "ffprobe")
    return ChannelTools(ffmpeg, "", ffprobe, "")


def system_program_request(path: str) -> ChannelRequest:
    """Create first-audio authority for a direct/legacy program-media input."""
    source = _canonical_file(path, "program audio source")
    return ChannelRequest(source, "", "a:0", system_channel_tools())


def selected_stream_request(
    path: str,
    source_sha256: str,
    stream_index: int,
    tools: ChannelTools,
) -> ChannelRequest:
    """Create authority for one already-pinned global stream selector."""
    if type(stream_index) is not int or stream_index < 0:
        raise ChannelNormalizationError(
            "selected audio stream index must be non-negative")
    return ChannelRequest(
        _canonical_file(path, "selected program audio source"),
        source_sha256, f"stream:{stream_index}", tools)


def first_audio_request(
    path: str,
    source_sha256: str,
    tools: ChannelTools,
) -> ChannelRequest:
    """Create first-audio authority with caller-pinned source and tools."""
    return ChannelRequest(
        _canonical_file(path, "program audio source"),
        source_sha256, "a:0", tools)


def _validated_request(request: ChannelRequest) -> ChannelRequest:
    source = _canonical_file(request.source_path, "program audio source")
    source_hash = file_sha256(source)
    ffmpeg = _canonical_file(request.tools.ffmpeg_path, "ffmpeg")
    ffprobe = _canonical_file(request.tools.ffprobe_path, "ffprobe")
    ffmpeg_hash = file_sha256(ffmpeg)
    ffprobe_hash = file_sha256(ffprobe)
    tools = ChannelTools(
        ffmpeg, ffmpeg_hash, ffprobe, ffprobe_hash,
    )
    if request.source_sha256 and source_hash != request.source_sha256:
        raise ChannelNormalizationError("program audio source bytes drifted")
    if request.tools.ffmpeg_sha256 \
            and ffmpeg_hash != request.tools.ffmpeg_sha256:
        raise ChannelNormalizationError(
            "channel-normalization ffmpeg bytes drifted")
    if request.tools.ffprobe_sha256 \
            and ffprobe_hash != request.tools.ffprobe_sha256:
        raise ChannelNormalizationError(
            "channel-normalization ffprobe bytes drifted")
    if request.selector != "a:0" \
            and re.fullmatch(r"stream:[0-9]+", request.selector) is None:
        raise ChannelNormalizationError(
            "audio selector must be a:0 or stream:<index>")
    return ChannelRequest(
        source, source_hash, request.selector, tools)


def _streams(request: ChannelRequest) -> list[dict]:
    raw = _run([
        request.tools.ffprobe_path, "-v", "error", "-show_streams",
        "-of", "json", request.source_path,
    ], "channel stream probe")
    try:
        streams = json.loads(raw).get("streams")
    except (AttributeError, json.JSONDecodeError) as exc:
        raise ChannelNormalizationError(
            "channel stream probe returned malformed JSON") from exc
    if not isinstance(streams, list):
        raise ChannelNormalizationError(
            "channel stream probe returned malformed streams")
    return [row for row in streams if isinstance(row, dict)]


def _selected_stream(request: ChannelRequest) -> dict:
    streams = _streams(request)
    if request.selector == "a:0":
        matches = [row for row in streams if row.get("codec_type") == "audio"]
        if not matches:
            raise ChannelNormalizationError(
                "program source has no first audio stream")
        return matches[0]
    index = int(request.selector.split(":", 1)[1])
    matches = [row for row in streams if row.get("index") == index]
    if len(matches) != 1 or matches[0].get("codec_type") != "audio":
        raise ChannelNormalizationError(
            "selected program audio stream is not unique")
    return matches[0]


def _channel_peaks(request: ChannelRequest, stream_index: int) -> list[float]:
    output = _run([
        request.tools.ffmpeg_path, "-hide_banner", "-nostats",
        "-i", request.source_path, "-map", f"0:{stream_index}",
        "-af", "astats=metadata=0:reset=0", "-f", "null", "-",
    ], "channel peak observation")
    raw = _PEAK_RE.findall(output)
    values = [
        -math.inf if value.lower() == "-inf" else float(value)
        for value in raw
    ]
    return values[:-1] if len(values) > 1 else []


def observe_channel_authority(request: ChannelRequest) -> ChannelAuthority:
    """Probe one source and return a closed, content-bound normalization receipt."""
    request = _validated_request(request)
    identity = _identity(request.source_path)
    stream = _selected_stream(request)
    try:
        index = int(stream["index"])
        channels = int(stream["channels"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ChannelNormalizationError(
            "selected program audio stream shape is malformed") from exc
    peaks = _channel_peaks(request, index)
    if channels <= 0 or len(peaks) != channels:
        raise ChannelNormalizationError(
            "could not prove every selected audio channel peak")
    body = {
        "schemaVersion": 1,
        "kind": "channel-normalization-receipt",
        "source": {
            "path": request.source_path,
            "sha256": request.source_sha256,
            "sizeBytes": identity.size,
            "selector": request.selector,
            "selectedStreamIndex": index,
        },
        "stream": {
            "codec": stream.get("codec_name"),
            "sampleRate": int(stream.get("sample_rate", 0)),
            "channels": channels,
            "channelLayout": stream.get("channel_layout")
            or f"{channels}ch-unspecified",
            "peakDbfs": [peak_token(value) for value in peaks],
        },
        "decision": decision(channels, peaks),
        "tools": {
            "ffmpegPath": request.tools.ffmpeg_path,
            "ffmpegSha256": request.tools.ffmpeg_sha256,
            "ffprobePath": request.tools.ffprobe_path,
            "ffprobeSha256": request.tools.ffprobe_sha256,
            "peakFilter": "astats=metadata=0:reset=0",
        },
    }
    receipt = seal_channel_receipt(body)
    return ChannelAuthority(request, identity, receipt)


def verify_channel_receipt(value: object) -> dict:
    """Expose receipt verification through this runtime module's error type."""
    try:
        return _verify_channel_receipt(value)
    except ChannelReceiptError as exc:
        raise ChannelNormalizationError(
            str(exc)) from exc
