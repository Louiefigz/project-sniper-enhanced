"""Fail-closed binding between exact operations and execution-policy V1."""

from __future__ import annotations

from dataclasses import dataclass

from .generation_policy_documents import (
    ExecutionPolicyV1,
    decode_execution_policy,
)
from .operation_contract import (
    HeadlessMp4OperationV1,
    InitializeOperationV1,
    QualityPassOperationV1,
    validate_headless_mp4_operation_v1,
)
from .quality_receipt_json import same_typed_value


class OperationPolicyError(RuntimeError):
    """An operation is stale or not authorized by its execution policy."""


@dataclass(frozen=True)
class OperationPolicyGapV1:
    """One operation authority missing from execution-policy V1."""

    code: str
    required_field: str


@dataclass(frozen=True)
class OperationPolicyBindingV1:
    """Exact compatibility result for a composition root."""

    operation: str
    execution_policy_id: str
    status: str
    executable: bool
    gaps: tuple[OperationPolicyGapV1, ...]


INITIALIZE_POLICY_GAPS = (
    OperationPolicyGapV1("OPERATION_DISCRIMINANT", "operation=initialize"),
    OperationPolicyGapV1(
        "INITIAL_BASE_BUILD_DISPOSITION",
        "initialBaseBuild=from-presealed-snapshot",
    ),
    OperationPolicyGapV1(
        "INITIALIZATION_SNAPSHOT_AUTHORITY",
        "initializationSnapshot.authorityKind=presealed-immutable-snapshot-v1",
    ),
)


def _policy(value: object) -> ExecutionPolicyV1:
    if type(value) is not ExecutionPolicyV1:
        raise OperationPolicyError("execution policy instance is invalid")
    try:
        parsed = decode_execution_policy(value.document_json)
    except RuntimeError as exc:
        raise OperationPolicyError("execution policy bytes are invalid") from exc
    if not same_typed_value(value, parsed):
        raise OperationPolicyError("execution policy identity is invalid")
    return parsed


def _operation(value: object) -> HeadlessMp4OperationV1:
    try:
        validate_headless_mp4_operation_v1(value)
    except RuntimeError as exc:
        raise OperationPolicyError("operation identity is invalid") from exc
    return value


def bind_operation_execution_policy(
    operation: object, policy: object
) -> OperationPolicyBindingV1:
    """Report exact compatibility; initialize remains blocked under policy V1."""
    operation = _operation(operation)
    policy = _policy(policy)
    if operation.execution_policy_id != policy.policy_id:
        raise OperationPolicyError("operation execution policy ID is stale")
    if type(operation) is QualityPassOperationV1:
        return OperationPolicyBindingV1(
            "quality-pass",
            policy.policy_id,
            "BOUND_QUALITY_PASS_EXECUTION_POLICY_V1",
            True,
            (),
        )
    if type(operation) is InitializeOperationV1:
        return OperationPolicyBindingV1(
            "initialize",
            policy.policy_id,
            "BLOCKED_EXECUTION_POLICY_V1_CANNOT_AUTHORIZE_INITIALIZE",
            False,
            INITIALIZE_POLICY_GAPS,
        )
    raise OperationPolicyError("operation type is unsupported")


def require_executable_operation_policy(
    operation: object, policy: object
) -> OperationPolicyBindingV1:
    """Return only executable bindings; never infer initialization authority."""
    binding = bind_operation_execution_policy(operation, policy)
    if not binding.executable:
        raise OperationPolicyError(binding.status)
    return binding
