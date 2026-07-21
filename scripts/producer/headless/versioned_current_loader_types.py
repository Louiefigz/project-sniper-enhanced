"""Tagged, path-free results for versioned selected-CURRENT disk loading."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .artifact_contract import ArtifactRefV1
from .generation_schema import CurrentPointerV1, GenerationCommitV1
from .genesis_approved_card import GenesisApprovedCardV2
from .genesis_authority_types import GenesisAuthorityBindingV2
from .genesis_execution_policy import InitializationExecutionPolicyV2
from .genesis_generation_verification import GenesisGenerationVerificationV2
from .genesis_payload_reobservation_types import GenesisPayloadReobservationV1
from .operation_contract import InitializeOperationV1
from .origin_receipt import InitializationOriginReceiptV1
from .versioned_quality_pass_types import (
    QualityPassAuthorityInputsV2,
    QualityPassCurrentBindingV2,
)

LEGACY_R0_SELECTED_STATUS = "FROZEN_R0_SELECTED_REQUIRES_LEGACY_LOADER"
GENESIS_R1_DISK_STATUS = (
    "GENESIS_R1_FULL_PAYLOAD_STREAM_REOBSERVED_STRUCTURALLY_BOUND_NOT_AUTHORIZED"
)


@dataclass(frozen=True)
class CurrentAuthorityBlockerV1:
    """One explicit authority requirement this disk seam does not close."""

    code: str
    description: str


@dataclass(frozen=True)
class FrozenR0CurrentSelectionV1:
    """Tagged R0 selection that never masquerades as a versioned card."""

    kind: str
    status: str
    profile: str
    approved_card_class: str
    current: CurrentPointerV1
    commit: GenerationCommitV1
    blockers: tuple[CurrentAuthorityBlockerV1, ...]
    authority_documents_bound: bool
    runtime_verified: bool
    execution_authorized: bool
    publication_authorized: bool


@dataclass(frozen=True)
class GenesisR1CurrentDocumentsV2:
    """Full streamed R1 structure without runtime or execution authority."""

    kind: str
    status: str
    profile: str
    approved_card_class: str
    current: CurrentPointerV1
    commit: GenerationCommitV1
    approved_card: GenesisApprovedCardV2
    origin_receipt: InitializationOriginReceiptV1
    operation: InitializeOperationV1
    initialization_policy: InitializationExecutionPolicyV2
    verification: GenesisGenerationVerificationV2
    snapshot_authority_json: bytes
    document_refs: Mapping[str, ArtifactRefV1]
    payload_reobservation: GenesisPayloadReobservationV1
    structural_binding: GenesisAuthorityBindingV2
    blockers: tuple[CurrentAuthorityBlockerV1, ...]
    manifest_bytes_materialized: bool
    authority_documents_bound: bool
    full_genesis_authority_bound: bool
    runtime_verified: bool
    execution_authorized: bool
    publication_authorized: bool


@dataclass(frozen=True)
class QualityPassV2CurrentDocumentsV2:
    """Exact current V2 authority documents and non-authorizing binding result."""

    kind: str
    status: str
    profile: str
    approved_card_class: str
    current: CurrentPointerV1
    commit: GenerationCommitV1
    authority: QualityPassAuthorityInputsV2
    binding: QualityPassCurrentBindingV2
    document_refs: Mapping[str, ArtifactRefV1]
    blockers: tuple[CurrentAuthorityBlockerV1, ...]
    manifest_bytes_materialized: bool
    authority_documents_bound: bool
    runtime_verified: bool
    execution_authorized: bool
    publication_authorized: bool


VersionedCurrentAuthorityResultV2 = (
    FrozenR0CurrentSelectionV1
    | GenesisR1CurrentDocumentsV2
    | QualityPassV2CurrentDocumentsV2
)


POINT_IN_TIME_SELECTION_BLOCKER = CurrentAuthorityBlockerV1(
    "FINAL_CURRENT_AND_FENCE_RECHECK",
    "the selected CURRENT snapshot is point-in-time evidence; execution and "
    "publication must recheck CURRENT under the operation fence",
)

LEGACY_R0_BLOCKERS = (
    CurrentAuthorityBlockerV1(
        "FROZEN_R0_LOADER_REQUIRED",
        "use the frozen ApprovedParentDescriptorV1 loader; this seam returns no "
        "legacy descriptor",
    ),
    POINT_IN_TIME_SELECTION_BLOCKER,
)

GENESIS_R1_DISK_BLOCKERS = (
    CurrentAuthorityBlockerV1(
        "GENESIS_CONTENT_RUNTIME_AND_TOOL_SEMANTICS",
        "complete payload bytes are structurally bound, but base, plan, graphics, "
        "build, runtime, media, and quality semantics require trusted reobservation",
    ),
    CurrentAuthorityBlockerV1(
        "GENESIS_RUNTIME_EXECUTION_PUBLICATION",
        "runtime reobservation, execution authority, and fenced publication remain "
        "external trusted operations",
    ),
    POINT_IN_TIME_SELECTION_BLOCKER,
)

QUALITY_PASS_V2_DISK_BLOCKERS = (
    CurrentAuthorityBlockerV1(
        "OPERATION_RUNTIME_AND_EXECUTION_AUTHORITY",
        "current-card structural binding does not prove operation admission, runtime "
        "execution, output measurements, or publication",
    ),
    POINT_IN_TIME_SELECTION_BLOCKER,
)
