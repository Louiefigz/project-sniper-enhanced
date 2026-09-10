"""Deterministic dependent-impact partitions for local and ripple repairs."""
from __future__ import annotations

from typing import Sequence

from edit.exact_timing import FrameRange, SampleRange
from edit.non_ripple_contracts import (
    DependentTiming,
    RemovableSilence,
    RepairContext,
)


def _overlaps(left: FrameRange, right: FrameRange) -> bool:
    return (left.start_frame < right.end_frame_exclusive
            and right.start_frame < left.end_frame_exclusive)


def dependency_partition(
    dependents: Sequence[DependentTiming],
    dirty_windows: Sequence[FrameRange],
) -> dict[str, list[str]]:
    """Partition stable IDs into conservative revalidation and unchanged sets."""
    revalidated: list[str] = []
    unchanged: list[str] = []
    for item in sorted(dependents, key=lambda row: row.stable_id):
        target = (revalidated if any(
            _overlaps(item.frames, window) for window in dirty_windows)
                  else unchanged)
        target.append(item.stable_id)
    return {
        "revalidatedDependentIds": revalidated,
        "unchangedDependentIds": unchanged,
    }


def frame_window_at_seam(
    total_frames: int,
    seam_frame: int,
    frames: int,
    leading: bool,
) -> FrameRange | None:
    """Return a bounded whole-frame window before or after one seam."""
    start, end = ((seam_frame - frames, seam_frame) if leading
                  else (seam_frame, seam_frame + frames))
    if start < 0 or end > total_frames:
        return None
    return FrameRange(start, end)


def audio_sample_window(
    context: RepairContext,
    seam_frame: int,
    samples: int,
    leading: bool,
) -> SampleRange | None:
    """Return one exact bounded project-clock L/J handle."""
    seam = context.clock.sample_at_frame(seam_frame)
    start, end = ((seam - samples, seam) if leading
                  else (seam, seam + samples))
    total = context.clock.sample_at_frame(context.total_frames)
    if start < 0 or end > total:
        return None
    return SampleRange(start, end)


def unchanged_frame_ranges(
    total_frames: int,
    dirty: FrameRange | None,
) -> list[dict[str, int]]:
    """Return the exact half-open complement of one local dirty window."""
    if dirty is None:
        return [FrameRange(0, total_frames).to_dict()]
    ranges: list[dict[str, int]] = []
    if dirty.start_frame:
        ranges.append(FrameRange(0, dirty.start_frame).to_dict())
    if dirty.end_frame_exclusive < total_frames:
        ranges.append(FrameRange(
            dirty.end_frame_exclusive, total_frames).to_dict())
    return ranges


def reclaimed_silence_residual(
    context: RepairContext,
    silence: RemovableSilence,
    extension_samples: int,
) -> int | None:
    """Return proved room-tone residual, or reject an undersized allocation."""
    allocation = context.clock.samples_for_frames(silence.output_frames).length
    residual = allocation - extension_samples
    return residual if residual >= 0 else None


def ripple_dependents(
    dependents: Sequence[DependentTiming],
    seam_frame: int,
    shift_frames: int,
) -> dict[str, object]:
    """Return exact output movement/invalidations for one proposed ripple."""
    moved: list[dict[str, object]] = []
    output_locked: list[str] = []
    invalidated: list[str] = []
    for item in sorted(dependents, key=lambda row: row.stable_id):
        if item.anchor_type == "output-locked":
            output_locked.append(item.stable_id)
            continue
        if item.frames.start_frame >= seam_frame:
            moved.append({
                "stableId": item.stable_id,
                "elementKind": item.element_kind,
                "from": item.frames.to_dict(),
                "to": FrameRange(
                    item.frames.start_frame + shift_frames,
                    item.frames.end_frame_exclusive + shift_frames).to_dict(),
            })
            continue
        if item.frames.end_frame_exclusive > seam_frame:
            invalidated.append(item.stable_id)
    return {
        "movedDependents": moved,
        "invalidatedDependents": invalidated,
        "unchangedOutputLockedIds": output_locked,
    }
