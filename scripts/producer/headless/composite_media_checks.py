"""Bounded, secret-free ffmpeg checks for a prebound composite candidate."""

from __future__ import annotations

import math
import os
import re
import stat
import subprocess
from dataclasses import dataclass

from .process_runner import ProcessRequest, run_text

_AUDIO_HASH = re.compile(r"0,a,SHA256=([0-9a-f]{64})")
_ALPHA_AVERAGE = re.compile(r"lavfi\.signalstats\.YAVG=([0-9]+(?:\.[0-9]+)?)")
_MAX_COVER_BYTES = 64 * 1024 * 1024
_STDERR_TAIL = 240


class CompositeMediaCheckError(RuntimeError):
    """A bounded media command or its claimed result was not trustworthy."""


@dataclass(frozen=True)
class MediaCommandConfig:
    """Closed runtime inputs shared by all compositor media checks."""

    ffmpeg_path: str
    working_directory: str
    timeout_seconds: float


@dataclass(frozen=True)
class AlphaOccupancyV1:
    """Independent decoded alpha-plane visibility evidence."""

    sampled_frames: int
    meaningful_frames: int
    peak_mean_alpha8: float
    mean_alpha8: float


def _absolute_path(value: object, label: str) -> str:
    valid = (
        isinstance(value, str)
        and value
        and "\0" not in value
        and os.path.isabs(value)
        and os.path.normpath(value) == value
    )
    if not valid:
        raise CompositeMediaCheckError(f"{label} must be an absolute normalized path")
    return value


def _validated_config(config: MediaCommandConfig) -> MediaCommandConfig:
    if not isinstance(config, MediaCommandConfig):
        raise CompositeMediaCheckError("media command config is invalid")
    _absolute_path(config.ffmpeg_path, "ffmpeg path")
    cwd = _absolute_path(config.working_directory, "working directory")
    timeout = config.timeout_seconds
    valid_timeout = (
        type(timeout) in {int, float} and math.isfinite(timeout) and 0 < timeout <= 3600
    )
    if not os.path.isdir(cwd) or not valid_timeout:
        raise CompositeMediaCheckError("media command config is invalid")
    return config


def _closed_environment() -> dict[str, str]:
    return {
        "AV_LOG_FORCE_NOCOLOR": "1",
        "LANG": "C",
        "LC_ALL": "C",
        "TZ": "UTC",
    }


def _arguments(value: tuple[str, ...]) -> tuple[str, ...]:
    valid = (
        isinstance(value, tuple)
        and value
        and all(isinstance(item, str) and item and "\0" not in item for item in value)
    )
    if not valid:
        raise CompositeMediaCheckError("ffmpeg arguments are invalid")
    return value


def _stderr_tail(stderr: object) -> str:
    text = stderr.strip() if isinstance(stderr, str) else ""
    return text[-_STDERR_TAIL:] if text else "<no stderr>"


def run_media_command(
    config: MediaCommandConfig, arguments: tuple[str, ...]
) -> subprocess.CompletedProcess:
    """Run one bounded ffmpeg command with no inherited environment or stdin."""
    checked = _validated_config(config)
    command = (checked.ffmpeg_path, "-hide_banner", "-nostdin", *_arguments(arguments))
    request = ProcessRequest(
        command,
        "",
        checked.working_directory,
        _closed_environment(),
        float(checked.timeout_seconds),
    )
    completed = run_text(request)
    if completed.returncode != 0:
        detail = _stderr_tail(completed.stderr)
        raise CompositeMediaCheckError(f"ffmpeg command failed: {detail}")
    return completed


def _parse_audio_hash(stdout: object) -> str:
    lines = stdout.splitlines() if isinstance(stdout, str) else []
    match = _AUDIO_HASH.fullmatch(lines[0]) if len(lines) == 1 else None
    if match is None:
        raise CompositeMediaCheckError(
            "ffmpeg must report exactly one canonical audio stream hash"
        )
    return match.group(1)


def audio_stream_sha256(path: str, config: MediaCommandConfig) -> str:
    """Hash the one encoded audio stream without decoding or transcoding it."""
    source = _absolute_path(path, "media path")
    arguments = (
        "-v",
        "error",
        "-i",
        source,
        "-map",
        "0:a",
        "-c:a",
        "copy",
        "-f",
        "streamhash",
        "-hash",
        "sha256",
        "-",
    )
    return _parse_audio_hash(run_media_command(config, arguments).stdout)


def preserved_audio_sha256(
    base_path: str, final_path: str, config: MediaCommandConfig
) -> str:
    """Require the final to retain the exact encoded base audio stream."""
    base_audio = audio_stream_sha256(base_path, config)
    final_audio = audio_stream_sha256(final_path, config)
    if base_audio != final_audio:
        raise CompositeMediaCheckError("candidate changed copied audio bytes")
    return base_audio


def alpha_occupancy(path: str, config: MediaCommandConfig) -> AlphaOccupancyV1:
    """Require sustained nonzero decoded alpha, independent of render claims."""
    source = _absolute_path(path, "alpha media path")
    filters = (
        "alphaextract,format=gray,scale=96:54:flags=area,fps=4,signalstats,"
        "metadata=print:key=lavfi.signalstats.YAVG:file=-"
    )
    arguments = ("-v", "error", "-i", source, "-vf", filters, "-an", "-f", "null", "-")
    output = run_media_command(config, arguments)
    lines = (output.stdout + output.stderr).splitlines()
    values = [
        float(match.group(1))
        for line in lines
        if (match := _ALPHA_AVERAGE.fullmatch(line.strip()))
    ]
    meaningful = [value for value in values if value >= 0.5]
    required = 1 if len(values) == 1 else max(2, math.ceil(len(values) * 0.2))
    if not values or len(meaningful) < required:
        raise CompositeMediaCheckError(
            "overlay has no sustained decoded alpha occupancy"
        )
    return AlphaOccupancyV1(
        len(values), len(meaningful), max(values), sum(values) / len(values)
    )


def _require_absent_output(path: str) -> str:
    output = _absolute_path(path, "pending cover path")
    parent = os.path.dirname(output)
    if not os.path.isdir(parent):
        raise CompositeMediaCheckError("pending cover parent must exist")
    try:
        os.lstat(output)
    except FileNotFoundError:
        return output
    raise CompositeMediaCheckError("pending cover must not already exist")


def _regular_output_size(path: str) -> int:
    flags = (
        os.O_RDONLY
        | os.O_NONBLOCK
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise CompositeMediaCheckError("pending cover is not a safe output") from exc
    try:
        info = os.fstat(fd)
        valid = (
            stat.S_ISREG(info.st_mode)
            and info.st_nlink == 1
            and info.st_uid == os.geteuid()
            and 0 < info.st_size <= _MAX_COVER_BYTES
        )
        if not valid:
            raise CompositeMediaCheckError(
                "pending cover must be one nonempty bounded regular file"
            )
        return info.st_size
    finally:
        os.close(fd)


def extract_frame_zero(
    final_path: str, pending_cover: str, config: MediaCommandConfig
) -> int:
    """Decode exactly video frame n=0 into one new PNG pending artifact."""
    source = _absolute_path(final_path, "final media path")
    output = _require_absent_output(pending_cover)
    if source == output or "%" in output:
        raise CompositeMediaCheckError("pending cover path is unsafe")
    arguments = (
        "-v",
        "error",
        "-i",
        source,
        "-map",
        "0:v:0",
        "-an",
        "-sn",
        "-dn",
        "-vf",
        r"select=eq(n\,0)",
        "-frames:v",
        "1",
        "-fps_mode",
        "passthrough",
        "-c:v",
        "png",
        "-f",
        "image2",
        "-n",
        output,
    )
    run_media_command(config, arguments)
    return _regular_output_size(output)


def full_decode_xerror(path: str, config: MediaCommandConfig) -> None:
    """Decode the complete primary video and every audio stream with xerror."""
    source = _absolute_path(path, "media path")
    arguments = (
        "-v",
        "error",
        "-xerror",
        "-i",
        source,
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-sn",
        "-dn",
        "-f",
        "null",
        "-",
    )
    run_media_command(config, arguments)
