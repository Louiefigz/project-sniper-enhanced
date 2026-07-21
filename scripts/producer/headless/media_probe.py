"""Strict media facts measured from one stable, controller-owned artifact."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from dataclasses import dataclass
from fractions import Fraction

from .process_runner import ProcessRequest, run_text

_FPS = re.compile(r"[1-9][0-9]*/[1-9][0-9]*")
_MAX_ARTIFACT_BYTES = 16 * 1024 ** 3


class MediaProbeError(RuntimeError):
    """A media artifact or its measured ffprobe facts are not trustworthy."""


@dataclass(frozen=True)
class ProbeResultV1:
    """Neutral facts bound to the exact bytes read during the probe."""

    sha256: str
    size_bytes: int
    width: int
    height: int
    duration_seconds: float
    fps_numerator: int
    fps_denominator: int
    frame_count: int
    video_codec: str
    pixel_format: str
    profile: str
    audio_codec: str | None

    @property
    def fps(self) -> float:
        """Return the display rate without discarding its rational identity."""
        return self.fps_numerator / self.fps_denominator


@dataclass(frozen=True)
class _ArtifactSnapshot:
    digest: str
    size_bytes: int
    identity: tuple[int, ...]


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_uid,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _valid_artifact(info: os.stat_result) -> bool:
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and info.st_uid == os.geteuid()
            and 0 < info.st_size <= _MAX_ARTIFACT_BYTES)


def _open_artifact(path: str) -> int:
    canonical = (isinstance(path, str) and os.path.isabs(path)
                 and os.path.normpath(path) == path
                 and os.path.realpath(path) == path and "\0" not in path)
    if not canonical:
        raise MediaProbeError(
            "media artifact path must be canonical and absolute")
    flags = (os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
             | getattr(os, "O_NOFOLLOW", 0))
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise MediaProbeError(
            "media artifact could not be opened safely") from exc
    try:
        valid = _valid_artifact(os.fstat(fd))
    except BaseException:
        os.close(fd)
        raise
    if valid:
        return fd
    os.close(fd)
    raise MediaProbeError(
        "media artifact must be one owned single-link regular file")


def _hash_fd(fd: int) -> str:
    digest = hashlib.sha256()
    os.lseek(fd, 0, os.SEEK_SET)
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            return digest.hexdigest()
        digest.update(chunk)


def _path_identity(path: str) -> tuple[int, ...]:
    try:
        return _identity(os.stat(path, follow_symlinks=False))
    except OSError as exc:
        raise MediaProbeError(
            "media artifact path changed during validation") from exc


def _snapshot(fd: int, path: str) -> _ArtifactSnapshot:
    before = os.fstat(fd)
    if not _valid_artifact(before):
        raise MediaProbeError(
            "media artifact must be one owned single-link regular file")
    digest = _hash_fd(fd)
    after = os.fstat(fd)
    identity = _identity(before)
    if identity != _identity(after) or identity != _path_identity(path):
        raise MediaProbeError("media artifact changed while hashing")
    return _ArtifactSnapshot(digest, after.st_size, identity)


def _assert_unchanged(fd: int, path: str, expected: _ArtifactSnapshot) -> None:
    before = os.fstat(fd)
    if _identity(before) != expected.identity:
        raise MediaProbeError("media artifact changed during ffprobe")
    digest = _hash_fd(fd)
    after = os.fstat(fd)
    stable = (_identity(after) == expected.identity
              and _path_identity(path) == expected.identity
              and digest == expected.digest)
    if not stable:
        raise MediaProbeError("media artifact changed during ffprobe")


def artifact_sha256(path: str) -> str:
    """Hash one stable, owned, single-link regular artifact."""
    fd = _open_artifact(path)
    try:
        return _snapshot(fd, path).digest
    finally:
        os.close(fd)


def _probe_request(path: str, ffprobe: str, timeout: float) -> ProcessRequest:
    valid_tool = (isinstance(ffprobe, str) and os.path.isabs(ffprobe)
                  and os.path.normpath(ffprobe) == ffprobe
                  and not any(ord(char) < 32 for char in ffprobe))
    valid_timeout = (type(timeout) in {int, float} and math.isfinite(timeout)
                     and 0 < timeout <= 3600)
    if not valid_tool or not valid_timeout:
        raise MediaProbeError("ffprobe request is invalid")
    entries = ("format=duration",
               "stream=codec_type,codec_name,profile,pix_fmt,"
               "width,height,avg_frame_rate,nb_read_packets,duration")
    command = (ffprobe, "-v", "error", "-count_packets", "-show_entries",
               ":".join(entries), "-of", "json", path)
    return ProcessRequest(command, "", "/", {}, float(timeout))


def _run_probe(path: str, ffprobe: str,
               timeout: float) -> tuple[str, _ArtifactSnapshot]:
    fd = _open_artifact(path)
    try:
        expected = _snapshot(fd, path)
        try:
            completed = run_text(_probe_request(path, ffprobe, timeout))
        finally:
            _assert_unchanged(fd, path, expected)
    finally:
        os.close(fd)
    if completed.returncode != 0:
        detail = completed.stderr.strip()[-240:]
        raise MediaProbeError(f"ffprobe failed for media artifact: {detail}")
    return completed.stdout, expected


def _strict_text(value: object, label: str) -> str:
    valid = (isinstance(value, str) and 0 < len(value) <= 256
             and value.strip() == value
             and not any(ord(char) < 32 or ord(char) == 127
                         for char in value))
    if not valid:
        raise MediaProbeError(f"ffprobe {label} is invalid")
    return value


def _positive_float(value: object, label: str) -> float:
    try:
        parsed = float(_strict_text(value, label))
    except ValueError as exc:
        raise MediaProbeError(f"ffprobe {label} is invalid") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise MediaProbeError(f"ffprobe {label} is invalid")
    return parsed


def _frame_rate(value: object) -> tuple[int, int]:
    text = _strict_text(value, "average frame rate")
    parts = text.split("/")
    if (not _FPS.fullmatch(text) or len(parts) != 2
            or any(len(part) > 12 for part in parts)):
        raise MediaProbeError("ffprobe average frame rate is invalid")
    rate = Fraction(text)
    if not 0 < float(rate) <= 1000:
        raise MediaProbeError("ffprobe average frame rate is invalid")
    return rate.numerator, rate.denominator


def _frame_count(value: object) -> int:
    text = _strict_text(value, "packet frame count")
    if (len(text) > 20 or not text.isascii() or not text.isdecimal()
            or text.startswith("0")):
        raise MediaProbeError("ffprobe packet frame count is invalid")
    return int(text)


def _dimensions(video: dict) -> tuple[int, int]:
    width, height = video.get("width"), video.get("height")
    valid = (type(width) is int and type(height) is int
             and 0 < width <= 16384 and 0 < height <= 16384)
    if not valid:
        raise MediaProbeError("ffprobe video dimensions are invalid")
    return width, height


def _stream_set(value: object) -> tuple[dict, dict | None]:
    invalid = (not isinstance(value, list)
               or any(not isinstance(row, dict) for row in value))
    if invalid:
        raise MediaProbeError("ffprobe streams are invalid")
    videos = [row for row in value if row.get("codec_type") == "video"]
    audio = [row for row in value if row.get("codec_type") == "audio"]
    known = len(videos) + len(audio) == len(value)
    if len(videos) != 1 or len(audio) > 1 or not known:
        raise MediaProbeError(
            "media must contain exactly one video and at most one audio")
    return videos[0], audio[0] if audio else None


def _validate_duration(duration: float, video: dict,
                       rate: tuple[int, int], frames: int) -> None:
    expected = frames * rate[1] / rate[0]
    tolerance = max(rate[1] / rate[0] + 0.005, 0.04)
    if abs(duration - expected) > tolerance:
        raise MediaProbeError(
            "media duration, frame count, and fps are inconsistent")
    stream_duration = video.get("duration")
    if stream_duration is None:
        return
    measured = _positive_float(stream_duration, "video duration")
    if abs(duration - measured) > tolerance:
        raise MediaProbeError(
            "format and video stream durations are inconsistent")


def _parse_probe(raw: str, snapshot: _ArtifactSnapshot) -> ProbeResultV1:
    if not isinstance(raw, str) or len(raw) > 256 * 1024:
        raise MediaProbeError("ffprobe returned invalid JSON")
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise MediaProbeError("ffprobe returned invalid JSON") from exc
    valid = (isinstance(value, dict)
             and isinstance(value.get("format"), dict))
    if not valid:
        raise MediaProbeError("ffprobe result schema is invalid")
    video, audio = _stream_set(value.get("streams"))
    duration = _positive_float(value["format"].get("duration"), "duration")
    rate = _frame_rate(video.get("avg_frame_rate"))
    frames = _frame_count(video.get("nb_read_packets"))
    _validate_duration(duration, video, rate, frames)
    width, height = _dimensions(video)
    audio_codec = None if audio is None else _strict_text(
        audio.get("codec_name"), "audio codec")
    return ProbeResultV1(
        snapshot.digest, snapshot.size_bytes, width, height, duration,
        rate[0], rate[1], frames,
        _strict_text(video.get("codec_name"), "video codec"),
        _strict_text(video.get("pix_fmt"), "pixel format"),
        _strict_text(video.get("profile"), "video profile"), audio_codec)


def probe_media_artifact(path: str, ffprobe: str,
                         timeout_seconds: float = 30.0) -> ProbeResultV1:
    """Measure one exact artifact with a bounded, secret-free ffprobe call."""
    raw, snapshot = _run_probe(path, ffprobe, timeout_seconds)
    return _parse_probe(raw, snapshot)
