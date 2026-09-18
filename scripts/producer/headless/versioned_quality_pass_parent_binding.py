"""Immediate R1-genesis or prior-assembly bridge for quality-pass V2."""

from __future__ import annotations

from .approved_parent_assembly_binding import (
    ApprovedParentAssemblyBindingError,
    bind_approved_parent_assembly_receipt,
)
from .genesis_authority_binding import bind_genesis_r1_authority
from .quality_receipt_json import same_typed_value
from .repair_intent import ParentRefV1, validate_parent_ref
from .versioned_parent_authority import ParentAuthorityV2
from .versioned_quality_pass_current_binding import (
    bind_quality_pass_current_authority_v2,
)
from .versioned_quality_pass_current_validation import (
    QualityPassCurrentBindingV2Error,
)
from .versioned_quality_pass_types import (
    QUALITY_PASS_V2_BRIDGE_STATUS,
    GenesisParentSnapshotV2,
    PriorAssemblyV1ParentSnapshotV2,
    PriorAssemblyV2ParentSnapshotV2,
    QualityPassParentBridgeBindingV2,
    QualityPassParentBridgeInputsV2,
    remaining_after_parent_bridge,
)


class QualityPassParentBridgeV2Error(RuntimeError):
    """Immediate parent authority or immutable base differs from the child."""


def _validate_ref(
    ref: ParentRefV1, commit: object, card: object, genesis: bool
) -> None:
    try:
        validate_parent_ref(ref)
    except RuntimeError as exc:
        raise QualityPassParentBridgeV2Error("parent reference is invalid") from exc
    expected = (
        commit.authority_id,
        commit.generation_id,
        commit.commit_digest,
        card.plan.approved_plan_digest,
    )
    actual = (
        ref.authority_id,
        ref.generation_id,
        ref.commit_digest,
        ref.plan_digest,
    )
    genesis_edge = (
        genesis and ref.publication_seq == 1 and commit.expected_parent is None
    )
    assembly_edge = (
        not genesis
        and commit.expected_parent is not None
        and ref.publication_seq == commit.expected_parent.publication_seq + 1
    )
    valid_edge = genesis_edge or assembly_edge
    if actual != expected or not valid_edge:
        raise QualityPassParentBridgeV2Error("parent reference is stale")


def _genesis_parent(value: GenesisParentSnapshotV2) -> tuple:
    try:
        report = bind_genesis_r1_authority(value.authority)
    except RuntimeError as exc:
        raise QualityPassParentBridgeV2Error(
            "genesis parent authority is invalid"
        ) from exc
    if report.runtime_verified or report.execution_authorized:
        raise QualityPassParentBridgeV2Error("genesis parent report is overclaimed")
    card = value.authority.approved_card
    _validate_ref(value.ref, value.authority.commit, card, True)
    authority = ParentAuthorityV2(
        "genesis-origin",
        "initialization-origin-receipt-v1",
        card.origin.receipt,
    )
    return value.ref, authority, card


def _assembly_v1_parent(value: PriorAssemblyV1ParentSnapshotV2) -> tuple:
    try:
        report = bind_approved_parent_assembly_receipt(
            value.approved_card, value.commit, value.assembly_receipt
        )
    except ApprovedParentAssemblyBindingError as exc:
        raise QualityPassParentBridgeV2Error(
            "prior assembly V1 parent is invalid"
        ) from exc
    if report.runtime_verified or report.publication_authorized:
        raise QualityPassParentBridgeV2Error("prior V1 parent report is overclaimed")
    _validate_ref(value.ref, value.commit, value.approved_card, False)
    authority = ParentAuthorityV2(
        "prior-assembly",
        "assembly-receipt-v1",
        value.approved_card.output.assembly_receipt,
    )
    return value.ref, authority, value.approved_card


def _assembly_v2_parent(value: PriorAssemblyV2ParentSnapshotV2) -> tuple:
    try:
        report = bind_quality_pass_current_authority_v2(value.authority)
    except QualityPassCurrentBindingV2Error as exc:
        raise QualityPassParentBridgeV2Error(
            "prior assembly V2 parent is invalid"
        ) from exc
    if report.runtime_verified or report.execution_authorized:
        raise QualityPassParentBridgeV2Error("prior V2 parent report is overclaimed")
    card = value.authority.approved_card
    _validate_ref(value.ref, value.authority.commit, card, False)
    authority = ParentAuthorityV2(
        "prior-assembly", "assembly-receipt-v2", card.output.assembly_receipt
    )
    return value.ref, authority, card


def _parent(value: object) -> tuple:
    if type(value) is GenesisParentSnapshotV2:
        return _genesis_parent(value)
    if type(value) is PriorAssemblyV1ParentSnapshotV2:
        return _assembly_v1_parent(value)
    if type(value) is PriorAssemblyV2ParentSnapshotV2:
        return _assembly_v2_parent(value)
    raise QualityPassParentBridgeV2Error("parent snapshot type is unsupported")


def _base_continuity(current: object, parent_card: object) -> None:
    card, receipt = current.approved_card, current.assembly_receipt
    current_values = (
        card.base.media,
        card.base.plan_artifact,
        card.base.receipt,
        card.base.timeline_map,
        card.plan.base_projection_digest,
    )
    parent_values = (
        parent_card.base.media,
        parent_card.base.plan_artifact,
        parent_card.base.receipt,
        parent_card.base.timeline_map,
        parent_card.plan.base_projection_digest,
    )
    receipt_values = (
        receipt.base,
        receipt.base_receipt_sha256,
        receipt.timeline_map_sha256,
        receipt.base_projection_digest,
    )
    parent_receipt = (
        parent_card.base.media,
        parent_card.base.receipt.sha256,
        parent_card.base.timeline_map.sha256,
        parent_card.plan.base_projection_digest,
    )
    if not same_typed_value(current_values, parent_values):
        raise QualityPassParentBridgeV2Error("child base differs from parent")
    if not same_typed_value(receipt_values, parent_receipt):
        raise QualityPassParentBridgeV2Error("assembly base differs from parent")


def bind_quality_pass_parent_bridge_v2(
    value: object,
) -> QualityPassParentBridgeBindingV2:
    """Authenticate immediate origin/assembly kind and immutable base continuity."""
    if type(value) is not QualityPassParentBridgeInputsV2:
        raise QualityPassParentBridgeV2Error("parent bridge inputs are invalid")
    try:
        current = bind_quality_pass_current_authority_v2(value.current)
    except QualityPassCurrentBindingV2Error as exc:
        raise QualityPassParentBridgeV2Error("current quality pass is invalid") from exc
    parent_ref, parent_authority, parent_card = _parent(value.parent)
    receipt = value.current.assembly_receipt
    expected = (parent_ref, parent_authority)
    actual = (receipt.parent, receipt.parent_authority)
    if not same_typed_value(actual, expected):
        raise QualityPassParentBridgeV2Error("declared parent authority is stale")
    _base_continuity(value.current, parent_card)
    return QualityPassParentBridgeBindingV2(
        QUALITY_PASS_V2_BRIDGE_STATUS,
        parent_ref,
        parent_authority,
        current.assembly_receipt,
        remaining_after_parent_bridge(),
        True,
        True,
        False,
        False,
        False,
        False,
    )


def require_quality_pass_bridge_execution_authorized(value: object) -> None:
    """Never promote the immediate structural bridge into execution authority."""
    if type(value) is not QualityPassParentBridgeBindingV2:
        raise QualityPassParentBridgeV2Error("parent bridge binding is invalid")
    raise QualityPassParentBridgeV2Error(
        "quality-pass parent bridge is not execution-authorized"
    )
