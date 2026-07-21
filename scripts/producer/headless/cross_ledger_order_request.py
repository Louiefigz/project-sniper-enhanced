"""Exact hostile-input normalization for cross-ledger order requests."""

from __future__ import annotations

from .cross_ledger_order_schema import (
    CrossLedgerOrderIdentityV1,
    build_cross_ledger_order_identity_v1,
)
from .cross_ledger_order_types import (
    CrossLedgerOrderError,
    CrossLedgerOrderRequestV1,
)
from .operation_admission_binding import (
    OperationAdmissionBindingError,
    bind_operation_admission_v3,
)
from .operation_admission_store_reader import (
    operation_admission_record_name_v3,
)
from .operation_admission_store_types import OperationAdmissionStoreRequestV3
from .unit_enrollment_admission_binding import (
    UnitEnrollmentAdmissionBindingError,
    require_prospective_enrollment_matches_admission_v1,
)
from .unit_enrollment_durable_validation import (
    DurableUnitEnrollmentValidationError,
    validate_durable_unit_enrollment_v1,
)
from .unit_enrollment_store_types import DurableUnitEnrollmentV1


def checked_cross_ledger_order_request_v1(
    value: object,
) -> CrossLedgerOrderRequestV1:
    """Normalize every exact-type request failure into the public error."""
    if type(value) is not CrossLedgerOrderRequestV1:
        raise CrossLedgerOrderError("cross-ledger order request is invalid")
    valid_fields = (
        type(value.authority_root) is str
        and type(value.enrollment) is DurableUnitEnrollmentV1
        and type(value.admission) is OperationAdmissionStoreRequestV3
        and type(value.admission.authority_root) is str
    )
    if not valid_fields:
        raise CrossLedgerOrderError("cross-ledger order request is invalid")
    try:
        validate_durable_unit_enrollment_v1(value.enrollment)
        bind_operation_admission_v3(
            value.admission.operation,
            value.admission.admission,
            value.admission.proposal,
        )
        retained = value.enrollment.structural_binding.enrollment
        require_prospective_enrollment_matches_admission_v1(
            retained,
            value.admission.operation,
            value.admission.admission,
        )
    except (
        DurableUnitEnrollmentValidationError,
        OperationAdmissionBindingError,
        UnitEnrollmentAdmissionBindingError,
        AttributeError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
        RuntimeError,
    ) as exc:
        raise CrossLedgerOrderError(
            "cross-ledger identities are invalid"
        ) from exc
    if value.authority_root != value.admission.authority_root:
        raise CrossLedgerOrderError("cross-ledger authority roots disagree")
    return value


def build_cross_ledger_order_request_identity_v1(
    value: object,
) -> CrossLedgerOrderIdentityV1:
    """Build exact order identity only from one normalized request."""
    request = checked_cross_ledger_order_request_v1(value)
    enrollment = request.enrollment.structural_binding.enrollment
    admission = request.admission.admission
    values = (
        enrollment.authority_id,
        enrollment.unit_id,
        enrollment.enrollment_key,
        request.enrollment.record_id,
        enrollment.enrollment_digest,
        admission.idempotency_key,
        admission.attempt_id,
        admission.intended_child_generation_id,
        operation_admission_record_name_v3(admission.idempotency_key),
        admission.admission_digest,
    )
    return build_cross_ledger_order_identity_v1(values)
