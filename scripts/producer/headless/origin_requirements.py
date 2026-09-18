"""Typed R1 and trusted-observation gaps for initialization origin."""

from __future__ import annotations

from dataclasses import dataclass

from .artifact_contract import ArtifactRefV1
from .operation_policy import OperationPolicyGapV1

R0_BLOCKED_STATUS = "BLOCKED_R0_PROFILE_CANNOT_COMMIT_INITIALIZATION_ORIGIN"


@dataclass(frozen=True)
class OriginProfileRequirementV1:
    """One versioned authority change required beyond the fixed R0 profile."""

    code: str
    required_change: str


@dataclass(frozen=True)
class OriginAuthorityRequirementV1:
    """One trusted observation unavailable from structural current-card data."""

    code: str
    required_proof: str


@dataclass(frozen=True)
class OriginBindingReportV1:
    """Typed non-authorizing result for an exact genesis structural binding."""

    status: str
    operation_artifact: ArtifactRefV1
    snapshot_authority_artifact: ArtifactRefV1
    bound_current_card_roles: tuple[str, ...]
    missing_profile_authority: tuple[OriginProfileRequirementV1, ...]
    execution_policy_gaps: tuple[OperationPolicyGapV1, ...]
    unresolved_authority: tuple[OriginAuthorityRequirementV1, ...]
    structural_current_card_bound: bool
    operation_bytes_bound: bool
    snapshot_bytes_bound: bool
    profile_compatible: bool
    initialization_policy_authorized: bool
    runtime_verified: bool
    publication_authorized: bool


R1_PROFILE_REQUIREMENTS = (
    OriginProfileRequirementV1(
        "DISJOINT_GENERATION_PROFILE_R1",
        "version the closed profile by expectedParent without changing R0",
    ),
    OriginProfileRequirementV1(
        "INITIALIZATION_ORIGIN_RECEIPT_CLASS",
        "add one initialization-origin-receipt-v1 manifest artifact for genesis",
    ),
    OriginProfileRequirementV1(
        "HEADLESS_INITIALIZE_OPERATION_CLASS",
        "add one headless-operation-v1 manifest artifact bound to initialize bytes",
    ),
    OriginProfileRequirementV1(
        "INITIALIZATION_SNAPSHOT_AUTHORITY_CLASS",
        "add one initialization-snapshot-authority-v1 artifact for the presealed closure",
    ),
    OriginProfileRequirementV1(
        "GENESIS_APPROVED_CARD_V2",
        "use a genesis card that names origin instead of requiring assembly-receipt-v1",
    ),
    OriginProfileRequirementV1(
        "INITIALIZATION_EXECUTION_POLICY_V2",
        "commit a policy that explicitly authorizes initialize and its snapshot/base disposition",
    ),
    OriginProfileRequirementV1(
        "GENERATION_VERIFICATION_PROFILE_V2",
        "bind verification to the new exact genesis class multiset and policy",
    ),
)

UNRESOLVED_ORIGIN_AUTHORITY = (
    OriginAuthorityRequirementV1(
        "TRUSTED_ORIGIN_OPERATION_AND_SNAPSHOT_STORE",
        "resolve origin, operation, and snapshot-authority bytes from one sealed generation store",
    ),
    OriginAuthorityRequirementV1(
        "TRUSTED_INITIALIZATION_EXECUTION_POLICY",
        "parse a committed initialization-capable policy and prove its exact ID",
    ),
    OriginAuthorityRequirementV1(
        "BASE_PLAN_GRAPHICS_REOBSERVATION",
        "read and recompute base, base-plan, base receipt, timeline, plan, clips, and graphics",
    ),
    OriginAuthorityRequirementV1(
        "BUILD_RUNTIME_AND_TOOL_ATTESTATION",
        "parse build/runtime receipts and bind the exact compositor and media tools executed",
    ),
    OriginAuthorityRequirementV1(
        "MEDIA_QUALITY_AND_COVER_REOBSERVATION",
        "reobserve final media, decode, effects, QC, critics, approval, cover, and frame-zero proof",
    ),
    OriginAuthorityRequirementV1(
        "GENESIS_PUBLICATION_SEQUENCE",
        "a later publisher must prove the first CURRENT transition has publicationSeq exactly 1",
    ),
)
