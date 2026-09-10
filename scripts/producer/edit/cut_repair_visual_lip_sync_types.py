"""Closed value types for selected-source visual lip-sync evidence."""
from __future__ import annotations

from dataclasses import dataclass

VISUAL_IMPLEMENTATION_SCOPE = "visual-choice-seam-repository-code-v1"
VISUAL_IMPLEMENTATION_NONCLAIMS = (
    "audio-seam-measurement",
    "candidate-qc-orchestration-storage-or-promotion",
    "python-stdlib-os-dylibs",
)
VISUAL_IMPLEMENTATION_ROLES = (
    "controller",
    "media-decoder",
    "receipt-projector",
    "visual-value-types",
    "authority-hashing",
    "candidate-qc-value-types",
    "candidate-qc-visual-adapter",
    "candidate-qc-seam-projector",
    "visual-seam-contract",
)


class VisualLipSyncBlocker(ValueError):
    """A visual lip-sync pass cannot be issued for the supplied evidence."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class RationalRate:
    """One positive rational video rate."""

    numerator: int
    denominator: int


@dataclass(frozen=True)
class FrameSpan:
    """One half-open decoded-frame range."""

    first: int
    end_exclusive: int


@dataclass(frozen=True)
class SampleSpan:
    """One half-open media-native sample range."""

    start: int
    end_exclusive: int
    rate: int


@dataclass(frozen=True)
class RegionPpm:
    """A normalized visible-speech ROI in parts per million."""

    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class SelectionAuthority:
    """Exact governed alternate-take selection consumed by the oracle."""

    preparation_hash: str
    operation_hash: str
    receipt_hash: str
    candidate_set_hash: str
    selection_hash: str
    selected_candidate_id: str
    source_id: str
    source_path: str
    source_sha256: str
    source_frames: FrameSpan
    source_samples: SampleSpan
    source_rate: RationalRate
    output_frames: FrameSpan
    output_samples: SampleSpan
    output_rate: RationalRate
    visual_region: RegionPpm


@dataclass(frozen=True)
class MediaAuthority:
    """Exact full-plan candidate observed by the oracle."""

    path: str
    sha256: str


@dataclass(frozen=True)
class OracleToolchain:
    """Pinned visual choice/seam code, runtime, policy, and FFmpeg bytes."""

    ffmpeg_path: str
    ffmpeg_sha256: str
    runtime_path: str
    runtime_sha256: str
    implementation_path: str
    implementation_sha256: str
    implementation_scope: str
    implementation_nonclaims: tuple[str, ...]
    policy_path: str
    policy_sha256: str
    implementation_closure_hash: str
    implementation_files: tuple[tuple[str, str, str], ...]


@dataclass(frozen=True)
class OracleRequest:
    """All immutable inputs to one bounded visual lip-sync observation."""

    selection: SelectionAuthority
    candidate: MediaAuthority
    tools: OracleToolchain
    tool_manifest_hash: str


@dataclass(frozen=True)
class DecodedEvidence:
    """Decoded visual and audio traces used for offset measurement."""

    source_frames: tuple[bytes, ...]
    candidate_frames: tuple[bytes, ...]
    source_pcm: tuple[int, ...]
    candidate_pcm: tuple[int, ...]
