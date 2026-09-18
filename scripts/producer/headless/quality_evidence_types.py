"""Typed values for exact deterministic-MP4 quality evidence wires."""

from __future__ import annotations

from dataclasses import dataclass

from .artifact_contract import ArtifactRefV1


@dataclass(frozen=True)
class DecodeStreamsV1:
    """Expected and decoded stream coverage for the exact final MP4."""

    expected_video: int
    decoded_video: int
    expected_audio: int
    decoded_audio: int


@dataclass(frozen=True)
class DecodeVideoV1:
    """Fail-on-error video frame and packet coverage."""

    expected_frames: int
    decoded_frames: int
    expected_packets: int
    decoded_packets: int


@dataclass(frozen=True)
class DecodeAudioV1:
    """Fail-on-error audio sample and packet coverage."""

    channels: int
    sample_rate_hz: int
    expected_samples_per_channel: int
    decoded_samples_per_channel: int
    expected_packets: int
    decoded_packets: int


@dataclass(frozen=True)
class DecodeToolsV1:
    """Exact binaries used for decoding and expected-count measurement."""

    ffmpeg_sha256: str
    ffprobe_sha256: str


@dataclass(frozen=True)
class DecodeExecutionV1:
    """Checked decoder process outcome and fail-on-error sinks."""

    error_policy: str
    exit_code: int
    video_sink: str
    audio_sink: str


@dataclass(frozen=True)
class FullDecodeProofV1:
    """Complete fail-on-error video and audio decode proof."""

    plan: ArtifactRefV1
    approved_plan_digest: str
    final: ArtifactRefV1
    assembly_receipt: ArtifactRefV1
    quality_policy_id: str
    runtime_capability_manifest: ArtifactRefV1
    tools: DecodeToolsV1
    execution: DecodeExecutionV1
    streams: DecodeStreamsV1
    video: DecodeVideoV1
    audio: DecodeAudioV1
    document_json: bytes


@dataclass(frozen=True)
class EffectTargetV1:
    """The sole stable-ID section-marker accent request proved by R0."""

    graphic_id: str
    relative_pointer: str
    requested_value: str
    brand_policy_id: str
    brand_membership: str


@dataclass(frozen=True)
class PreEncodeEffectV1:
    """Exact lossless overlay token/raster evidence before H.264 encode."""

    graphic_media: ArtifactRefV1
    render_intent_digest: str
    raster_rgb: tuple[int, int, int]
    matching_pixels: int
    method: str


@dataclass(frozen=True)
class DecodedColorV1:
    """Calibrated requested-color landing over the complete sample window."""

    requested_rgb: tuple[int, int, int]
    observed_rgb: tuple[int, int, int]
    maximum_delta_e_milli: int
    observed_delta_e_milli: int
    sampled_frames: int
    matching_frames: int
    method: str


@dataclass(frozen=True)
class EffectTimingV1:
    """Plan window and decoded-frame boundary evidence."""

    out_start: int | float
    out_end: int | float
    expected_first_frame: int
    expected_last_frame: int
    observed_first_frame: int
    observed_last_frame: int
    boundary_tolerance_frames: int
    sampled_frames: int


@dataclass(frozen=True)
class EffectPlacementV1:
    """Expected and observed composite origin/canvas evidence."""

    anchor: str
    expected_x: int | float
    expected_y: int | float
    observed_x: int | float
    observed_y: int | float
    max_origin_error_pixels: int
    delivery_width: int
    delivery_height: int
    graphic_width: int
    graphic_height: int
    method: str


@dataclass(frozen=True)
class EffectContrastV1:
    """Full-window moving-background contrast evidence."""

    required_minimum_milli_ratio: int
    observed_minimum_milli_ratio: int
    sampled_frames: int
    passing_frames: int
    method: str


@dataclass(frozen=True)
class ProtectedRegionsV1:
    """Caption/title noncollision evidence for every sampled frame."""

    region_kinds: tuple[str, ...]
    sampled_frames: int
    collision_frames: int
    maximum_overlap_pixels: int
    method: str


@dataclass(frozen=True)
class EffectLocalityV1:
    """Pre-encode exact locality and calibrated encoded-spill evidence."""

    preencode_changed_pixels: int
    preencode_outside_roi_changed_pixels: int
    decoded_outside_roi_material_pixels: int
    materiality_threshold_milli: int
    observed_max_outside_roi_delta_milli: int
    method: str


@dataclass(frozen=True)
class EffectProofV1:
    """Complete requested SECTION_MARKER_ACCENT_V1 landing proof."""

    plan: ArtifactRefV1
    approved_plan_digest: str
    final: ArtifactRefV1
    assembly_receipt: ArtifactRefV1
    quality_policy_id: str
    runtime_capability_manifest: ArtifactRefV1
    effect_class: str
    request_digest: str
    target: EffectTargetV1
    preencode: PreEncodeEffectV1
    decoded_color: DecodedColorV1
    timing: EffectTimingV1
    placement: EffectPlacementV1
    contrast: EffectContrastV1
    protected_regions: ProtectedRegionsV1
    locality: EffectLocalityV1
    document_json: bytes


@dataclass(frozen=True)
class AuditDomainV1:
    """One required normalized Audit-B check family."""

    name: str
    verdict: str
    check_count: int
    warning_count: int


@dataclass(frozen=True)
class AuditSummaryV1:
    """Exact aggregate check counts from the terminal audit."""

    check_count: int
    passed: int
    warnings: int
    failed: int


@dataclass(frozen=True)
class AuditBReceiptV1:
    """Terminal Audit-B receipt downstream of independent evidence."""

    plan: ArtifactRefV1
    approved_plan_digest: str
    final: ArtifactRefV1
    assembly_receipt: ArtifactRefV1
    quality_policy_id: str
    runtime_capability_manifest: ArtifactRefV1
    full_decode: ArtifactRefV1
    effect_proof: ArtifactRefV1
    evidence_set_digest: str
    domains: tuple[AuditDomainV1, ...]
    summary: AuditSummaryV1
    document_json: bytes


@dataclass(frozen=True)
class ApprovedParentQualityEvidenceV1:
    """Acyclic full-decode/effect then terminal-Audit evidence set."""

    full_decode: FullDecodeProofV1
    effect_proof: EffectProofV1
    audit: AuditBReceiptV1
