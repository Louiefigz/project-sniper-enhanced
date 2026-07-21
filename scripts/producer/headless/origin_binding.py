"""Fail-closed R0 assessment for an initialization-origin receipt."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from .approved_parent_binding import validate_descriptor_identity
from .approved_parent_schema import (
    ApprovedParentDescriptorV1,
    parse_approved_parent_descriptor,
)
from .artifact_contract import ArtifactRefV1
from .generation_policy_documents import current_execution_policy
from .generation_profile import verify_r0_generation_profile
from .generation_schema import (
    GenerationCommitV1,
    GenerationManifestRowV1,
    parse_generation_commit,
)
from .operation_contract import (
    InitializeOperationV1,
    validate_headless_mp4_operation_v1,
)
from .operation_policy import (
    OperationPolicyGapV1,
    bind_operation_execution_policy,
)
from .operation_wire import canonical
from .origin_requirements import (
    R0_BLOCKED_STATUS,
    R1_PROFILE_REQUIREMENTS,
    UNRESOLVED_ORIGIN_AUTHORITY,
    OriginBindingReportV1,
)
from .origin_roles import origin_manifest_roles
from .origin_receipt import (
    InitializationOriginReceiptV1,
    validate_initialization_origin_receipt_v1,
)
from .quality_receipt_json import same_typed_value


class InitializationOriginBindingError(RuntimeError):
    """Origin bytes contradict their exact operation, card, or R0 commit."""


def _artifact(path: str, raw: bytes) -> ArtifactRefV1:
    return ArtifactRefV1(path, hashlib.sha256(raw).hexdigest(), len(raw))


def _parsed_inputs(
    descriptor: object, commit: object, receipt: object, operation: object
) -> tuple:
    expected = (
        ApprovedParentDescriptorV1,
        GenerationCommitV1,
        InitializationOriginReceiptV1,
        InitializeOperationV1,
    )
    if (
        tuple(type(item) for item in (descriptor, commit, receipt, operation))
        != expected
    ):
        raise InitializationOriginBindingError("origin binding inputs are invalid")
    try:
        parsed_descriptor = parse_approved_parent_descriptor(descriptor.document_json)
        parsed_commit = parse_generation_commit(commit.document_json)
        validate_initialization_origin_receipt_v1(receipt)
        validate_headless_mp4_operation_v1(operation)
    except RuntimeError as exc:
        raise InitializationOriginBindingError("origin authority is invalid") from exc
    if not same_typed_value(descriptor, parsed_descriptor):
        raise InitializationOriginBindingError("descriptor construction is invalid")
    if not same_typed_value(commit, parsed_commit):
        raise InitializationOriginBindingError("commit construction is invalid")
    try:
        validate_descriptor_identity(descriptor, commit)
    except RuntimeError as exc:
        raise InitializationOriginBindingError("origin authority is invalid") from exc
    return descriptor, commit, receipt, operation


def _identity(
    descriptor: ApprovedParentDescriptorV1,
    commit: GenerationCommitV1,
    receipt: InitializationOriginReceiptV1,
    operation: InitializeOperationV1,
) -> None:
    if commit.expected_parent is not None:
        raise InitializationOriginBindingError("origin requires a genesis commit")
    expected_policies = (
        descriptor.policies.execution_policy_id,
        descriptor.policies.repair_policy_id,
        descriptor.policies.quality_policy_id,
        descriptor.policies.fallback_policy_id,
    )
    actual_policies = (
        receipt.policies.initialization_execution_policy_id,
        receipt.policies.repair_policy_id,
        receipt.policies.quality_policy_id,
        receipt.policies.fallback_policy_id,
    )
    expected_operation = (descriptor.identity.unit_id, expected_policies[0])
    actual_operation = (operation.unit_id, operation.execution_policy_id)
    if not same_typed_value(receipt.identity, descriptor.identity):
        raise InitializationOriginBindingError("origin identity card is stale")
    if actual_policies != expected_policies or actual_operation != expected_operation:
        raise InitializationOriginBindingError("origin policy identity is stale")


def _current_card(
    descriptor: ApprovedParentDescriptorV1,
    receipt: InitializationOriginReceiptV1,
) -> None:
    expected = (
        descriptor.plan,
        descriptor.base,
        descriptor.graphics,
        descriptor.output.final,
        descriptor.output.cover,
        descriptor.output.cover_proof,
        descriptor.output.proxy_disposition,
        descriptor.quality,
        descriptor.provenance.runtime_capability_manifest,
    )
    actual = (
        receipt.plan,
        receipt.base,
        receipt.graphics,
        receipt.output.final,
        receipt.output.cover,
        receipt.output.cover_proof,
        receipt.output.proxy_disposition,
        receipt.quality,
        receipt.build_runtime.runtime_capability_manifest,
    )
    if not same_typed_value(actual, expected):
        raise InitializationOriginBindingError("origin current card is stale")


def _operation_authority(
    receipt: InitializationOriginReceiptV1, operation: InitializeOperationV1
) -> None:
    operation_ref = _artifact(
        receipt.operation.artifact.relative_path, operation.document_json
    )
    document = json.loads(operation.document_json)
    snapshot_raw = canonical(document["initializationSnapshot"])
    snapshot_ref = _artifact(
        receipt.operation.snapshot_authority.relative_path, snapshot_raw
    )
    expected = (
        operation_ref,
        operation.operation_digest,
        snapshot_ref,
        operation.snapshot.snapshot_id,
    )
    actual = (
        receipt.operation.artifact,
        receipt.operation.digest,
        receipt.operation.snapshot_authority,
        receipt.operation.snapshot_id,
    )
    if not same_typed_value(actual, expected):
        raise InitializationOriginBindingError("origin operation authority is stale")


def _require_ref(ref: ArtifactRefV1, artifact_class: str, groups: Mapping) -> None:
    matches = tuple(
        row
        for row in groups.get(artifact_class, ())
        if ArtifactRefV1(row.path, row.sha256, row.size_bytes) == ref
    )
    if len(matches) != 1:
        raise InitializationOriginBindingError(
            f"origin artifact does not match class {artifact_class}"
        )


def _manifest(
    descriptor: ApprovedParentDescriptorV1,
    receipt: InitializationOriginReceiptV1,
    groups: Mapping[str, tuple[GenerationManifestRowV1, ...]],
) -> tuple[str, ...]:
    approved = _artifact(groups["approved-parent-v1"][0].path, descriptor.document_json)
    _require_ref(approved, "approved-parent-v1", groups)
    roles = origin_manifest_roles(descriptor, receipt)
    for _name, ref, artifact_class in roles:
        _require_ref(ref, artifact_class, groups)
    manifest_paths = {row.path.casefold() for rows in groups.values() for row in rows}
    uncommitted = (receipt.operation.artifact, receipt.operation.snapshot_authority)
    if any(ref.relative_path.casefold() in manifest_paths for ref in uncommitted):
        raise InitializationOriginBindingError("origin authority aliases an R0 class")
    return tuple(name for name, _ref, _artifact_class in roles)


def _policy_gaps(
    descriptor: ApprovedParentDescriptorV1, operation: InitializeOperationV1
) -> tuple[OperationPolicyGapV1, ...]:
    policy = current_execution_policy()
    ref = _artifact(
        descriptor.provenance.execution_policy.relative_path, policy.document_json
    )
    if ref != descriptor.provenance.execution_policy:
        raise InitializationOriginBindingError("execution policy bytes are stale")
    try:
        binding = bind_operation_execution_policy(operation, policy)
    except RuntimeError as exc:
        raise InitializationOriginBindingError("operation policy is invalid") from exc
    return binding.gaps


def bind_initialization_origin_receipt(
    descriptor: object, commit: object, receipt: object, operation: object
) -> OriginBindingReportV1:
    """Bind current structure, then expose why fixed R0 cannot authorize genesis."""
    descriptor, commit, receipt, operation = _parsed_inputs(
        descriptor, commit, receipt, operation
    )
    _identity(descriptor, commit, receipt, operation)
    _current_card(descriptor, receipt)
    _operation_authority(receipt, operation)
    try:
        groups = verify_r0_generation_profile(commit)
    except RuntimeError as exc:
        raise InitializationOriginBindingError("commit profile is invalid") from exc
    roles = _manifest(descriptor, receipt, groups)
    gaps = _policy_gaps(descriptor, operation)
    return OriginBindingReportV1(
        R0_BLOCKED_STATUS,
        receipt.operation.artifact,
        receipt.operation.snapshot_authority,
        roles,
        R1_PROFILE_REQUIREMENTS,
        gaps,
        UNRESOLVED_ORIGIN_AUTHORITY,
        True,
        True,
        True,
        False,
        False,
        False,
        False,
    )
