"""Typed inputs and non-authorizing result for genesis R1 structural binding."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .generation_schema import GenerationCommitV1
from .genesis_approved_card import GenesisApprovedCardV2
from .genesis_execution_policy import InitializationExecutionPolicyV2
from .genesis_generation_verification import GenesisGenerationVerificationV2
from .operation_contract import InitializeOperationV1
from .origin_receipt import InitializationOriginReceiptV1
from .origin_requirements import (
    OriginAuthorityRequirementV1,
    OriginProfileRequirementV1,
)

GENESIS_R1_STRUCTURAL_STATUS = (
    "STRUCTURAL_GENESIS_R1_BOUND_NOT_RUNTIME_OR_EXECUTION_AUTHORIZED"
)


@dataclass(frozen=True)
class GenesisAuthorityInputsV2:
    """All exact authorities plus bytes named by one genesis commit."""

    commit: GenerationCommitV1
    approved_card: GenesisApprovedCardV2
    origin_receipt: InitializationOriginReceiptV1
    operation: InitializeOperationV1
    initialization_policy: InitializationExecutionPolicyV2
    verification: GenesisGenerationVerificationV2
    snapshot_authority_json: bytes
    artifact_bytes: Mapping[str, bytes]


@dataclass(frozen=True)
class GenesisAuthorityBindingV2:
    """Structural success with every trusted execution gate held closed."""

    status: str
    closed_profile_requirements: tuple[OriginProfileRequirementV1, ...]
    remaining_trusted_blockers: tuple[OriginAuthorityRequirementV1, ...]
    bound_artifact_classes: tuple[str, ...]
    profile_selected: bool
    manifest_bytes_bound: bool
    approved_card_bound: bool
    origin_receipt_bound: bool
    operation_bound: bool
    snapshot_authority_bound: bool
    initialization_policy_compatible: bool
    generation_policies_bound: bool
    structural_verification_bound: bool
    trusted_store_verified: bool
    runtime_verified: bool
    execution_authorized: bool
    publication_authorized: bool


REMAINING_GENESIS_R1_BLOCKERS = (
    OriginAuthorityRequirementV1(
        "TRUSTED_SEALED_GENESIS_STORE",
        "resolve commit, card, origin, operation, snapshot, policy, and verification "
        "through one durable sealed-generation reader and reverify the snapshot's "
        "archive, manifest, and seal-receipt closure",
    ),
    OriginAuthorityRequirementV1(
        "BASE_PLAN_GRAPHICS_REOBSERVATION",
        "read and recompute base, base-plan, base receipt, timeline, plan, clips, "
        "and graphics",
    ),
    OriginAuthorityRequirementV1(
        "BUILD_RUNTIME_AND_TOOL_ATTESTATION",
        "reobserve build/runtime receipts and attest exact compositor and media tools",
    ),
    OriginAuthorityRequirementV1(
        "MEDIA_QUALITY_AND_COVER_REOBSERVATION",
        "reobserve final media, decode, effects, QC, critics, approval, cover, and "
        "frame-zero proof",
    ),
    OriginAuthorityRequirementV1(
        "GENESIS_PUBLICATION_SEQUENCE",
        "a later fenced publisher must prove the first CURRENT transition has "
        "publicationSeq exactly 1",
    ),
)
