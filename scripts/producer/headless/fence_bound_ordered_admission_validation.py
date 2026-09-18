"""Exact validation for the composed work-disabled admission evidence."""

from __future__ import annotations

from .active_fence_validation import (
    validate_active_fence_operation_result_v1,
)
from .cross_ledger_order_validation import (
    validate_durable_cross_ledger_ordered_admission_v1,
)
from .fence_admission_reservation_validation import (
    validate_durable_fence_admission_reservation_v1,
)
from .fence_bound_ordered_admission_types import (
    FENCE_BOUND_ORDERED_ADMISSION_STATUS,
    WorkDisabledFenceBoundOrderedAdmissionV1,
)
from .fence_order_start_validation import (
    validate_durable_fence_order_start_v1,
)
from .unit_enrollment_durable_validation import (
    validate_durable_unit_enrollment_v1,
)
from .wire_identity import same_wire_value


class FenceBoundOrderedAdmissionValidationError(RuntimeError):
    """Composed admission evidence is malformed, mismatched, or forged."""


def _validate_nested(value: WorkDisabledFenceBoundOrderedAdmissionV1) -> None:
    try:
        validate_durable_unit_enrollment_v1(value.enrollment)
        validate_durable_fence_admission_reservation_v1(value.reservation)
        validate_active_fence_operation_result_v1(value.fence)
        validate_durable_fence_order_start_v1(value.start_intent)
        validate_durable_cross_ledger_ordered_admission_v1(
            value.ordered_admission
        )
    except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
        raise FenceBoundOrderedAdmissionValidationError(
            "fence-bound nested evidence is invalid"
        ) from exc


def _reservation_binding(reservation: object, identity: object, admission: object) -> bool:
    return (
        reservation.authority_id == identity.authority_id
        and reservation.attempt_id == identity.attempt_id
        and reservation.idempotency_key == identity.idempotency_key
        and reservation.enrollment_key == identity.enrollment_key
        and reservation.admission_digest == identity.admission_digest
        and reservation.unit_id == identity.unit_id
        and reservation.intended_child_generation_id
        == identity.intended_child_generation_id
        and reservation.enrollment_digest == identity.enrollment_digest
        and reservation.order_identity_digest == identity.order_identity_digest
        and reservation.request_identity_digest
        == admission.request_identity_digest
    )


def _bindings(value: WorkDisabledFenceBoundOrderedAdmissionV1) -> bool:
    ordered = value.ordered_admission
    identity = ordered.intent.identity
    admission = ordered.admission.structural_binding.admission
    reservation = value.reservation.reservation
    start = value.start_intent.intent
    fence = value.fence.state
    enrollment_exact = (
        value.enrollment.record_id == ordered.enrollment.record_id
        and same_wire_value(
            value.enrollment.structural_binding,
            ordered.enrollment.structural_binding,
        )
    )
    return (
        enrollment_exact
        and _reservation_binding(reservation, identity, admission)
        and reservation.reservation_digest == start.reservation_digest
        and start.order_identity_digest == identity.order_identity_digest
        and reservation.authority_id == fence.authority_id
        and reservation.authority_id == identity.authority_id
        and start.authority_id == identity.authority_id
        and reservation.attempt_id == fence.active_attempt_id
        and reservation.attempt_id == identity.attempt_id
        and start.fence_revision == fence.fence_revision
        and start.fence_token == fence.fence_token
        and start.active_attempt_id == fence.active_attempt_id
        and value.fence.operation == "RESERVE"
    )


def _expected(
    value: WorkDisabledFenceBoundOrderedAdmissionV1,
) -> WorkDisabledFenceBoundOrderedAdmissionV1:
    return WorkDisabledFenceBoundOrderedAdmissionV1(
        FENCE_BOUND_ORDERED_ADMISSION_STATUS,
        value.enrollment,
        value.reservation,
        value.fence,
        value.start_intent,
        value.ordered_admission,
        value.enrollment.created,
        True,
        True,
        True,
        True,
        value.ordered_admission.order_created,
        True,
    )


def validate_fence_bound_ordered_admission_v1(value: object) -> None:
    """Validate nested identities, derived claims, and denied authorities."""
    if type(value) is not WorkDisabledFenceBoundOrderedAdmissionV1:
        raise FenceBoundOrderedAdmissionValidationError(
            "fence-bound ordered admission is invalid"
        )
    _validate_nested(value)
    try:
        expected = _expected(value)
        exact = same_wire_value(value, expected)
        bound = _bindings(value)
    except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
        raise FenceBoundOrderedAdmissionValidationError(
            "fence-bound ordered admission cannot be rebuilt"
        ) from exc
    if not exact or not bound:
        raise FenceBoundOrderedAdmissionValidationError(
            "fence-bound ordered admission is invalid"
        )
