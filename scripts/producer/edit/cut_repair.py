"""P2 ``cut.restoreSpeech`` resolution and non-ripple analysis seam."""
from __future__ import annotations

from dataclasses import dataclass

from edit.exact_timing import FrameRange, ProjectClock, SampleRange
from edit.non_ripple import enumerate_non_ripple
from edit.cut_repair_selection import select_restore_candidate
from edit.non_ripple_contracts import (
    CompiledCutSegment,
    DependentTiming,
    RemovableSilence,
    RepairContext,
)
from edit.target_resolver import (
    PhraseTarget,
    ResolvedWordRange,
    WordRef,
    protected_word_ranges,
    resolve_phrase,
)


@dataclass(frozen=True)
class RestoreSpeechInput:
    """Immutable inputs for a deterministic restore-speech analysis."""

    words: tuple[WordRef, ...]
    target: PhraseTarget
    segments: tuple[CompiledCutSegment, ...]
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


def _context(item: RestoreSpeechInput, resolved: ResolvedWordRange,
             protected: tuple[SampleRange, ...]) -> RepairContext:
    return RepairContext(
        target=resolved,
        segments=item.segments,
        protected_speech=protected,
        silences=item.silences,
        covered_picture=item.covered_picture,
        replaceable_audio=item.replaceable_audio,
        replaceable_audio_evidence_hash=item.replaceable_audio_evidence_hash,
        dependents=item.dependents,
        clock=item.clock,
        total_frames=item.total_frames,
        parent_timeline_map_hash=item.parent_timeline_map_hash,
        parent_picture_lock_hash=item.parent_picture_lock_hash,
        max_dirty_frames=item.max_dirty_frames,
        max_audio_overlap_frames=item.max_audio_overlap_frames,
    )


def analyze_restore_speech(item: RestoreSpeechInput) -> dict[str, object]:
    """Resolve an exact occurrence and enumerate candidates without mutation."""
    resolved = resolve_phrase(item.words, item.target)
    protected = protected_word_ranges(item.words, resolved)
    context = _context(item, resolved, protected)
    analysis = enumerate_non_ripple(context)
    candidates = [
        {"operation": row.operation, "operationHash": row.operation_hash}
        for row in analysis.candidates
    ]
    return {
        "schemaVersion": 1,
        "operation": "cut.restoreSpeech",
        "status": analysis.status,
        "resolvedTarget": resolved.to_dict(),
        "candidates": candidates,
        "recommendedCandidate": (
            select_restore_candidate(candidates)
            if analysis.status == "eligible" else None),
        "rippleImpact": analysis.ripple_impact,
        "evidencePolicy": {
            "alignment": "bounded-evidence-not-sole-audibility-proof",
            "operatorReport": "ground-truth-when-audition-disagrees",
        },
    }
