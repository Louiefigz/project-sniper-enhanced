"""Path-free types for recursive selected-history authentication."""

from __future__ import annotations

from dataclasses import dataclass

from .approved_parent_assembly_receipt import AssemblyReceiptV1
from .approved_parent_schema import ApprovedParentDescriptorV1
from .generation_schema import CurrentPointerV1, GenerationCommitV1
from .genesis_authority_types import GenesisAuthorityInputsV2
from .repair_intent import ParentRefV1
from .versioned_quality_pass_types import QualityPassAuthorityInputsV2

VERSIONED_SELECTED_HISTORY_SCOPE = (
    "selected-current-recursive-versioned-ancestry-only-no-global-fork-claim"
)
VERSIONED_SELECTED_HISTORY_STATUS = (
    "SELECTED_CURRENT_RECURSIVE_LINEAGE_AND_GENESIS_ORIGIN_BOUND_"
    "NOT_RUNTIME_OR_EXECUTION_AUTHORIZED"
)


class VersionedSelectedHistoryError(RuntimeError):
    """Selected versioned ancestry is unsafe, discontinuous, or inconsistent."""


@dataclass(frozen=True)
class GenesisHistoryAuthorityV1:
    """Disk-parsed genesis authority retained only while the resolver is active."""

    inputs: GenesisAuthorityInputsV2


@dataclass(frozen=True)
class FrozenR0HistoryAuthorityV1:
    """Disk-parsed frozen R0 card and its assembly receipt."""

    commit: GenerationCommitV1
    approved_card: ApprovedParentDescriptorV1
    assembly_receipt: AssemblyReceiptV1


@dataclass(frozen=True)
class QualityPassV2HistoryAuthorityV1:
    """Disk-parsed quality-pass V2 authority."""

    inputs: QualityPassAuthorityInputsV2


HistoryAuthorityV1 = (
    GenesisHistoryAuthorityV1
    | FrozenR0HistoryAuthorityV1
    | QualityPassV2HistoryAuthorityV1
)


@dataclass(frozen=True)
class VersionedHistoryNodeV1:
    """Internal semantic node authenticated from one sealed generation."""

    ref: ParentRefV1
    profile: str
    approved_card_class: str
    commit: GenerationCommitV1
    authority: HistoryAuthorityV1


@dataclass(frozen=True)
class VersionedHistoryNodeSummaryV1:
    """Path-free identity summary safe to expose after descriptors close."""

    publication_seq: int
    generation_id: str
    commit_digest: str
    plan_digest: str
    profile: str
    approved_card_class: str
    authority_receipt_class: str
    authority_receipt_sha256: str


@dataclass(frozen=True)
class VersionedSelectedHistoryReportV1:
    """Recursive selected-chain proof that confers no execution capability."""

    status: str
    proof_scope: str
    anchor_authority_id: str
    anchor_publication_seq: int
    anchor_generation_id: str
    anchor_commit_digest: str
    genesis_generation_id: str
    genesis_commit_digest: str
    genesis_origin_receipt_sha256: str
    nodes: tuple[VersionedHistoryNodeSummaryV1, ...]
    lineage_node_count: int
    lineage_edges_required: int
    lineage_edges_verified: int
    selected_current_ancestry_verified: bool
    unique_genesis_tail_verified: bool
    recursive_lineage_verified: bool
    genesis_origin_verified: bool
    global_fork_uniqueness_verified: bool
    final_current_and_fence_rechecked: bool
    runtime_verified: bool
    execution_authorized: bool
    publication_authorized: bool


@dataclass(frozen=True)
class VersionedHistoryBindingInputsV1:
    """Pinned CURRENT plus disk-authenticated nodes ordered child to genesis."""

    anchor: CurrentPointerV1
    nodes: tuple[VersionedHistoryNodeV1, ...]
