"""Non-authorizing result construction for durable V3 admissions."""

from __future__ import annotations

from .operation_admission_binding import bind_operation_admission_v3
from .operation_admission_schema import OperationAdmissionV3
from .operation_admission_store_types import (
    DURABLE_OPERATION_ADMISSION_STATUS,
    STORE_CLOSED_REQUIREMENTS,
    STORE_UNRESOLVED_AUTHORITY,
    DurableOperationAdmissionV3,
)
from .operation_admission_types import OperationAdmissionProposalV3


def _proposal(admission: OperationAdmissionV3) -> OperationAdmissionProposalV3:
    return OperationAdmissionProposalV3(
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


def durable_operation_admission_result(
    created: bool, record: object
) -> DurableOperationAdmissionV3:
    """Construct a result whose execution and publication gates stay false."""
    name = record.name
    admission = record.admission
    operation = record.operation
    binding = bind_operation_admission_v3(
        operation, admission, _proposal(admission)
    )
    return DurableOperationAdmissionV3(
        DURABLE_OPERATION_ADMISSION_STATUS,
        created,
        name,
        binding,
        STORE_CLOSED_REQUIREMENTS,
        STORE_UNRESOLVED_AUTHORITY,
        True,
        True,
        True,
        False,
        False,
        False,
        False,
    )
