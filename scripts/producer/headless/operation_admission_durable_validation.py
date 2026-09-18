"""Exact validation for non-authorizing durable V3 admission results."""

from __future__ import annotations

from .operation_admission_binding import bind_operation_admission_v3
from .operation_admission_store_reader import (
    operation_admission_record_name_v3,
)
from .operation_admission_store_types import (
    DURABLE_OPERATION_ADMISSION_STATUS,
    STORE_CLOSED_REQUIREMENTS,
    STORE_UNRESOLVED_AUTHORITY,
    DurableOperationAdmissionV3,
)
from .operation_admission_types import OperationAdmissionProposalV3
from .operation_admission_schema import OperationAdmissionV3
from .wire_identity import same_wire_value


class DurableOperationAdmissionValidationError(RuntimeError):
    """A durable admission result is malformed or forged."""


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


def validate_durable_operation_admission_v3(value: object) -> None:
    """Rebuild every field without treating the result as a capability."""
    if type(value) is not DurableOperationAdmissionV3:
        raise DurableOperationAdmissionValidationError(
            "durable admission is invalid"
        )
    try:
        binding = value.structural_binding
        structural = bind_operation_admission_v3(
            binding.operation, binding.admission, _proposal(binding.admission)
        )
        expected = DurableOperationAdmissionV3(
            DURABLE_OPERATION_ADMISSION_STATUS,
            value.created,
            operation_admission_record_name_v3(
                binding.admission.idempotency_key
            ),
            structural,
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
    except (RuntimeError, AttributeError, ValueError) as exc:
        raise DurableOperationAdmissionValidationError(
            "durable admission bytes are invalid"
        ) from exc
    if type(value.created) is not bool or not same_wire_value(value, expected):
        raise DurableOperationAdmissionValidationError(
            "durable admission is invalid"
        )
