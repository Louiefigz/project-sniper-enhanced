"""Bounded held inputs for an executed pre-encode compositor-prefix oracle.

This contract carries no cut/source/approval authority. The caller must obtain
the actual resolved graphs and separately held hashes from its owned execution.
"""
from __future__ import annotations

import hashlib
import math
import os
import stat
import time
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import TYPE_CHECKING

from cross_runtime_canonical_json import canonical_compact_json
from cut_preview_io import real_directory

if TYPE_CHECKING:
    from opening_prefix_presenter import PrefixPresenterGraphs

MAX_INPUT_BYTES = 8 * 1024 ** 3
MAX_AGGREGATE_BYTES = 32 * 1024 ** 3
MAX_CLIPS = 512
MAX_GRAPH_BYTES = 512 * 1024
MAX_REVIEW_FRAMES = 7200
GRAPH_WORKLOAD_POLICY = {"version": 1, "kind": "preencode-oracle-native-input-workload",
    "maxInputSide": 4096, "maxInputPixels": 4096 * 2160,
    "maxGraphInputPixels": 64 * 1024 * 1024,
    "scope": "conservative-verifier-admission-not-quality-or-fixed-RSS"}


@dataclass(frozen=True)
class HeldPrefixInput:
    """Exact regular-file identity independently held by the calling execution."""

    path: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class PrefixClock:
    """Exact expected whole-base clock and source-aspect canvas."""

    frame_rate: str
    total_frames: int
    width: int
    height: int


@dataclass(frozen=True)
class PrefixRanges:
    """Absolute half-open output frames; review contains core."""

    core: tuple[int, int]
    review: tuple[int, int]


@dataclass(frozen=True)
class CompositorPrefixRequest:
    """Actual full and opening graph inputs, never reconstructed plan guesses."""

    base: HeldPrefixInput
    assets: tuple[HeldPrefixInput, ...]
    full_clips: tuple[dict, ...]
    opening_clips: tuple[dict, ...]
    clock: PrefixClock
    ranges: PrefixRanges
    caption_tail: tuple[int, int] | None = None
    presenter: PrefixPresenterGraphs | None = None


@dataclass(frozen=True)
class PrefixOracleRuntime:
    """Held tools plus remaining original caller allowance, not a new job budget."""

    ffmpeg: HeldPrefixInput
    ffprobe: HeldPrefixInput
    working_directory: str
    timeout_seconds: float


class PrefixOracleError(RuntimeError):
    """The exact executed graph prefix could not be proved."""


class PrefixDeadline:
    """One decreasing local deadline including hashes, probes, graphs and rechecks."""

    def __init__(self, seconds: float) -> None:
        if type(seconds) not in {int, float} or not math.isfinite(seconds) or not 0 < seconds <= 900:
            raise PrefixOracleError("prefix oracle requires 0 < remaining timeout <= 900 seconds")
        self.started = time.monotonic()
        self.end = self.started + seconds

    def remaining(self) -> float:
        """Fail before any next operation after the original allowance expires."""
        value = self.end - time.monotonic()
        if value <= 0:
            raise PrefixOracleError("prefix oracle exhausted the supplied remaining deadline")
        return value


def canonical_hash(value: object) -> str:
    """Hash the exact JSON graph projection, including supplied metadata."""
    return hashlib.sha256(canonical_compact_json(value).encode()).hexdigest()


def _identity(info: os.stat_result) -> tuple:
    """Link complete source/tool stat identity to the bytes just hashed."""
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _valid_file(row: HeldPrefixInput) -> Path:
    if not isinstance(row, HeldPrefixInput) or type(row.path) is not str \
            or not row.path or len(row.path) > 4096 or any(ord(char) < 32 for char in row.path):
        raise PrefixOracleError("prefix input path is malformed")
    path = Path(row.path)
    if str(path) != row.path or not path.is_absolute() or type(row.size_bytes) is not int \
            or not 0 < row.size_bytes <= MAX_INPUT_BYTES or type(row.sha256) is not str \
            or len(row.sha256) != 64 or any(char not in "0123456789abcdef" for char in row.sha256):
        raise PrefixOracleError("prefix input identity is malformed or exceeds its byte limit")
    real_directory(path.parent)
    return path


def verify_held_input(row: HeldPrefixInput, deadline: PrefixDeadline) -> tuple:
    """Stream bounded no-follow bytes with per-chunk deadline and inode checks."""
    deadline.remaining()
    path = _valid_file(row)
    handle = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(handle)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size != row.size_bytes:
            raise PrefixOracleError("prefix input is not the held regular single-link file")
        value = _hash_chunks(handle, before.st_size, deadline)
        if _identity(before) != _identity(os.fstat(handle)) or _identity(before) != _identity(path.lstat()) \
                or value != row.sha256:
            raise PrefixOracleError("prefix input bytes or file identity changed")
    finally:
        os.close(handle)
    deadline.remaining()
    return _identity(before)


def _hash_chunks(handle: int, remaining: int, deadline: PrefixDeadline) -> str:
    """Keep reads small and cancellation responsive even for a long-form base."""
    value = hashlib.sha256()
    while remaining:
        deadline.remaining()
        chunk = os.read(handle, min(remaining, 1024 * 1024))
        if not chunk:
            raise PrefixOracleError("prefix input truncated during hashing")
        value.update(chunk)
        remaining -= len(chunk)
    return value.hexdigest()


def _range(value: tuple[int, int], total: int) -> None:
    if type(value) is not tuple or len(value) != 2 or any(type(item) is not int for item in value) \
            or not 0 <= value[0] < value[1] <= total:
        raise PrefixOracleError("prefix range is not an exact bounded half-open frame interval")


def _clock(clock: PrefixClock, ranges: PrefixRanges) -> None:
    if not isinstance(clock, PrefixClock) or type(clock.frame_rate) is not str:
        raise PrefixOracleError("prefix clock is malformed")
    try:
        rate = Fraction(clock.frame_rate)
    except (ValueError, ZeroDivisionError) as error:
        raise PrefixOracleError("prefix frame rate is malformed") from error
    integers = (clock.total_frames, clock.width, clock.height)
    if not 0 < rate <= 60 or any(type(value) is not int or value <= 0 for value in integers) \
            or clock.total_frames > 432000 or max(clock.width, clock.height) > 4096 \
            or clock.width * clock.height > 4096 * 2160 or clock.width % 2 or clock.height % 2:
        raise PrefixOracleError("prefix clock/canvas exceeds the declared mechanical workload")
    if not isinstance(ranges, PrefixRanges):
        raise PrefixOracleError("prefix ranges are malformed")
    _range(ranges.core, clock.total_frames)
    _range(ranges.review, clock.total_frames)
    if ranges.review[0] > ranges.core[0] or ranges.review[1] < ranges.core[1] \
            or ranges.review[1] > MAX_REVIEW_FRAMES or Fraction(ranges.review[1], 1) / rate > 120:
        raise PrefixOracleError("prefix review must contain core and end within 120 seconds/7200 frames")


def _integer_vector(value: object, count: int) -> bool:
    return type(value) in {tuple, list} and len(value) == count \
        and all(type(item) is int and -16384 <= item <= 16384 for item in value)


def _clip(row: dict, paths: set[str], total: int) -> None:
    if type(row) is not dict or type(row.get("path")) is not str or row["path"] not in paths:
        raise PrefixOracleError("prefix graph references an unheld graphic")
    _range((row.get("startFrame"), row.get("endFrameExclusive")), total)
    times = (row.get("outStart"), row.get("outEnd"))
    if any(type(value) not in {int, float} or not math.isfinite(value) for value in times) \
            or not 0 <= times[0] < times[1] <= 432000:
        raise PrefixOracleError("prefix graph has malformed original animation timing")
    if any(type(row.get(key, 0)) is not int or abs(row.get(key, 0)) > 16384 for key in ("x", "y")):
        raise PrefixOracleError("prefix graph placement is malformed")
    if row.get("scaleDims") and (not _integer_vector(row["scaleDims"], 2)
            or not valid_canvas(*row["scaleDims"])):
        raise PrefixOracleError("prefix graph scale is malformed")
    _hole(row.get("pipHole"))


def _hole(value: object) -> None:
    if not value:
        return
    if type(value) is not dict or set(value) != {"crop", "rect"} \
            or not _integer_vector(value["crop"], 4) or not _integer_vector(value["rect"], 4):
        raise PrefixOracleError("prefix graph PiP geometry is malformed")
    if not valid_canvas(*value["crop"][:2]) or not valid_canvas(*value["rect"][2:]):
        raise PrefixOracleError("prefix graph PiP surfaces exceed verifier workload")


def valid_canvas(width: object, height: object) -> bool:
    """Native/derived surface bound, not a promise about actual process RSS."""
    return all(type(value) is int and 0 < value <= 4096 for value in (width, height)) \
        and width * height <= GRAPH_WORKLOAD_POLICY["maxInputPixels"]


def validate_request(request: CompositorPrefixRequest, runtime: PrefixOracleRuntime) -> tuple[HeldPrefixInput, ...]:
    """Reject unsupported work before hashing or spawning; never silently narrow graphs."""
    from opening_prefix_presenter import validate_presenter_request
    if not isinstance(request, CompositorPrefixRequest) or not isinstance(runtime, PrefixOracleRuntime):
        raise PrefixOracleError("prefix oracle requires its typed closed request/runtime")
    _clock(request.clock, request.ranges)
    if type(request.assets) is not tuple or len(request.assets) > MAX_CLIPS:
        raise PrefixOracleError("prefix graphic inventory is malformed or too large")
    if any(type(graph) is not tuple or len(graph) > MAX_CLIPS for graph in (request.full_clips, request.opening_clips)):
        raise PrefixOracleError("prefix graph exceeds its bounded clip count")
    presentation = validate_presenter_request(request)
    rows = (request.base, *request.assets, *presentation, runtime.ffmpeg, runtime.ffprobe)
    for row in rows:
        _valid_file(row)
    if sum(row.size_bytes for row in rows) > MAX_AGGREGATE_BYTES:
        raise PrefixOracleError("prefix aggregate held input bytes exceed 32 GiB")
    paths = {row.path for row in request.assets}
    all_paths = paths | {row.path for row in presentation}
    if len(all_paths) != len(request.assets) + len(presentation) or request.base.path in all_paths \
            or len(all_paths) > MAX_CLIPS:
        raise PrefixOracleError("prefix asset inventory is duplicated or aliases its base")
    used = _graphs(request, paths)
    validate_caption_tail(request)
    if used != paths:
        raise PrefixOracleError("prefix inventory contains unconsumed graphics")
    real_directory(Path(runtime.working_directory))
    return rows


def validate_caption_tail(request: CompositorPrefixRequest) -> None:
    """An opt-in tail belongs to each exact combined graph, never inferred roles."""
    from graphics.composite_core import validate_caption_tails
    try:
        validate_caption_tails((request.full_clips, request.opening_clips), request.caption_tail)
    except (ValueError, KeyError, TypeError) as error:
        raise PrefixOracleError("prefix caption-tail graph is malformed") from error


def _graphs(request: CompositorPrefixRequest, paths: set[str]) -> set[str]:
    """Bound every original graphic plus the complete opt-in presenter projection."""
    from opening_prefix_graphs import bounded_graph_json, graph_projection
    used = set()
    for graph in (request.full_clips, request.opening_clips):
        if type(graph) is not tuple or len(graph) > MAX_CLIPS:
            raise PrefixOracleError("prefix graph exceeds its bounded clip count")
        for row in graph:
            _clip(row, paths, request.clock.total_frames)
            used.add(row["path"])
    try:
        values = [graph_projection(request, role) for role in ("full", "opening")]
        bounded_graph_json(values)
    except (TypeError, ValueError, RecursionError) as error:
        raise PrefixOracleError("prefix graph is not bounded finite JSON") from error
    return used
