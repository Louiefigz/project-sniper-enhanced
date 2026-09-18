"""Exact manifest-document bindings for genesis R1 structural authority."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

from .artifact_contract import ArtifactRefV1
from .generation_schema import GenerationManifestRowV1
from .genesis_authority_types import GenesisAuthorityInputsV2
from .genesis_authority_validation import GenesisAuthorityBindingError
from .wire_identity import same_wire_value


def _artifact(row: GenerationManifestRowV1) -> ArtifactRefV1:
    return ArtifactRefV1(row.path, row.sha256, row.size_bytes)


def _sole(groups: Mapping, artifact_class: str) -> ArtifactRefV1:
    rows = groups.get(artifact_class, ())
    if len(rows) != 1:
        raise GenesisAuthorityBindingError(
            f"genesis authority class is not singular: {artifact_class}"
        )
    return _artifact(rows[0])


def _raw_ref(ref: ArtifactRefV1, raw: bytes) -> ArtifactRefV1:
    return ArtifactRefV1(ref.relative_path, hashlib.sha256(raw).hexdigest(), len(raw))


def _document_refs(inputs: GenesisAuthorityInputsV2, groups: Mapping) -> tuple:
    classes = (
        "genesis-approved-card-v2",
        "initialization-origin-receipt-v1",
        "headless-operation-v1",
        "initialization-snapshot-authority-v1",
        "initialization-execution-policy-v2",
        "generation-verification-v2",
    )
    return tuple(_sole(groups, name) for name in classes)


def _cross_refs(inputs: GenesisAuthorityInputsV2, refs: tuple) -> None:
    card_ref, origin_ref, operation_ref, snapshot_ref, policy_ref, _verify_ref = refs
    card = inputs.approved_card
    receipt = inputs.origin_receipt
    actual = (
        card.origin.receipt,
        card.origin.operation,
        card.origin.snapshot_authority,
        card.provenance.execution_policy,
        inputs.verification.approved_card,
    )
    expected = (origin_ref, operation_ref, snapshot_ref, policy_ref, card_ref)
    receipt_refs = (
        receipt.operation.artifact,
        receipt.operation.snapshot_authority,
    )
    matches = same_wire_value(actual, expected) and same_wire_value(
        receipt_refs, (operation_ref, snapshot_ref)
    )
    if not matches:
        raise GenesisAuthorityBindingError("genesis authority references are stale")
    if not same_wire_value(inputs.verification.origin, card.origin):
        raise GenesisAuthorityBindingError("genesis verification origin is stale")


def bind_exact_authority_documents(
    inputs: GenesisAuthorityInputsV2,
    groups: Mapping,
    artifact_bytes: Mapping[str, bytes],
) -> None:
    """Bind each parsed authority to its exact committed bytes and cross-refs."""
    card_ref, origin_ref, operation_ref, snapshot_ref, policy_ref, verify_ref = (
        _document_refs(inputs, groups)
    )
    raw_values = (
        inputs.approved_card.document_json,
        inputs.origin_receipt.document_json,
        inputs.operation.document_json,
        inputs.snapshot_authority_json,
        inputs.initialization_policy.document_json,
        inputs.verification.document_json,
    )
    refs = (card_ref, origin_ref, operation_ref, snapshot_ref, policy_ref, verify_ref)
    if any(
        not same_wire_value(_raw_ref(ref, raw), ref)
        for ref, raw in zip(refs, raw_values)
    ):
        raise GenesisAuthorityBindingError("genesis authority document bytes are stale")
    if any(
        artifact_bytes[ref.relative_path] != raw for ref, raw in zip(refs, raw_values)
    ):
        raise GenesisAuthorityBindingError("genesis manifest resolves different bytes")
    _cross_refs(inputs, refs)
