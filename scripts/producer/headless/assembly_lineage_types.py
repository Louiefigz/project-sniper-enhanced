"""Typed non-authorizing result for assembly base-lineage continuity."""

from __future__ import annotations

from dataclasses import dataclass

from .artifact_contract import ArtifactRefV1, MediaRefV1
from .generation_schema import CurrentPointerV1
from .repair_intent import ParentRefV1

IMMEDIATE_PARENT_AND_BASE_CONTINUITY = "IMMEDIATE_PARENT_AND_BASE_CONTINUITY"
LINEAGE_PROOF_SCOPE = "selected-ancestry-authenticated-immediate-assembly-edge-only"
RECURSIVE_LINEAGE_AND_GENESIS_ORIGIN = "RECURSIVE_LINEAGE_AND_GENESIS_ORIGIN"
IMMEDIATE_EDGE_STATUS = (
    "SELECTED_CURRENT_IMMEDIATE_PARENT_BASE_CARD_BOUND_"
    "NOT_RECURSIVE_OR_ORIGIN_VERIFIED"
)


@dataclass(frozen=True)
class AssemblyLineageRequirementV1:
    """One ancestry proof that this immediate-edge binder does not close."""

    code: str
    required_proof: str


@dataclass(frozen=True)
class AssemblyLineageContinuityV1:
    """One immediate edge; recursive ancestry and runtime remain unresolved."""

    status: str
    proof_scope: str
    closed_requirements: tuple[str, ...]
    unresolved_authority: tuple[AssemblyLineageRequirementV1, ...]
    anchor_current: CurrentPointerV1
    selected_child: ParentRefV1
    parent: ParentRefV1
    parent_assembly_receipt: ArtifactRefV1
    base: MediaRefV1
    base_plan: ArtifactRefV1
    base_receipt: ArtifactRefV1
    timeline_map: ArtifactRefV1
    base_projection_digest: str
    lineage_node_count: int
    assembly_edges_required: int
    assembly_edges_verified: int
    recursive_assembly_verified: bool
    genesis_origin_verified: bool
    runtime_verified: bool
    publication_authorized: bool


UNRESOLVED_LINEAGE_AUTHORITY = (
    AssemblyLineageRequirementV1(
        RECURSIVE_LINEAGE_AND_GENESIS_ORIGIN,
        "parse and bind every selected assembly edge plus the versioned genesis origin",
    ),
)
