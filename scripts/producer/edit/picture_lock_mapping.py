"""Exact outside-dirty mapping proof for P2 child picture locks."""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Sequence

from edit.exact_timing import FrameRange, SampleRange
from edit.picture_lock_common import (
    PictureLockError,
    content_hash,
    require_hash,
)


@dataclass(frozen=True)
class MappingSpan:
    """Exact linear source-sample mapping for one compiled frame span."""

    frames: FrameRange
    source_id: str
    source_samples: SampleRange

    def __post_init__(self) -> None:
        if not isinstance(self.source_id, str) or not self.source_id:
            raise PictureLockError("mapping span source identity is empty")

    @property
    def slope(self) -> Fraction:
        """Exact source samples per delivery frame."""
        return Fraction(self.source_samples.length, self.frames.length)

    def value_at(self, frame: int) -> Fraction:
        """Exact unrounded source-sample point at a frame boundary."""
        if not self.frames.start_frame <= frame <= self.frames.end_frame_exclusive:
            raise PictureLockError("mapping query is outside its span")
        return self.source_samples.start_sample + (
            frame - self.frames.start_frame) * self.slope


def _span_at(spans: Sequence[MappingSpan], frame: int) -> MappingSpan:
    hit = next((span for span in spans
                if span.frames.start_frame <= frame
                < span.frames.end_frame_exclusive), None)
    if hit is None:
        raise PictureLockError(f"compiled mapping has no owner for frame {frame}")
    return hit


def merged_frame_ranges(ranges: Sequence[FrameRange]) -> list[FrameRange]:
    """Merge overlapping/touching dirty windows deterministically."""
    merged: list[FrameRange] = []
    for item in sorted(ranges, key=lambda row: row.start_frame):
        if not merged or item.start_frame > merged[-1].end_frame_exclusive:
            merged.append(item)
            continue
        prior = merged[-1]
        merged[-1] = FrameRange(
            prior.start_frame,
            max(prior.end_frame_exclusive, item.end_frame_exclusive))
    return merged


def _unchanged_ranges(total_frames: int,
                      dirty: Sequence[FrameRange]) -> list[FrameRange]:
    if type(total_frames) is not int or total_frames <= 0:
        raise PictureLockError("mapping proof requires positive total frames")
    cursor = 0
    ranges: list[FrameRange] = []
    for item in merged_frame_ranges(dirty):
        if item.end_frame_exclusive > total_frames:
            raise PictureLockError("dirty window exceeds the timeline")
        if item.start_frame > cursor:
            ranges.append(FrameRange(cursor, item.start_frame))
        cursor = max(cursor, item.end_frame_exclusive)
    if cursor < total_frames:
        ranges.append(FrameRange(cursor, total_frames))
    return ranges


def _descriptor(span: MappingSpan, start: int) -> tuple[object, ...]:
    value = span.value_at(start)
    return (
        span.source_id,
        value.numerator, value.denominator,
        span.slope.numerator, span.slope.denominator,
    )


def _validate_spans(spans: Sequence[MappingSpan], total: int,
                    label: str) -> None:
    ordered = sorted(spans, key=lambda row: row.frames.start_frame)
    if not ordered or ordered[0].frames.start_frame != 0 \
            or ordered[-1].frames.end_frame_exclusive != total:
        raise PictureLockError(f"{label} mapping does not cover the timeline")
    for previous, current in zip(ordered, ordered[1:]):
        if previous.frames.end_frame_exclusive \
                != current.frames.start_frame:
            raise PictureLockError(f"{label} mapping has a gap or overlap")


@dataclass(frozen=True)
class MappingProofInput:
    """Parent/child compiled maps and the only authorized dirty windows."""

    parent_timeline_map_hash: str
    child_timeline_map_hash: str
    parent: tuple[MappingSpan, ...]
    child: tuple[MappingSpan, ...]
    dirty_windows: tuple[FrameRange, ...]
    total_frames: int


def _breakpoints(
    item: MappingProofInput,
    interval: FrameRange,
) -> list[int]:
    points = {interval.start_frame, interval.end_frame_exclusive}
    for span in (*item.parent, *item.child):
        if interval.start_frame < span.frames.start_frame \
                < interval.end_frame_exclusive:
            points.add(span.frames.start_frame)
        if interval.start_frame < span.frames.end_frame_exclusive \
                < interval.end_frame_exclusive:
            points.add(span.frames.end_frame_exclusive)
    return sorted(points)


def _interval_proof(
    item: MappingProofInput,
    interval: FrameRange,
) -> list[dict[str, object]]:
    rows = []
    points = _breakpoints(item, interval)
    for start, end in zip(points, points[1:]):
        parent = _span_at(item.parent, start)
        child = _span_at(item.child, start)
        if _descriptor(parent, start) != _descriptor(child, start):
            raise PictureLockError(
                f"source mapping changed outside dirty windows at frame {start}")
        rows.append({"frameRange": FrameRange(start, end).to_dict(),
                     "mapping": list(_descriptor(parent, start))})
    return rows


def _proof_rows(item: MappingProofInput,
                unchanged: Sequence[FrameRange]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for interval in unchanged:
        rows.extend(_interval_proof(item, interval))
    return rows


def prove_unchanged_mapping(item: MappingProofInput) -> tuple[dict, str]:
    """Prove exact source mapping outside the authorized dependency closure."""
    _validate_spans(item.parent, item.total_frames, "parent")
    _validate_spans(item.child, item.total_frames, "child")
    unchanged = _unchanged_ranges(item.total_frames, item.dirty_windows)
    if not unchanged:
        raise PictureLockError("dirty windows consume the complete timeline")
    payload = {
        "schemaVersion": 1,
        "parentTimelineMapHash": require_hash(
            item.parent_timeline_map_hash, "parent timeline map hash"),
        "childTimelineMapHash": require_hash(
            item.child_timeline_map_hash, "child timeline map hash"),
        "authorizedDirtyWindows": [
            row.to_dict() for row in merged_frame_ranges(item.dirty_windows)],
        "unchangedRanges": _proof_rows(item, unchanged),
    }
    return payload, content_hash(payload)
