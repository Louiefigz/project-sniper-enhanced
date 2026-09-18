"""Fail-closed operation/current-parent preflight for the future MP4 root."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from dataclasses import dataclass

from fingerprints import base_plan_digest

from .approved_parent_loader import (
    ApprovedParentLeaseV1,
    load_current_approved_parent,
)
from .approved_parent_media import ApprovedParentVerifierContextV1
from .generation_policy_documents import current_execution_policy
from .operation_contract import (
    QualityPassOperationV1,
    parse_headless_mp4_operation_v1,
)
from .operation_policy import (
    OperationPolicyBindingV1,
    require_executable_operation_policy,
)
from .repair_intent import RepairApplication, apply_repair, current_accent_policy

PREFLIGHT_STATUS = (
    "BOUND_OPERATION_CURRENT_PARENT_AND_REPAIR_CAS_NOT_EXECUTION_AUTHORIZED"
)


class QualityPassPreflightError(RuntimeError):
    """The operation/current-parent boundary is invalid or not executable."""


@dataclass(frozen=True)
class QualityPassPreflightRequirementV1:
    """One downstream authority still required before execution."""

    code: str
    required_proof: str


@dataclass(frozen=True)
class QualityPassPreflightV1:
    """Scoped exact parent plus an explicit non-authorizing preflight result."""

    operation: QualityPassOperationV1
    policy: OperationPolicyBindingV1
    parent: ApprovedParentLeaseV1
    candidate: RepairApplication
    status: str
    unresolved_authority: tuple[QualityPassPreflightRequirementV1, ...]
    execution_authorized: bool


_COMMON_REQUIREMENTS = (
    QualityPassPreflightRequirementV1(
        "PARENT_QUALITY_RUNTIME_REOBSERVATION",
        "independently reobserve final decode and requested-effect evidence",
    ),
    QualityPassPreflightRequirementV1(
        "PARENT_ASSEMBLY_RUNTIME_AUTHORITY",
        "prove assembly lineage, exact runtime/tool execution, media, audio, and YDIF",
    ),
    QualityPassPreflightRequirementV1(
        "RUNTIME_CAPABILITY_EXECUTION_AUTHORITY",
        "bind the exact executable runtime closure used by this operation",
    ),
)
_GENESIS_REQUIREMENT = QualityPassPreflightRequirementV1(
    "R1_INITIALIZATION_ORIGIN_AUTHORITY",
    "represent and verify the selected chain's genesis origin under a versioned profile",
)
_HISTORICAL_REQUIREMENT = QualityPassPreflightRequirementV1(
    "SELECTED_PARENT_LINEAGE_CONTINUITY",
    "resolve the child-signed historical parent and prove base continuity",
)
_ADMISSION_REQUIREMENT = QualityPassPreflightRequirementV1(
    "OPERATION_DURABLE_ADMISSION_AND_CHILD_BINDING",
    "reobserve exact operation bytes, durable admission, and proposed child generation",
)
_UNIT_ENROLLMENT_REQUIREMENT = QualityPassPreflightRequirementV1(
    "UNIT_ENROLLMENT_AUTHORITY",
    "resolve the operation unit through the durable pre-enrollment ledger",
)


def _operation(raw: object) -> QualityPassOperationV1:
    parsed = parse_headless_mp4_operation_v1(raw)
    if type(parsed) is not QualityPassOperationV1:
        raise QualityPassPreflightError("preflight accepts only quality-pass")
    return parsed


def _bind_parent(
    operation: QualityPassOperationV1, lease: ApprovedParentLeaseV1
) -> None:
    request = operation.quality_pass
    parent = lease.parent
    valid = (
        parent.ref == operation.expected_parent
        and request.repair.expected_parent == parent.ref
        and request.repair_policy_id == parent.repair_policy_id
        and request.quality_policy_id == parent.quality_policy_id
        and operation.execution_policy_id == lease.evidence.policies.execution.policy_id
    )
    if not valid:
        raise QualityPassPreflightError("operation differs from approved parent")
    if lease.evidence.quality_evidence.execution_authorized:
        raise QualityPassPreflightError("unexpected parent evidence authority state")


def _candidate(
    operation: QualityPassOperationV1, lease: ApprovedParentLeaseV1
) -> RepairApplication:
    parent = lease.parent
    try:
        application = apply_repair(
            operation.quality_pass.repair,
            parent.ref,
            parent.decoded_plan(),
            current_accent_policy(),
        )
    except RuntimeError as exc:
        raise QualityPassPreflightError("repair CAS is not applicable") from exc
    if base_plan_digest(application.decoded_plan()) != parent.base_projection_digest:
        raise QualityPassPreflightError("repair changed the approved base projection")
    return application


def _requirements(
    lease: ApprovedParentLeaseV1,
) -> tuple[QualityPassPreflightRequirementV1, ...]:
    lineage = (
        ()
        if lease.generation.commit.expected_parent is None
        else (_HISTORICAL_REQUIREMENT,)
    )
    return (
        _GENESIS_REQUIREMENT,
        *lineage,
        _ADMISSION_REQUIREMENT,
        _UNIT_ENROLLMENT_REQUIREMENT,
        *_COMMON_REQUIREMENTS,
    )


@contextlib.contextmanager
def inspect_quality_pass_preflight(
    authority_root: str,
    materialization_root: str,
    operation_json: object,
    verifier: ApprovedParentVerifierContextV1,
) -> Iterator[QualityPassPreflightV1]:
    """Bind operation and current parent while refusing premature execution."""
    stack = contextlib.ExitStack()
    try:
        operation = _operation(operation_json)
        policy = require_executable_operation_policy(
            operation, current_execution_policy()
        )
        parent = stack.enter_context(
            load_current_approved_parent(
                authority_root,
                materialization_root,
                operation.expected_parent,
                verifier,
            )
        )
        _bind_parent(operation, parent)
        candidate = _candidate(operation, parent)
    except QualityPassPreflightError:
        stack.close()
        raise
    except RuntimeError as exc:
        stack.close()
        raise QualityPassPreflightError(str(exc)) from exc
    try:
        yield QualityPassPreflightV1(
            operation,
            policy,
            parent,
            candidate,
            PREFLIGHT_STATUS,
            _requirements(parent),
            False,
        )
    finally:
        stack.close()


def require_execution_authorized(value: QualityPassPreflightV1) -> None:
    """Reject the current structural preflight until all runtime proof exists."""
    raise QualityPassPreflightError(PREFLIGHT_STATUS)
