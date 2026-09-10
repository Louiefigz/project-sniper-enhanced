"""Deterministic duration-neutral speech-repair candidate enumeration."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from edit.exact_timing import (
    SampleRange,
    source_span_frames,
    source_span_project_samples,
)
from edit.picture_lock_common import content_hash
from edit.non_ripple_contracts import (
    CompiledCutSegment,
    NonRippleAnalysis,
    RepairCandidate,
    RepairContext,
    RepairContractError,
)
from edit.repair_impact import (
    audio_sample_window,
    dependency_partition,
    frame_window_at_seam,
    reclaimed_silence_residual,
    ripple_dependents,
    unchanged_frame_ranges,
)
from edit.repair_ranges import (
    PictureDirtyGeometry,
    contains_frames,
    contains_samples,
    overlaps_samples,
    picture_dirty_range,
    source_video_frame_range,
)


@dataclass(frozen=True)
class _RepairEdge:
    segment: CompiledCutSegment
    side: str
    extension: SampleRange

    @property
    def seam_frame(self) -> int:
        return (self.segment.output_frames.start_frame if self.side == "start"
                else self.segment.output_frames.end_frame_exclusive)


def _protected(extension: SampleRange,
               protected: Sequence[SampleRange]) -> bool:
    return any(overlaps_samples(extension, row) for row in protected)


def _target_complete_count(context: RepairContext) -> int:
    target = context.target.samples
    return sum(row.source_id == context.target.source_id
               and row.source_samples.start_sample <= target.start_sample
               and row.source_samples.end_sample_exclusive
               >= target.end_sample_exclusive for row in context.segments)

def _target_straddles_segments(context: RepairContext) -> bool:
    target = context.target.samples
    overlaps = [row for row in context.segments
                if row.source_id == context.target.source_id
                and overlaps_samples(row.source_samples, target)]
    return len(overlaps) > 1

def _partial_edges(context: RepairContext) -> list[_RepairEdge]:
    target = context.target.samples
    edges: list[_RepairEdge] = []
    same_source = [row for row in context.segments
                   if row.source_id == context.target.source_id]
    for segment in same_source:
        source = segment.source_samples
        if source.start_sample <= target.start_sample \
                and source.end_sample_exclusive >= target.end_sample_exclusive:
            return []
        if target.start_sample < source.start_sample < target.end_sample_exclusive:
            edges.append(_RepairEdge(
                segment, "start",
                SampleRange(target.start_sample, source.start_sample)))
        if target.start_sample < source.end_sample_exclusive \
                < target.end_sample_exclusive:
            edges.append(_RepairEdge(
                segment, "end",
                SampleRange(source.end_sample_exclusive,
                            target.end_sample_exclusive)))
    if edges or not same_source:
        return edges
    before = [row for row in same_source
              if row.source_samples.end_sample_exclusive <= target.start_sample]
    after = [row for row in same_source
             if row.source_samples.start_sample >= target.end_sample_exclusive]
    if before:
        segment = max(before, key=lambda row: (
            row.source_samples.end_sample_exclusive, row.segment_id))
        edges.append(_RepairEdge(
            segment, "end",
            SampleRange(segment.source_samples.end_sample_exclusive,
                        target.end_sample_exclusive)))
    if after:
        segment = min(after, key=lambda row: (
            row.source_samples.start_sample, row.segment_id))
        edges.append(_RepairEdge(
            segment, "start",
            SampleRange(target.start_sample,
                        segment.source_samples.start_sample)))
    return edges


def _base_operation(context: RepairContext, edge: _RepairEdge,
                    extension_frames: int) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "operation": "cut.restoreSpeech",
        "target": context.target.to_dict(),
        "parentPictureLockHash": context.parent_picture_lock_hash,
        "parentTimelineMapHash": context.parent_timeline_map_hash,
        "segment": {
            "segmentId": edge.segment.segment_id,
            "elementVersion": edge.segment.element_version,
            "edge": edge.side,
        },
        "sourceExtension": edge.extension.to_dict(),
        "sourceSampleRate": edge.segment.source_rate,
        "speed": edge.segment.speed.to_dict(),
        "extensionFrames": extension_frames,
        "preserveUnrelated": True,
        "totalOutputFramesBefore": context.total_frames,
        "totalOutputFramesAfter": context.total_frames,
    }


def _source_picture_fields(edge: _RepairEdge) -> dict[str, object]:
    fps = edge.segment.source_fps
    if fps is None:
        raise RepairContractError("picture repair lacks source frame rate")
    frames = source_video_frame_range(
        edge.extension, edge.segment.source_rate, fps)
    return {
        "sourceVideoFrameRange": frames.to_dict(),
        "sourceFrameRate": fps.to_dict(),
    }


def _audio_candidate(context: RepairContext, edge: _RepairEdge,
                     frames: int) -> RepairCandidate | None:
    if frames > context.max_audio_overlap_frames:
        return None
    window = frame_window_at_seam(
        context.total_frames, edge.seam_frame, frames, edge.side == "start")
    if window is None or not any(
            contains_frames(cover, window) for cover in context.covered_picture):
        return None
    output_samples = source_span_project_samples(
        edge.extension.length, edge.segment.source_rate,
        edge.segment.speed, context.clock)
    sample_window = audio_sample_window(
        context, edge.seam_frame, output_samples, edge.side == "start")
    if sample_window is None:
        return None
    if not any(contains_samples(row, sample_window)
               for row in context.replaceable_audio):
        return None
    operation = {
        **_base_operation(context, edge, frames),
        "method": "audio-lj-overlap",
        "pictureDirtyWindows": [],
        "audioDirtyWindows": [window.to_dict()],
        "audioDirtySampleRanges": [sample_window.to_dict()],
        "replacedAudioSampleRanges": [sample_window.to_dict()],
        "replaceableAudioEvidenceHash":
            context.replaceable_audio_evidence_hash,
        "extensionOutputSamples": output_samples,
        "unchangedPictureMappingRanges": unchanged_frame_ranges(
            context.total_frames, None),
        **dependency_partition(context.dependents, (window,)),
    }
    return RepairCandidate(operation, content_hash(operation))


def _picture_candidate(context: RepairContext, edge: _RepairEdge,
                       frames: int) -> RepairCandidate | None:
    if edge.segment.source_fps is None:
        return None
    silence = next((row for row in sorted(
                    context.silences, key=lambda item: item.silence_id)
                    if row.segment_id == edge.segment.segment_id
                    and row.source_id == edge.segment.source_id
                    and not overlaps_samples(
                        row.source_samples, edge.extension)
                    and row.output_frames.length == frames), None)
    if silence is None:
        return None
    dirty = picture_dirty_range(PictureDirtyGeometry(
        context.total_frames, edge.seam_frame, frames, edge.side == "end",
        silence.output_frames, context.max_dirty_frames))
    if dirty is None:
        return None
    unchanged = unchanged_frame_ranges(context.total_frames, dirty)
    if not unchanged:
        return None
    output_samples = source_span_project_samples(
        edge.extension.length, edge.segment.source_rate,
        edge.segment.speed, context.clock)
    residual = reclaimed_silence_residual(
        context, silence, output_samples)
    if residual is None:
        return None
    operation = {
        **_base_operation(context, edge, frames),
        "method": "extend-and-reclaim-silence",
        **_source_picture_fields(edge),
        "reclaimedSilence": {
            "silenceId": silence.silence_id,
            "sourceSampleRange": silence.source_samples.to_dict(),
            "outputFrameRange": silence.output_frames.to_dict(),
        },
        "pictureDirtyWindows": [dirty.to_dict()],
        "audioDirtyWindows": [dirty.to_dict()],
        "audioDirtySampleRanges": [
            context.clock.samples_for_frames(dirty).to_dict()],
        "extensionOutputSamples": output_samples,
        "quantizationResidualSamples": residual,
        "residualPolicy": "reclaimed-proved-silence",
        "unchangedPictureMappingRanges": unchanged,
        **dependency_partition(context.dependents, (dirty,)),
    }
    return RepairCandidate(operation, content_hash(operation))


def _ripple_impact(context: RepairContext,
                   edges: Sequence[_RepairEdge]) -> dict[str, object]:
    if not edges:
        return {
            "exact": False,
            "blockingReason": "NO_ADJACENT_SOURCE_HANDLE",
            "reopensPictureLock": True,
        }
    edge = min(edges, key=lambda row: (
        row.extension.length, row.segment.segment_id, row.side))
    frames = source_span_frames(
        edge.extension.length, edge.segment.source_rate,
        edge.segment.speed, context.clock)
    return {
        "exact": True,
        "requiredDurationDeltaFrames": frames,
        "newTotalOutputFrames": context.total_frames + frames,
        "rippleFromFrame": edge.seam_frame,
        "reopensPictureLock": True,
        "semanticClosureRequired": True,
        **ripple_dependents(context.dependents, edge.seam_frame, frames),
    }


def enumerate_non_ripple(context: RepairContext) -> NonRippleAnalysis:
    """Enumerate least-disruptive valid candidates without mutating authority."""
    if context.total_frames <= 0 \
            or context.max_dirty_frames <= 0 \
            or context.max_audio_overlap_frames <= 0:
        raise RepairContractError("repair bounds and total frames must be positive")
    complete_count = _target_complete_count(context)
    if complete_count > 1:
        return NonRippleAnalysis("NON_RIPPLE_IMPOSSIBLE", (), {
            "exact": False,
            "blockingReason": "TARGET_HAS_MULTIPLE_OUTPUT_OWNERS",
            "reopensPictureLock": True,
        })
    if complete_count == 1:
        return NonRippleAnalysis("already-complete", (), None)
    edges = _partial_edges(context)
    if _target_straddles_segments(context):
        return NonRippleAnalysis("NON_RIPPLE_IMPOSSIBLE", (), {
            "exact": False,
            "blockingReason": "WORD_STRADDLES_SEGMENTS",
            "reopensPictureLock": True,
        })
    candidates: list[RepairCandidate] = []
    for edge in sorted(edges, key=lambda row: (
            row.extension.length, row.segment.segment_id, row.side)):
        if _protected(edge.extension, context.protected_speech):
            continue
        frames = source_span_frames(
            edge.extension.length, edge.segment.source_rate,
            edge.segment.speed, context.clock)
        audio = _audio_candidate(context, edge, frames)
        picture = _picture_candidate(context, edge, frames)
        candidates.extend(row for row in (audio, picture) if row is not None)
    unique: dict[str, RepairCandidate] = {}
    for row in candidates:
        unique.setdefault(row.operation_hash, row)
    ordered = tuple(unique.values())
    if ordered:
        return NonRippleAnalysis("eligible", ordered, None)
    return NonRippleAnalysis(
        "NON_RIPPLE_IMPOSSIBLE", (), _ripple_impact(context, edges))
