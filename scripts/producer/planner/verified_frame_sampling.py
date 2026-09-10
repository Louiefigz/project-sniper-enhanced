"""Bind placement probes to displayed PTS, not arbitrary wall-clock seeks.

The current graphics/b-roll/card FFmpeg overlays use inclusive ``between``
expressions with four/six/four decimal places respectively. This contract is
for that compositor only, not the separate frame-based title-card shard lane.
Packet indexing is lazy and scoped to one verification run. Selected frames
still have to decode at the requested timestamp; packet metadata is not QC.
"""
from __future__ import annotations

import json
import math
import subprocess
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Iterator


_SELECTED: ContextVar[tuple[str, tuple[float, ...]] | None] = ContextVar(
    "placement_frame_samples", default=None)


def frame_timestamps(video: str) -> tuple[float, ...]:
    """Index presentation times without decoding every full-resolution frame."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_packets",
         "-show_entries", "stream=time_base:packet=pts", "-of", "json", video],
        capture_output=True, text=True, check=True, timeout=30)
    payload = json.loads(result.stdout)
    try:
        scale = Fraction(payload["streams"][0]["time_base"])
        stamps = tuple(sorted(float(int(row["pts"]) * scale)
                              for row in payload["packets"]))
    except (KeyError, IndexError, TypeError, ZeroDivisionError) as exc:
        raise ValueError("video has no usable presentation-time index") from exc
    if not stamps or len(set(stamps)) != len(stamps):
        raise ValueError("video has missing or duplicate presentation timestamps")
    if any(not math.isfinite(stamp) for stamp in stamps) or scale <= 0:
        raise ValueError("video has invalid presentation timestamps")
    return stamps


def _covered(stamp: float, occlusions: dict) -> bool:
    """Apply the exact current compositor's serialized inclusive windows."""
    for key, precision in (("broll", 6), ("cards", 4)):
        for start, end in occlusions.get(key, []):
            if float(f"{start:.{precision}f}") <= stamp <= float(f"{end:.{precision}f}"):
                return True
    return False


@dataclass
class FrameIndex:
    """A disposable index shared by all placement spans in one output pass."""

    video: str
    _timestamps: tuple[float, ...] | None = field(default=None, init=False)
    _error: Exception | None = field(default=None, init=False)

    def _read(self) -> tuple[float, ...]:
        """Retry an unavailable index only in a new verification pass."""
        if self._error is not None:
            raise self._error
        if self._timestamps is not None:
            return self._timestamps
        try:
            self._timestamps = frame_timestamps(self.video)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            self._error = exc
            raise
        return self._timestamps

    def samples(self, window: tuple[float, float], occlusions: dict,
                limit: int) -> tuple[float, ...]:
        """Select distinct visible PTS, retaining the first and last frame."""
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 2:
            raise ValueError("placement sampling limit must be an integer of at least two")
        eligible = [stamp for stamp in self._read()
                    if window[0] <= stamp <= window[1] and not _covered(stamp, occlusions)]
        if len(eligible) <= limit:
            return tuple(eligible)
        indices = {round(i * (len(eligible) - 1) / (limit - 1)) for i in range(limit)}
        return tuple(eligible[i] for i in sorted(indices))


@contextmanager
def selected_frame_samples(video: str, stamps: tuple[float, ...]) -> Iterator[None]:
    """Limit only this synchronous geometry probe to its selected PTS."""
    token = _SELECTED.set((video, stamps))
    try:
        yield
    finally:
        _SELECTED.reset(token)


def current_frame_samples(video: str) -> tuple[float, ...] | None:
    """Leave ordinary planner sampling unchanged outside a verified probe."""
    selected = _SELECTED.get()
    return selected[1] if selected is not None and selected[0] == video else None
