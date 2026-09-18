"""Bounded supplied planar float32 counters; no decode or color authority."""
from __future__ import annotations

import numpy as np

MAX_CHUNK_BYTES = 1024 * 1024
_COUNTS = ("finiteCount", "nanCount", "positiveInfinityCount", "negativeInfinityCount",
           "belowZeroCount", "aboveOneCount")


def empty_channels() -> dict:
    """Create independent constant-space counters for physical G, B, R planes."""
    return {channel: {**dict.fromkeys(_COUNTS, 0), "minimum": None, "maximum": None}
            for channel in ("g", "b", "r")}


def _accumulate(row: dict, values: np.ndarray) -> None:
    """Classify a bounded view without per-pixel Python or nonfinite extrema."""
    finite = np.isfinite(values)
    count = int(np.count_nonzero(finite))
    row["finiteCount"] += count
    observed = values
    if count != values.size:
        row["nanCount"] += int(np.count_nonzero(np.isnan(values)))
        row["positiveInfinityCount"] += int(np.count_nonzero(np.isposinf(values)))
        row["negativeInfinityCount"] += int(np.count_nonzero(np.isneginf(values)))
        observed = values[finite]
    if not observed.size:
        return
    row["belowZeroCount"] += int(np.count_nonzero(observed < 0))
    row["aboveOneCount"] += int(np.count_nonzero(observed > 1))
    low, high = float(np.min(observed)), float(np.max(observed))
    # Signed zero is the same range endpoint; only the raw payload hash keeps its bit.
    low, high = (0.0 if value == 0 else value for value in (low, high))
    row["minimum"] = low if row["minimum"] is None else min(row["minimum"], low)
    row["maximum"] = high if row["maximum"] is None else max(row["maximum"], high)


class PlanarSamples:
    """Consume one explicit frame in G/B/R order with at most three carry bytes."""

    def __init__(self, pixels: int, channels: dict) -> None:
        """Borrow aggregate counters for one explicitly sized synthetic byte frame."""
        self.pixels = pixels
        self.channels = channels
        self.bytes = 0
        self.samples = 0
        self.carry = b""

    def push(self, chunk: bytes) -> None:
        """Keep only bounded temporary views; never retain the supplied payload."""
        if type(chunk) is not bytes or not 1 <= len(chunk) <= MAX_CHUNK_BYTES:
            raise ValueError("gamut payload needs immutable bytes within the chunk bound")
        if self.bytes + len(chunk) > self.pixels * 12:
            raise ValueError("gamut frame has extra payload bytes")
        data = self.carry + chunk
        aligned = len(data) - len(data) % 4
        self.carry = data[aligned:]
        values = np.frombuffer(data, dtype="<f4", count=aligned // 4)
        self._planes(values)
        self.bytes += len(chunk)

    def _planes(self, values: np.ndarray) -> None:
        """Split views at native plane boundaries even when a chunk crosses them."""
        offset = 0
        while offset < values.size:
            plane = self.samples // self.pixels
            count = min(values.size - offset, self.pixels - self.samples % self.pixels)
            _accumulate(self.channels[("g", "b", "r")[plane]], values[offset:offset + count])
            offset += count
            self.samples += count

    def finish(self) -> None:
        """Require complete planes, not merely a rounded float sample count."""
        if self.carry or self.bytes != self.pixels * 12 or self.samples != self.pixels * 3:
            raise ValueError("gamut frame payload is truncated")
