"""Closed data contracts consumed by the P2 non-ripple enumerator."""
from __future__ import annotations

from dataclasses import dataclass

from edit.exact_timing import (
    FrameRange,
    PositiveRational,
    ProjectClock,
    SampleRange,
)
from edit.target_resolver import ResolvedWordRange


class RepairContractError(ValueError):
    """P2 repair inputs cannot support a trustworthy analysis."""


def _is_hash(value: str) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


@dataclass(frozen=True)
class CompiledCutSegment:
    """Compiler-resolved segment identity and exact handle bounds."""

    segment_id: str
    element_version: int
    source_id: str
    source_rate: int
    source_samples: SampleRange
    output_frames: FrameRange
    speed: PositiveRational
    source_fps: PositiveRational | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.segment_id, str) or not self.segment_id \
                or not isinstance(self.source_id, str) or not self.source_id \
                or type(self.element_version) is not int \
                or type(self.source_rate) is not int \
                or self.element_version <= 0 or self.source_rate <= 0:
            raise RepairContractError("compiled segment identity/rate is invalid")


@dataclass(frozen=True)
class RemovableSilence:
    """Compiler/VAD-proved silence unit already aligned to delivery frames."""

    silence_id: str
    segment_id: str
    source_id: str
    source_samples: SampleRange
    output_frames: FrameRange

    def __post_init__(self) -> None:
        values = (self.silence_id, self.segment_id, self.source_id)
        if any(not isinstance(value, str) or not value for value in values):
            raise RepairContractError("removable silence identity is invalid")


@dataclass(frozen=True)
class DependentTiming:
    """One materialized dependent whose ripple impact must be disclosed."""

    stable_id: str
    element_kind: str
    frames: FrameRange
    anchor_type: str

    def __post_init__(self) -> None:
        if not isinstance(self.stable_id, str) or not self.stable_id \
                or not isinstance(self.element_kind, str) or not self.element_kind:
            raise RepairContractError("dependent identity is invalid")
        if self.anchor_type not in {"content", "source", "output-locked"}:
            raise RepairContractError("dependent anchor type is unsupported")


def _validate_segments(
    rows: tuple[CompiledCutSegment, ...],
    total_frames: int,
) -> None:
    segment_ids = {row.segment_id for row in rows}
    if len(segment_ids) != len(rows):
        raise RepairContractError("compiled segment IDs must be unique")
    ordered = sorted(rows, key=lambda row: row.output_frames.start_frame)
    if any(left.output_frames.end_frame_exclusive
           > right.output_frames.start_frame
           for left, right in zip(ordered, ordered[1:])):
        raise RepairContractError("compiled picture segments overlap")
    if any(row.output_frames.end_frame_exclusive > total_frames for row in rows):
        raise RepairContractError("compiled segment exceeds the timeline")


@dataclass(frozen=True)
class RepairContext:
    """All immutable evidence needed to enumerate one local repair."""

    target: ResolvedWordRange
    segments: tuple[CompiledCutSegment, ...]
    protected_speech: tuple[SampleRange, ...]
    silences: tuple[RemovableSilence, ...]
    covered_picture: tuple[FrameRange, ...]
    replaceable_audio: tuple[SampleRange, ...]
    replaceable_audio_evidence_hash: str
    dependents: tuple[DependentTiming, ...]
    clock: ProjectClock
    total_frames: int
    parent_timeline_map_hash: str
    parent_picture_lock_hash: str
    max_dirty_frames: int
    max_audio_overlap_frames: int

    def __post_init__(self) -> None:
        integers = (
            self.total_frames, self.max_dirty_frames,
            self.max_audio_overlap_frames,
        )
        if any(type(value) is not int for value in integers) \
                or self.total_frames <= 0 or self.max_dirty_frames <= 0 \
                or self.max_audio_overlap_frames <= 0:
            raise RepairContractError("repair frame bounds must be positive")
        if not _is_hash(self.parent_timeline_map_hash) \
                or not _is_hash(self.parent_picture_lock_hash) \
                or not _is_hash(self.replaceable_audio_evidence_hash):
            raise RepairContractError("repair parent hashes are malformed")
        _validate_segments(self.segments, self.total_frames)
        silence_ids = {row.silence_id for row in self.silences}
        if len(silence_ids) != len(self.silences):
            raise RepairContractError("removable silence IDs must be unique")
        dependent_ids = {row.stable_id for row in self.dependents}
        if len(dependent_ids) != len(self.dependents):
            raise RepairContractError("dependent IDs must be unique")
        if any(row.frames.end_frame_exclusive > self.total_frames
               for row in self.dependents):
            raise RepairContractError("dependent timing exceeds the timeline")
        if any(row.end_frame_exclusive > self.total_frames
               for row in self.covered_picture):
            raise RepairContractError("covered-picture evidence exceeds the timeline")
        total_samples = self.clock.sample_at_frame(self.total_frames)
        if any(row.end_sample_exclusive > total_samples
               for row in self.replaceable_audio):
            raise RepairContractError(
                "replaceable-audio evidence exceeds the timeline")
        for silence in self.silences:
            segment = next((row for row in self.segments
                            if row.segment_id == silence.segment_id), None)
            if segment is None or silence.source_id != segment.source_id:
                raise RepairContractError("silence does not bind a compiled segment")
            if silence.output_frames.start_frame \
                    < segment.output_frames.start_frame \
                    or silence.output_frames.end_frame_exclusive \
                    > segment.output_frames.end_frame_exclusive:
                raise RepairContractError("silence output range exceeds its segment")
            if silence.source_samples.start_sample \
                    < segment.source_samples.start_sample \
                    or silence.source_samples.end_sample_exclusive \
                    > segment.source_samples.end_sample_exclusive:
                raise RepairContractError("silence source range exceeds its segment")


@dataclass(frozen=True)
class RepairCandidate:
    """One mechanically valid, duration-neutral operation."""

    operation: dict[str, object]
    operation_hash: str


@dataclass(frozen=True)
class NonRippleAnalysis:
    """Eligible candidates, or an honest impossible result plus ripple impact."""

    status: str
    candidates: tuple[RepairCandidate, ...]
    ripple_impact: dict[str, object] | None
