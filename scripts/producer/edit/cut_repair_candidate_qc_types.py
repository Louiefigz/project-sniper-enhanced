"""Shared immutable value types for candidate-bound cut-repair QC."""
from __future__ import annotations

from dataclasses import dataclass


class CandidateQcContractError(ValueError):
    """Candidate QC inputs are absent, stale, substituted, or open-ended."""


@dataclass(frozen=True)
class DirtyWindow:
    """One bounded output-clock extraction interval."""

    first_frame: int
    end_frame_exclusive: int
    dirty_start_sample: int
    dirty_end_sample_exclusive: int
    start_sample: int
    end_sample_exclusive: int
    sample_rate: int
    fps_numerator: int
    fps_denominator: int


@dataclass(frozen=True)
class CandidateAuthority:
    """Exact full-plan candidate and target evidence."""

    producer: str
    preparation_hash: str
    package: dict
    descriptor: dict
    candidate_path: str
    candidate_sha256: str
    operation: dict
    target_phrase: str
    target_word_ids: tuple[str, ...]
    source_media_path: str
    source_media_sha256: str
    source_id: str
    source_start_sample: int
    source_end_sample_exclusive: int
    source_sample_rate: int
    total_frames: int
    window: DirtyWindow
    picture_dirty: bool
    alternate_take_selection: dict | None
    alternate_take_selection_hash: str | None
    alternate_take_selection_path: str | None


@dataclass(frozen=True)
class ToolFile:
    """One pinned executable or immutable data file."""

    path: str
    sha256: str


@dataclass(frozen=True)
class AlignerTool:
    """Pinned deterministic source-waveform alignment implementation."""

    protocol: str
    runtime: ToolFile
    implementation: ToolFile
    policy: ToolFile


@dataclass(frozen=True)
class VisualImplementationFile:
    """One role-labelled member of the visual implementation closure."""

    role: str
    file: ToolFile


@dataclass(frozen=True)
class VisualOracleTool:
    """Pinned selected-source visual choice/seam implementation."""

    protocol: str
    runtime: ToolFile
    implementation: ToolFile
    implementation_scope: str
    implementation_nonclaims: tuple[str, ...]
    policy: ToolFile
    implementation_closure_hash: str
    implementation_files: tuple[VisualImplementationFile, ...]


@dataclass(frozen=True)
class QcTools:
    """Exact toolchain admitted for one QC run."""

    manifest_hash: str
    ffmpeg: ToolFile
    whisper: ToolFile
    whisper_model: ToolFile
    aligner: AlignerTool | None
    visual_oracle: VisualOracleTool | None


@dataclass(frozen=True)
class QcRun:
    """Verified inputs and deterministic receipt destination."""

    authority: CandidateAuthority
    tools: QcTools
    invocation_hash: str
    directory: str
