"""Bind one parsed MP4 operation to exact V3 admission and child identities."""

from __future__ import annotations

import hashlib

from . import quality_receipt_json as wire
from .operation_admission_schema import (
    OperationAdmissionV3,
    QualityRequestIdentityV3,
    parse_operation_admission_v3,
    request_identity_digest_v3,
    validate_operation_admission_v3,
)
from .operation_admission_types import (
    CLOSED_OPERATION_ADMISSION_REQUIREMENTS,
    OPERATION_ADMISSION_STATUS,
    UNRESOLVED_OPERATION_ADMISSION_AUTHORITY,
    OperationAdmissionBindingV3,
    OperationAdmissionProposalV3,
)
from .operation_contract import (
    HeadlessMp4OperationV1,
    InitializeOperationV1,
    QualityPassOperationV1,
    validate_headless_mp4_operation_v1,
)
from .operation_wire import canonical, parent_document


class OperationAdmissionBindingError(RuntimeError):
    """Operation, durable admission bytes, or proposed identity disagree."""


def _kind(operation: HeadlessMp4OperationV1) -> str:
    if type(operation) is InitializeOperationV1:
        return "initialize"
    if type(operation) is QualityPassOperationV1:
        return "quality-pass"
    raise OperationAdmissionBindingError("operation type is invalid")


def _quality_identity(
    operation: HeadlessMp4OperationV1,
) -> QualityRequestIdentityV3 | None:
    if type(operation) is InitializeOperationV1:
        return None
    if type(operation) is not QualityPassOperationV1:
        raise OperationAdmissionBindingError("operation type is invalid")
    quality = operation.quality_pass
    return QualityRequestIdentityV3(
        quality.request_digest, quality.repair.request_id
    )


def _artifact_document(operation: HeadlessMp4OperationV1, path: str) -> dict:
    return {
        "path": path,
        "sha256": hashlib.sha256(operation.document_json).hexdigest(),
        "sizeBytes": len(operation.document_json),
    }


def _proposal_document(
    operation: HeadlessMp4OperationV1,
    proposal: OperationAdmissionProposalV3,
    operation_path: str,
) -> dict:
    parent = (
        None
        if proposal.expected_parent is None
        else parent_document(proposal.expected_parent)
    )
    quality = _quality_identity(operation)
    quality_document = None
    if quality is not None:
        quality_document = {
            "repairRequestId": quality.repair_request_id,
            "requestDigest": quality.request_digest,
        }
    return {
        "schemaVersion": 3,
        "authorityKind": "operation-admission-v3",
        "realizationKind": "deterministic-mp4",
        "authorityId": proposal.authority_id,
        "idempotencyKey": proposal.idempotency_key,
        "attemptId": proposal.attempt_id,
        "intendedChildGenerationId": proposal.intended_child_generation_id,
        "unitId": proposal.unit_id,
        "firstSubmittedAt": proposal.first_submitted_at,
        "releaseId": proposal.release_id,
        "buildId": proposal.build_id,
        "executionPolicyId": proposal.execution_policy_id,
        "expectedParent": parent,
        "operation": {
            "kind": _kind(operation),
            "artifact": _artifact_document(operation, operation_path),
            "operationDigest": operation.operation_digest,
        },
        "qualityRequest": quality_document,
    }


def build_operation_admission_v3(
    operation: object,
    proposal: OperationAdmissionProposalV3,
    operation_path: str,
) -> OperationAdmissionV3:
    """Create exact V3 bytes from a reparsed operation and proposed identities."""
    try:
        validate_headless_mp4_operation_v1(operation)
    except RuntimeError as exc:
        raise OperationAdmissionBindingError("operation is invalid") from exc
    if type(proposal) is not OperationAdmissionProposalV3:
        raise OperationAdmissionBindingError("admission proposal is invalid")
    try:
        document = _proposal_document(operation, proposal, operation_path)
        document["requestIdentityDigest"] = request_identity_digest_v3(
            document
        )
        admission = parse_operation_admission_v3(canonical(document))
        _bind_values(operation, admission, proposal)
    except (RuntimeError, AttributeError, TypeError, ValueError) as exc:
        raise OperationAdmissionBindingError(
            "admission proposal is invalid"
        ) from exc
    return admission


def _proposal_values(proposal: OperationAdmissionProposalV3) -> tuple:
    return (
        proposal.authority_id,
        proposal.idempotency_key,
        proposal.attempt_id,
        proposal.intended_child_generation_id,
        proposal.unit_id,
        proposal.expected_parent,
        proposal.first_submitted_at,
        proposal.release_id,
        proposal.build_id,
        proposal.execution_policy_id,
    )


def _admission_values(admission: OperationAdmissionV3) -> tuple:
    return (
        admission.authority_id,
        admission.idempotency_key,
        admission.attempt_id,
        admission.intended_child_generation_id,
        admission.unit_id,
        admission.expected_parent,
        admission.first_submitted_at,
        admission.release_id,
        admission.build_id,
        admission.execution_policy_id,
    )


def _bind_values(
    operation: HeadlessMp4OperationV1,
    admission: OperationAdmissionV3,
    proposal: OperationAdmissionProposalV3,
) -> None:
    expected_artifact = (
        len(operation.document_json),
        hashlib.sha256(operation.document_json).hexdigest(),
        operation.operation_digest,
        _kind(operation),
    )
    actual_artifact = (
        admission.operation.artifact.size_bytes,
        admission.operation.artifact.sha256,
        admission.operation.operation_digest,
        admission.operation.kind,
    )
    operation_values = (
        operation.unit_id,
        operation.expected_parent,
        operation.execution_policy_id,
        _quality_identity(operation),
    )
    admitted_values = (
        admission.unit_id,
        admission.expected_parent,
        admission.execution_policy_id,
        admission.quality_request,
    )
    valid = (
        wire.same_typed_value(expected_artifact, actual_artifact)
        and wire.same_typed_value(operation_values, admitted_values)
        and wire.same_typed_value(
            _proposal_values(proposal), _admission_values(admission)
        )
    )
    if not valid:
        raise OperationAdmissionBindingError(
            "operation admission binding is stale"
        )


def bind_operation_admission_v3(
    operation: object,
    admission: object,
    proposal: object,
) -> OperationAdmissionBindingV3:
    """Bind operation, exact admission bytes, and child without authorizing work."""
    if type(proposal) is not OperationAdmissionProposalV3:
        raise OperationAdmissionBindingError("admission proposal is invalid")
    try:
        validate_headless_mp4_operation_v1(operation)
        validate_operation_admission_v3(admission)
        _bind_values(operation, admission, proposal)
    except (RuntimeError, AttributeError, TypeError, ValueError) as exc:
        raise OperationAdmissionBindingError(
            "operation admission is invalid"
        ) from exc
    return OperationAdmissionBindingV3(
        OPERATION_ADMISSION_STATUS,
        operation,
        admission,
        admission.intended_child_generation_id,
        CLOSED_OPERATION_ADMISSION_REQUIREMENTS,
        UNRESOLVED_OPERATION_ADMISSION_AUTHORITY,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        False,
        False,
        False,
        False,
    )


def require_operation_admission_execution_authorized(value: object) -> None:
    """Never treat structural V3 admission binding as execution authority."""
    if type(value) is not OperationAdmissionBindingV3:
        raise OperationAdmissionBindingError(
            "operation admission binding is invalid"
        )
    raise OperationAdmissionBindingError(OPERATION_ADMISSION_STATUS)
