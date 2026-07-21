"""Exact-value validation for durable fence reservation diagnostics."""

from __future__ import annotations

from .fence_admission_reservation_records import (
    fence_admission_reservation_record_name_v1,
)
from .fence_admission_reservation_schema import (
    FenceAdmissionReservationSchemaError,
    validate_fence_admission_reservation_v1,
)
from .fence_admission_reservation_types import (
    FENCE_ADMISSION_RESERVATION_STATUS,
    DurableFenceAdmissionReservationV1,
)
from .wire_identity import same_wire_value


class DurableFenceAdmissionReservationValidationError(RuntimeError):
    """A durable reservation result is malformed or forged."""


def validate_durable_fence_admission_reservation_v1(value: object) -> None:
    """Rebuild all non-authorizing result fields from exact record bytes."""
    if type(value) is not DurableFenceAdmissionReservationV1:
        raise DurableFenceAdmissionReservationValidationError(
            "durable fence admission reservation is invalid"
        )
    try:
        validate_fence_admission_reservation_v1(value.reservation)
        expected = DurableFenceAdmissionReservationV1(
            FENCE_ADMISSION_RESERVATION_STATUS,
            value.created,
            fence_admission_reservation_record_name_v1(
                value.reservation.attempt_id
            ),
            value.reservation,
            True,
            True,
            False,
            False,
        )
    except (FenceAdmissionReservationSchemaError, RuntimeError) as exc:
        raise DurableFenceAdmissionReservationValidationError(
            "durable fence admission reservation bytes are invalid"
        ) from exc
    if type(value.created) is not bool or not same_wire_value(value, expected):
        raise DurableFenceAdmissionReservationValidationError(
            "durable fence admission reservation is invalid"
        )
