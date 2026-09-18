"""Typed limits for structural assembly authority."""

from __future__ import annotations

from dataclasses import dataclass

from .artifact_contract import ArtifactRefV1

STRUCTURAL_STATUS = "STRUCTURAL_CURRENT_CARD_BOUND_NOT_RUNTIME_VERIFIED"
IMMEDIATE_PARENT_AND_BASE_CONTINUITY = "IMMEDIATE_PARENT_AND_BASE_CONTINUITY"
RECURSIVE_LINEAGE_AND_GENESIS_ORIGIN = "RECURSIVE_LINEAGE_AND_GENESIS_ORIGIN"


@dataclass(frozen=True)
class AssemblyAuthorityRequirementV1:
    """One authority unavailable from a current generation card alone."""

    code: str
    required_proof: str


@dataclass(frozen=True)
class AssemblyBindingReportV1:
    """Non-authorizing result of exact structural/current-card binding."""

    status: str
    assembly_receipt: ArtifactRefV1
    unresolved_authority: tuple[AssemblyAuthorityRequirementV1, ...]
    runtime_verified: bool
    publication_authorized: bool


UNRESOLVED_ASSEMBLY_AUTHORITY = (
    AssemblyAuthorityRequirementV1(
        IMMEDIATE_PARENT_AND_BASE_CONTINUITY,
        "resolve commit.expectedParent and prove its assembly/base/base-plan/receipt/timeline",
    ),
    AssemblyAuthorityRequirementV1(
        RECURSIVE_LINEAGE_AND_GENESIS_ORIGIN,
        "prove every selected assembly/base edge and the chain's versioned genesis origin",
    ),
    AssemblyAuthorityRequirementV1(
        "PLAN_CLIP_AND_FILTER_BYTES",
        "read exact plan/prebound-clips bytes and recompute plan, clip-set, and filter graph",
    ),
    AssemblyAuthorityRequirementV1(
        "COMPOSITOR_BUILD_RUNTIME_AND_TOOLS",
        "parse build/runtime authority and bind the stable ffmpeg/ffprobe binaries executed",
    ),
    AssemblyAuthorityRequirementV1(
        "MEDIA_AUDIO_ALPHA_DECODE_AND_COVER",
        "reobserve exact store bytes, media facts, stream hashes, alpha, decode, and frame zero",
    ),
    AssemblyAuthorityRequirementV1(
        "RETAINED_YDIF_REOBSERVATION",
        "retain independently auditable inline-preencode YDIF evidence",
    ),
    AssemblyAuthorityRequirementV1(
        "GRAPHIC_RENDER_BUILD_SEMANTICS",
        "parse graphic-render and render-build receipts behind both claimed digests",
    ),
)
