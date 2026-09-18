"""Exact range predicates and source-picture handle conversion."""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from edit.exact_timing import (
    FrameRange,
    PositiveRational,
    SampleRange,
    ceil_fraction,
)
from edit.repair_impact import frame_window_at_seam


@dataclass(frozen=True)
class PictureDirtyGeometry:
    """Inputs needed to bound one picture-changing repair fragment."""

    total_frames: int
    seam_frame: int
    extension_frames: int
    extension_after_seam: bool
    reclaimed_frames: FrameRange
    max_dirty_frames: int


def overlaps_samples(left: SampleRange, right: SampleRange) -> bool:
    """Return whether two half-open sample ranges intersect."""
    return (
        left.start_sample < right.end_sample_exclusive
        and right.start_sample < left.end_sample_exclusive
    )


def contains_frames(outer: FrameRange, inner: FrameRange) -> bool:
    """Return whether a frame range completely contains another."""
    return (
        outer.start_frame <= inner.start_frame
        and outer.end_frame_exclusive >= inner.end_frame_exclusive
    )


def contains_samples(outer: SampleRange, inner: SampleRange) -> bool:
    """Return whether a sample range completely contains another."""
    return (
        outer.start_sample <= inner.start_sample
        and outer.end_sample_exclusive >= inner.end_sample_exclusive
    )


def source_video_frame_range(
    samples: SampleRange,
    source_rate: int,
    fps: PositiveRational,
) -> FrameRange:
    """Convert a source-audio handle to its enclosing source frame handle."""
    start = Fraction(samples.start_sample, source_rate) * fps.fraction
    end = Fraction(samples.end_sample_exclusive, source_rate) * fps.fraction
    return FrameRange(
        start.numerator // start.denominator,
        ceil_fraction(end),
    )


def picture_dirty_range(
    geometry: PictureDirtyGeometry,
) -> FrameRange | None:
    """Return the bounded union of inserted and reclaimed picture frames."""
    extension = frame_window_at_seam(
        geometry.total_frames,
        geometry.seam_frame,
        geometry.extension_frames,
        geometry.extension_after_seam,
    )
    if extension is None:
        return None
    dirty = FrameRange(
        min(extension.start_frame, geometry.reclaimed_frames.start_frame),
        max(
            extension.end_frame_exclusive,
            geometry.reclaimed_frames.end_frame_exclusive,
        ),
    )
    return dirty if dirty.length <= geometry.max_dirty_frames else None
