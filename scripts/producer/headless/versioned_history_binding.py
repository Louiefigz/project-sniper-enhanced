"""Recursive origin/assembly binding for one selected versioned ancestry."""

from __future__ import annotations

from .artifact_contract import ArtifactRefV1
from .generation_schema import CurrentPointerV1, parse_current_pointer
from .versioned_history_node import history_card, validate_versioned_history_node
from .versioned_history_types import (
    VERSIONED_SELECTED_HISTORY_SCOPE,
    VERSIONED_SELECTED_HISTORY_STATUS,
    FrozenR0HistoryAuthorityV1,
    GenesisHistoryAuthorityV1,
    QualityPassV2HistoryAuthorityV1,
    VersionedHistoryBindingInputsV1,
    VersionedHistoryNodeSummaryV1,
    VersionedHistoryNodeV1,
    VersionedSelectedHistoryError,
    VersionedSelectedHistoryReportV1,
)
from .versioned_parent_authority import ParentAuthorityV2
from .wire_identity import same_wire_value as exact_value


def _anchor(value: object) -> CurrentPointerV1:
    if type(value) is not CurrentPointerV1:
        raise VersionedSelectedHistoryError("history anchor type is invalid")
    try:
        parsed = parse_current_pointer(value.document_json)
    except RuntimeError as exc:
        raise VersionedSelectedHistoryError("history anchor bytes are invalid") from exc
    if not exact_value(value, parsed):
        raise VersionedSelectedHistoryError("history anchor construction is stale")
    return parsed


def _receipt(node: VersionedHistoryNodeV1) -> tuple[str, ArtifactRefV1]:
    authority = node.authority
    if type(authority) is GenesisHistoryAuthorityV1:
        return (
            "initialization-origin-receipt-v1",
            authority.inputs.approved_card.origin.receipt,
        )
    if type(authority) is FrozenR0HistoryAuthorityV1:
        return "assembly-receipt-v1", authority.approved_card.output.assembly_receipt
    if type(authority) is QualityPassV2HistoryAuthorityV1:
        return (
            "assembly-receipt-v2",
            authority.inputs.approved_card.output.assembly_receipt,
        )
    raise VersionedSelectedHistoryError("history receipt authority is invalid")


def _assembly(node: VersionedHistoryNodeV1) -> object:
    authority = node.authority
    if type(authority) is FrozenR0HistoryAuthorityV1:
        return authority.assembly_receipt
    if type(authority) is QualityPassV2HistoryAuthorityV1:
        return authority.inputs.assembly_receipt
    raise VersionedSelectedHistoryError("genesis cannot be an assembly child")


def _declared_parent(
    child: VersionedHistoryNodeV1, parent: VersionedHistoryNodeV1
) -> None:
    expected = child.commit.expected_parent
    valid = (
        expected is not None
        and exact_value(expected, parent.ref)
        and child.ref.authority_id == parent.ref.authority_id
        and child.ref.publication_seq == parent.ref.publication_seq + 1
    )
    if not valid:
        raise VersionedSelectedHistoryError("selected history edge is discontinuous")
    receipt = _assembly(child)
    if not exact_value(receipt.parent, parent.ref):
        raise VersionedSelectedHistoryError("child receipt parent is stale")


def _parent_authority(
    child: VersionedHistoryNodeV1, parent: VersionedHistoryNodeV1
) -> None:
    receipt_class, receipt_ref = _receipt(parent)
    authority = child.authority
    if type(authority) is FrozenR0HistoryAuthorityV1:
        if type(parent.authority) is GenesisHistoryAuthorityV1:
            raise VersionedSelectedHistoryError(
                "frozen R0 cannot alias a genesis origin as an assembly receipt"
            )
        if (
            authority.assembly_receipt.parent_assembly_receipt_sha256
            != receipt_ref.sha256
        ):
            raise VersionedSelectedHistoryError("frozen R0 parent receipt is stale")
        return
    if type(authority) is not QualityPassV2HistoryAuthorityV1:
        raise VersionedSelectedHistoryError("history child authority is invalid")
    kind = (
        "genesis-origin"
        if type(parent.authority) is GenesisHistoryAuthorityV1
        else "prior-assembly"
    )
    expected = ParentAuthorityV2(kind, receipt_class, receipt_ref)
    if not exact_value(authority.inputs.assembly_receipt.parent_authority, expected):
        raise VersionedSelectedHistoryError("versioned parent authority is stale")


def _base_continuity(
    child: VersionedHistoryNodeV1, parent: VersionedHistoryNodeV1
) -> None:
    child_card, parent_card = history_card(child.authority), history_card(
        parent.authority
    )
    child_values = (
        child_card.base.media,
        child_card.base.plan_artifact,
        child_card.base.receipt,
        child_card.base.timeline_map,
        child_card.plan.base_projection_digest,
    )
    parent_values = (
        parent_card.base.media,
        parent_card.base.plan_artifact,
        parent_card.base.receipt,
        parent_card.base.timeline_map,
        parent_card.plan.base_projection_digest,
    )
    receipt = _assembly(child)
    receipt_values = (
        receipt.base,
        receipt.base_receipt_sha256,
        receipt.timeline_map_sha256,
        receipt.base_projection_digest,
    )
    parent_receipt_values = (
        parent_card.base.media,
        parent_card.base.receipt.sha256,
        parent_card.base.timeline_map.sha256,
        parent_card.plan.base_projection_digest,
    )
    if not exact_value(child_values, parent_values):
        raise VersionedSelectedHistoryError("child immutable base differs from parent")
    if not exact_value(receipt_values, parent_receipt_values):
        raise VersionedSelectedHistoryError("child assembly base differs from parent")


def _edge(child: VersionedHistoryNodeV1, parent: VersionedHistoryNodeV1) -> None:
    if type(child.authority) is GenesisHistoryAuthorityV1:
        raise VersionedSelectedHistoryError("genesis appears before history tail")
    _declared_parent(child, parent)
    _parent_authority(child, parent)
    _base_continuity(child, parent)


def _tail(nodes: tuple[VersionedHistoryNodeV1, ...]) -> VersionedHistoryNodeV1:
    genesis = tuple(
        node for node in nodes if type(node.authority) is GenesisHistoryAuthorityV1
    )
    tail = nodes[-1]
    valid = (
        len(genesis) == 1
        and genesis[0] is tail
        and tail.ref.publication_seq == 1
        and tail.commit.expected_parent is None
    )
    if not valid:
        raise VersionedSelectedHistoryError("selected history lacks one genesis tail")
    return tail


def _summary(node: VersionedHistoryNodeV1) -> VersionedHistoryNodeSummaryV1:
    receipt_class, receipt_ref = _receipt(node)
    return VersionedHistoryNodeSummaryV1(
        node.ref.publication_seq,
        node.ref.generation_id,
        node.ref.commit_digest,
        node.ref.plan_digest,
        node.profile,
        node.approved_card_class,
        receipt_class,
        receipt_ref.sha256,
    )


def _validate_inputs(
    value: object,
) -> tuple[CurrentPointerV1, tuple[VersionedHistoryNodeV1, ...]]:
    if (
        type(value) is not VersionedHistoryBindingInputsV1
        or type(value.nodes) is not tuple
    ):
        raise VersionedSelectedHistoryError("history binding inputs are invalid")
    anchor = _anchor(value.anchor)
    if not value.nodes:
        raise VersionedSelectedHistoryError("selected history is empty")
    nodes = tuple(validate_versioned_history_node(node) for node in value.nodes)
    head = nodes[0].ref
    actual = (
        head.authority_id,
        head.publication_seq,
        head.generation_id,
        head.commit_digest,
    )
    expected = (
        anchor.authority_id,
        anchor.publication_seq,
        anchor.generation_id,
        anchor.commit_digest,
    )
    if actual != expected:
        raise VersionedSelectedHistoryError("history head is not selected CURRENT")
    return anchor, nodes


def bind_versioned_selected_history(
    value: object,
) -> VersionedSelectedHistoryReportV1:
    """Bind every selected edge to one genesis origin without runtime claims."""
    anchor, nodes = _validate_inputs(value)
    tail = _tail(nodes)
    for child, parent in zip(nodes, nodes[1:]):
        _edge(child, parent)
    origin_digest = tail.authority.inputs.approved_card.origin.receipt.sha256
    edges = len(nodes) - 1
    return VersionedSelectedHistoryReportV1(
        VERSIONED_SELECTED_HISTORY_STATUS,
        VERSIONED_SELECTED_HISTORY_SCOPE,
        anchor.authority_id,
        anchor.publication_seq,
        anchor.generation_id,
        anchor.commit_digest,
        tail.ref.generation_id,
        tail.ref.commit_digest,
        origin_digest,
        tuple(_summary(node) for node in nodes),
        len(nodes),
        edges,
        edges,
        True,
        True,
        True,
        True,
        False,
        False,
        False,
        False,
        False,
    )


def require_versioned_history_execution_authorized(value: object) -> None:
    """Never convert recursive structural history into execution authority."""
    if type(value) is not VersionedSelectedHistoryReportV1:
        raise VersionedSelectedHistoryError("versioned history report is invalid")
    raise VersionedSelectedHistoryError(
        "versioned selected history is not execution-authorized"
    )
