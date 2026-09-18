"""Typed non-authorizing output for quality-pass composition inspection."""

from __future__ import annotations

from dataclasses import dataclass

from .approved_parent_media import ApprovedParentVerifierContextV1
from .repair_intent import ParentRefV1

R0_GENESIS_BLOCKED = "BLOCKED_R0_GENESIS_REQUIRES_R1_DISPATCH"
STRUCTURAL_CHILD_STATUS = "STRUCTURAL_PARENT_DIAGNOSTICS_NOT_EXECUTION_AUTHORITY"


class QualityPassCompositionInspectionError(RuntimeError):
    """Composition diagnostics could not bind one coherent parent snapshot."""


@dataclass(frozen=True)
class QualityPassCompositionInspectionRequestV1:
    """All filesystem and verifier inputs owned by the future composition root."""

    authority_root: str
    current_materialization_root: str
    historical_materialization_root: str
    operation_json: bytes
    verifier: ApprovedParentVerifierContextV1


@dataclass(frozen=True)
class CompositionAuthorityRequirementV1:
    """One authority that remains absent after structural inspection."""

    code: str
    required_proof: str


@dataclass(frozen=True)
class NonAuthorizingQualityPassCompositionV1:
    """Immutable diagnostics only; never a render or publication capability."""

    status: str
    operation_digest: str
    unit_id: str
    expected_parent: ParentRefV1
    current_commit_digest: str
    candidate_plan_digest: str
    candidate_plan_sha256: str
    closed_checks: tuple[str, ...]
    unresolved_authority: tuple[CompositionAuthorityRequirementV1, ...]
    parent_profile: str
    lineage_status: str | None
    lineage_edges_required: int
    lineage_edges_verified: int
    parent_runtime_status: str | None
    parent_quality_runtime_reobserved: bool
    recursive_assembly_verified: bool
    genesis_origin_verified: bool
    durable_admission_bound: bool
    operation_runtime_verified: bool
    fence_rechecked: bool
    execution_authorized: bool
    publication_authorized: bool
