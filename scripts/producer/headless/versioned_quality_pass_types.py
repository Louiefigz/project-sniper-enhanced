"""Typed current and parent-bridge inputs for quality-pass authority V2."""

from __future__ import annotations

from dataclasses import dataclass

from .approved_parent_assembly_receipt import AssemblyReceiptV1
from .approved_parent_assembly_types import (
    AssemblyAuthorityRequirementV1,
    UNRESOLVED_ASSEMBLY_AUTHORITY,
)
from .approved_parent_schema import ApprovedParentDescriptorV1
from .artifact_contract import ArtifactRefV1
from .generation_schema import GenerationCommitV1
from .genesis_authority_types import GenesisAuthorityInputsV2
from .repair_intent import ParentRefV1
from .versioned_assembly_receipt import AssemblyReceiptV2
from .versioned_parent_authority import ParentAuthorityV2
from .versioned_quality_pass_card import QualityPassApprovedCardV2
from .versioned_quality_pass_verification import QualityPassGenerationVerificationV2

QUALITY_PASS_V2_CURRENT_STATUS = (
    "STRUCTURAL_QUALITY_PASS_V2_CURRENT_CARD_BOUND_NOT_RUNTIME_VERIFIED"
)
QUALITY_PASS_V2_BRIDGE_STATUS = (
    "STRUCTURAL_QUALITY_PASS_V2_PARENT_AUTHORITY_BOUND_NOT_RUNTIME_AUTHORIZED"
)


@dataclass(frozen=True)
class QualityPassAuthorityInputsV2:
    """Exact current-generation card, receipt, commit, and verification V2."""

    commit: GenerationCommitV1
    approved_card: QualityPassApprovedCardV2
    assembly_receipt: AssemblyReceiptV2
    verification: QualityPassGenerationVerificationV2


@dataclass(frozen=True)
class QualityPassCurrentBindingV2:
    """Current card success without historical, runtime, or execution authority."""

    status: str
    assembly_receipt: ArtifactRefV1
    parent_authority: ParentAuthorityV2
    unresolved_authority: tuple[AssemblyAuthorityRequirementV1, ...]
    runtime_verified: bool
    execution_authorized: bool
    publication_authorized: bool


@dataclass(frozen=True)
class GenesisParentSnapshotV2:
    """Full structurally bound genesis authority plus its publication reference."""

    ref: ParentRefV1
    authority: GenesisAuthorityInputsV2


@dataclass(frozen=True)
class PriorAssemblyV1ParentSnapshotV2:
    """Frozen R0 prior-assembly authority plus its publication reference."""

    ref: ParentRefV1
    commit: GenerationCommitV1
    approved_card: ApprovedParentDescriptorV1
    assembly_receipt: AssemblyReceiptV1


@dataclass(frozen=True)
class PriorAssemblyV2ParentSnapshotV2:
    """Versioned prior-assembly authority plus its publication reference."""

    ref: ParentRefV1
    authority: QualityPassAuthorityInputsV2


ParentSnapshotV2 = (
    GenesisParentSnapshotV2
    | PriorAssemblyV1ParentSnapshotV2
    | PriorAssemblyV2ParentSnapshotV2
)


@dataclass(frozen=True)
class QualityPassParentBridgeInputsV2:
    """One current quality pass and the exact parent generation it names."""

    current: QualityPassAuthorityInputsV2
    parent: ParentSnapshotV2


@dataclass(frozen=True)
class QualityPassParentBridgeBindingV2:
    """Immediate parent-kind authentication with all execution gates closed."""

    status: str
    parent: ParentRefV1
    parent_authority: ParentAuthorityV2
    current_assembly_receipt: ArtifactRefV1
    unresolved_authority: tuple[AssemblyAuthorityRequirementV1, ...]
    parent_kind_authenticated: bool
    immediate_base_continuity_bound: bool
    recursive_lineage_verified: bool
    runtime_verified: bool
    execution_authorized: bool
    publication_authorized: bool


def remaining_after_parent_bridge() -> tuple[AssemblyAuthorityRequirementV1, ...]:
    """Drop only the immediate-parent requirement closed by the V2 bridge."""
    return tuple(
        item
        for item in UNRESOLVED_ASSEMBLY_AUTHORITY
        if item.code != "IMMEDIATE_PARENT_AND_BASE_CONTINUITY"
    )
