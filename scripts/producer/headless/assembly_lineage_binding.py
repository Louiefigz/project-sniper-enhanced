"""Close only historical-parent and immutable-base assembly continuity."""

from __future__ import annotations

from .approved_parent_assembly_binding import (
    ApprovedParentAssemblyBindingError,
    bind_approved_parent_assembly_receipt,
)
from .approved_parent_assembly_receipt import AssemblyReceiptV1
from .approved_parent_schema import ApprovedParentDescriptorV1
from .generation_schema import GenerationCommitV1
from .assembly_lineage_types import (
    IMMEDIATE_EDGE_STATUS,
    IMMEDIATE_PARENT_AND_BASE_CONTINUITY,
    LINEAGE_PROOF_SCOPE,
    UNRESOLVED_LINEAGE_AUTHORITY,
    AssemblyLineageContinuityV1,
)
from .assembly_lineage_validation import validate_historical_materialization
from .historical_generation_types import HistoricalGenerationMaterializationV1
from .quality_receipt_json import same_typed_value


class AssemblyLineageBindingError(RuntimeError):
    """Assembly parent or base authority differs from selected history."""


def _current_inputs(
    descriptor: object, commit: object, receipt: object
) -> tuple[ApprovedParentDescriptorV1, GenerationCommitV1, AssemblyReceiptV1]:
    expected = (ApprovedParentDescriptorV1, GenerationCommitV1, AssemblyReceiptV1)
    if tuple(type(item) for item in (descriptor, commit, receipt)) != expected:
        raise AssemblyLineageBindingError("current assembly inputs are invalid")
    try:
        bind_approved_parent_assembly_receipt(descriptor, commit, receipt)
    except ApprovedParentAssemblyBindingError as exc:
        raise AssemblyLineageBindingError("current assembly card is invalid") from exc
    return descriptor, commit, receipt


def _parent_identity(
    historical: HistoricalGenerationMaterializationV1,
    commit: GenerationCommitV1,
    receipt: AssemblyReceiptV1,
) -> None:
    parent = commit.expected_parent
    if parent is None:
        raise AssemblyLineageBindingError(
            "assembly lineage continuity cannot validate genesis"
        )
    expected = historical.target.ref
    if not (
        same_typed_value(parent, expected)
        and same_typed_value(receipt.parent, expected)
    ):
        raise AssemblyLineageBindingError("historical target is not exact parent")


def _selected_child(
    historical: HistoricalGenerationMaterializationV1,
    descriptor: ApprovedParentDescriptorV1,
    commit: GenerationCommitV1,
) -> None:
    lineage = historical.lineage
    if len(lineage) < 2:
        raise AssemblyLineageBindingError("historical lineage has no parent edge")
    head = lineage[0]
    valid = (
        same_typed_value(head.commit, commit)
        and same_typed_value(head.descriptor, descriptor)
        and same_typed_value(historical.target, lineage[1])
    )
    if not valid:
        raise AssemblyLineageBindingError("current card is not selected lineage head")


def _base_continuity(
    historical: ApprovedParentDescriptorV1,
    current: ApprovedParentDescriptorV1,
    receipt: AssemblyReceiptV1,
) -> None:
    historical_base = historical.base
    current_values = (
        current.base.media,
        current.base.plan_artifact,
        current.base.receipt,
        current.base.timeline_map,
        current.plan.base_projection_digest,
    )
    historical_values = (
        historical_base.media,
        historical_base.plan_artifact,
        historical_base.receipt,
        historical_base.timeline_map,
        historical.plan.base_projection_digest,
    )
    receipt_values = (
        receipt.base,
        receipt.base_receipt_sha256,
        receipt.timeline_map_sha256,
        receipt.base_projection_digest,
    )
    expected_receipt = (
        historical_base.media,
        historical_base.receipt.sha256,
        historical_base.timeline_map.sha256,
        historical.plan.base_projection_digest,
    )
    if not same_typed_value(current_values, historical_values):
        raise AssemblyLineageBindingError("current base chain differs from parent")
    if not same_typed_value(receipt_values, expected_receipt):
        raise AssemblyLineageBindingError("assembly base chain differs from parent")


def bind_assembly_lineage_continuity(
    historical: object,
    descriptor: object,
    commit: object,
    receipt: object,
) -> AssemblyLineageContinuityV1:
    """Close one base-lineage requirement without runtime/publication claims."""
    descriptor, commit, receipt = _current_inputs(descriptor, commit, receipt)
    try:
        materialization, store, parent_descriptor = validate_historical_materialization(
            historical
        )
    except RuntimeError as exc:
        raise AssemblyLineageBindingError("historical parent is invalid") from exc
    _selected_child(materialization, descriptor, commit)
    _parent_identity(materialization, commit, receipt)
    parent_assembly = parent_descriptor.output.assembly_receipt
    if receipt.parent_assembly_receipt_sha256 != parent_assembly.sha256:
        raise AssemblyLineageBindingError("parent assembly receipt is stale")
    _base_continuity(parent_descriptor, descriptor, receipt)
    for ref in (
        parent_descriptor.base.media.artifact,
        parent_descriptor.base.plan_artifact,
        parent_descriptor.base.receipt,
        parent_descriptor.base.timeline_map,
        parent_assembly,
    ):
        store.resolve(ref)
    return AssemblyLineageContinuityV1(
        IMMEDIATE_EDGE_STATUS,
        LINEAGE_PROOF_SCOPE,
        (IMMEDIATE_PARENT_AND_BASE_CONTINUITY,),
        UNRESOLVED_LINEAGE_AUTHORITY,
        materialization.anchor_current,
        materialization.lineage[0].ref,
        materialization.target.ref,
        parent_assembly,
        parent_descriptor.base.media,
        parent_descriptor.base.plan_artifact,
        parent_descriptor.base.receipt,
        parent_descriptor.base.timeline_map,
        parent_descriptor.plan.base_projection_digest,
        len(materialization.lineage),
        len(materialization.lineage) - 1,
        1,
        False,
        False,
        False,
        False,
    )
