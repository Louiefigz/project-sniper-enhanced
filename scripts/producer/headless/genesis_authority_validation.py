"""Fail-closed structural validators for genesis R1 authorities."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

from . import quality_receipt_json as wire
from .artifact_contract import ArtifactRefV1
from .generation_schema import (
    GenerationCommitV1,
    GenerationManifestRowV1,
    parse_generation_commit,
)
from .genesis_approved_card import (
    GenesisApprovedCardV2,
    validate_genesis_approved_card_v2,
)
from .genesis_authority_roles import genesis_authority_roles
from .genesis_authority_types import GenesisAuthorityInputsV2
from .genesis_execution_policy import (
    InitializationExecutionPolicyV2,
    bind_initialize_operation_policy_v2,
)
from .genesis_generation_verification import (
    GenesisGenerationVerificationV2,
    validate_genesis_generation_verification_v2,
)
from .operation_contract import (
    InitializeOperationV1,
    validate_headless_mp4_operation_v1,
)
from .operation_wire import canonical, parse_initialization_snapshot
from .origin_receipt import (
    InitializationOriginReceiptV1,
    validate_initialization_origin_receipt_v1,
)
from .wire_identity import same_wire_value


class GenesisAuthorityBindingError(RuntimeError):
    """Genesis R1 bytes or cross-authority structure are inconsistent."""


def _reparse_commit(commit: GenerationCommitV1) -> None:
    try:
        parsed = parse_generation_commit(commit.document_json)
    except RuntimeError as exc:
        raise GenesisAuthorityBindingError("genesis commit bytes are invalid") from exc
    if not same_wire_value(commit, parsed):
        raise GenesisAuthorityBindingError("genesis commit construction is invalid")


def revalidate_genesis_inputs(inputs: object) -> GenesisAuthorityInputsV2:
    """Reparse each typed wire authority before any semantic comparison."""
    if type(inputs) is not GenesisAuthorityInputsV2:
        raise GenesisAuthorityBindingError("genesis binding inputs are invalid")
    expected = (
        GenerationCommitV1,
        GenesisApprovedCardV2,
        InitializationOriginReceiptV1,
        InitializeOperationV1,
        InitializationExecutionPolicyV2,
        GenesisGenerationVerificationV2,
    )
    values = (
        inputs.commit,
        inputs.approved_card,
        inputs.origin_receipt,
        inputs.operation,
        inputs.initialization_policy,
        inputs.verification,
    )
    if tuple(type(value) for value in values) != expected:
        raise GenesisAuthorityBindingError("genesis authority types are invalid")
    try:
        _reparse_commit(inputs.commit)
        validate_genesis_approved_card_v2(inputs.approved_card)
        validate_initialization_origin_receipt_v1(inputs.origin_receipt)
        validate_headless_mp4_operation_v1(inputs.operation)
        validate_genesis_generation_verification_v2(inputs.verification, inputs.commit)
        bind_initialize_operation_policy_v2(
            inputs.operation, inputs.initialization_policy
        )
    except RuntimeError as exc:
        raise GenesisAuthorityBindingError("genesis authority is invalid") from exc
    return inputs


def snapshot_manifest_bytes(
    commit: GenerationCommitV1, artifact_bytes: object
) -> dict[str, bytes]:
    """Copy and hash-check the exact bytes for every committed manifest path."""
    if not isinstance(artifact_bytes, Mapping):
        raise GenesisAuthorityBindingError("genesis artifact bytes are not a mapping")
    try:
        snapshot = dict(artifact_bytes)
    except (TypeError, ValueError) as exc:
        raise GenesisAuthorityBindingError(
            "genesis artifact mapping is invalid"
        ) from exc
    if any(type(path) is not str for path in snapshot):
        raise GenesisAuthorityBindingError("genesis artifact paths are invalid")
    expected_paths = {row.path for row in commit.files}
    if set(snapshot) != expected_paths:
        raise GenesisAuthorityBindingError("genesis artifact mapping is not closed")
    rows = {row.path: row for row in commit.files}
    for path, raw in snapshot.items():
        row = rows[path]
        valid = (
            type(raw) is bytes
            and len(raw) == row.size_bytes
            and hashlib.sha256(raw).hexdigest() == row.sha256
        )
        if not valid:
            raise GenesisAuthorityBindingError(
                f"genesis artifact bytes contradict manifest: {path}"
            )
    return snapshot


def _identity(card: GenesisApprovedCardV2, commit: GenerationCommitV1) -> tuple:
    value = card.identity
    policy = card.policies
    return (
        value.authority_id,
        value.generation_id,
        value.attempt_id,
        value.unit_id,
        value.request_digest,
        policy.execution_policy_id,
        policy.repair_policy_id,
        policy.quality_policy_id,
        policy.fallback_policy_id,
    ), (
        commit.authority_id,
        commit.generation_id,
        commit.attempt_id,
        commit.unit_id,
        commit.request_digest,
        commit.execution_policy_id,
        commit.repair_policy_id,
        commit.quality_policy_id,
        commit.fallback_policy_id,
    )


def bind_genesis_current_card(inputs: GenesisAuthorityInputsV2) -> None:
    """Cross-bind commit, approved card, and origin current-card values."""
    card = inputs.approved_card
    receipt = inputs.origin_receipt
    actual_identity, expected_identity = _identity(card, inputs.commit)
    origin_policies = (
        receipt.policies.initialization_execution_policy_id,
        receipt.policies.repair_policy_id,
        receipt.policies.quality_policy_id,
        receipt.policies.fallback_policy_id,
    )
    card_policies = actual_identity[-4:]
    shared = (
        same_wire_value(card.identity, receipt.identity),
        same_wire_value(card.plan, receipt.plan),
        same_wire_value(card.base, receipt.base),
        same_wire_value(card.graphics, receipt.graphics),
        same_wire_value(card.quality, receipt.quality),
        same_wire_value(
            card.provenance.runtime_capability_manifest,
            receipt.build_runtime.runtime_capability_manifest,
        ),
    )
    outputs = all(
        same_wire_value(actual, expected)
        for actual, expected in zip(
            (
                card.output.final,
                card.output.cover,
                card.output.cover_proof,
                card.output.proxy_disposition,
            ),
            (
                receipt.output.final,
                receipt.output.cover,
                receipt.output.cover_proof,
                receipt.output.proxy_disposition,
            ),
        )
    )
    if (
        actual_identity != expected_identity
        or origin_policies != card_policies
        or not all(shared)
        or not outputs
    ):
        raise GenesisAuthorityBindingError("genesis current card is stale")


def bind_operation_snapshot(inputs: GenesisAuthorityInputsV2) -> None:
    """Bind exact operation and separately committed snapshot-authority bytes."""
    operation_document = wire.canonical_document(
        inputs.operation.document_json, "initialize operation"
    )
    snapshot_raw = canonical(operation_document["initializationSnapshot"])
    if inputs.snapshot_authority_json != snapshot_raw:
        raise GenesisAuthorityBindingError("genesis snapshot bytes are stale")
    snapshot_document = wire.canonical_document(snapshot_raw, "snapshot authority")
    try:
        snapshot = parse_initialization_snapshot(snapshot_document)
    except RuntimeError as exc:
        raise GenesisAuthorityBindingError("genesis snapshot is invalid") from exc
    receipt = inputs.origin_receipt
    card = inputs.approved_card
    expected = (
        inputs.operation.operation_digest,
        snapshot.snapshot_id,
        inputs.operation.unit_id,
        inputs.operation.execution_policy_id,
    )
    actual = (
        card.origin.operation_digest,
        card.origin.snapshot_id,
        card.identity.unit_id,
        card.policies.execution_policy_id,
    )
    receipt_values = (
        receipt.operation.digest,
        receipt.operation.snapshot_id,
        receipt.identity.unit_id,
        receipt.policies.initialization_execution_policy_id,
    )
    if actual != expected or receipt_values != expected:
        raise GenesisAuthorityBindingError("genesis operation authority is stale")
    if not same_wire_value(snapshot, inputs.operation.snapshot):
        raise GenesisAuthorityBindingError("genesis snapshot authority is stale")


def _artifact(row: GenerationManifestRowV1) -> ArtifactRefV1:
    return ArtifactRefV1(row.path, row.sha256, row.size_bytes)


def _require_role(ref: ArtifactRefV1, artifact_class: str, groups: Mapping) -> None:
    candidates = tuple(_artifact(row) for row in groups.get(artifact_class, ()))
    matches = tuple(
        candidate for candidate in candidates if same_wire_value(candidate, ref)
    )
    if len(matches) != 1:
        raise GenesisAuthorityBindingError(
            f"genesis role does not match class {artifact_class}"
        )


def bind_genesis_manifest_roles(
    inputs: GenesisAuthorityInputsV2, groups: Mapping
) -> None:
    """Require every named genesis authority to match exactly one allowed class."""
    roles = genesis_authority_roles(inputs.approved_card, inputs.origin_receipt)
    for _name, ref, artifact_class in roles:
        _require_role(ref, artifact_class, groups)
    excluded = {
        "genesis-approved-card-v2",
        "generation-verification-v2",
        "repair-policy-v1",
        "quality-policy-v1",
        "fallback-policy-v1",
    }
    described = {ref for _name, ref, _artifact_class in roles}
    expected = {
        _artifact(row)
        for name, rows in groups.items()
        if name not in excluded
        for row in rows
    }
    if described != expected:
        raise GenesisAuthorityBindingError(
            "genesis approved-card coverage is incomplete"
        )
