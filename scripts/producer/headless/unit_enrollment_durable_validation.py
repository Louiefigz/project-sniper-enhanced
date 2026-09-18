"""Exact-value validation for durable unit-enrollment diagnostics."""

from __future__ import annotations

import hashlib

from .unit_enrollment_binding import bind_prospective_unit_enrollment_v1
from .unit_enrollment_store_types import (
    DURABLE_UNIT_ENROLLMENT_STATUS,
    STORE_CLOSED_UNIT_ENROLLMENT_REQUIREMENTS,
    STORE_UNRESOLVED_UNIT_ENROLLMENT_AUTHORITY,
    DurableUnitEnrollmentV1,
)
from .wire_identity import same_wire_value

_RECORD_DOMAIN = b"sniper-unit-enrollment-record-v1\0"


class DurableUnitEnrollmentValidationError(RuntimeError):
    """Durable enrollment diagnostics are malformed or forged."""


def _record_id(enrollment_key: str) -> str:
    return hashlib.sha256(
        _RECORD_DOMAIN + enrollment_key.encode("ascii")
    ).hexdigest()


def validate_durable_unit_enrollment_v1(value: object) -> None:
    """Validate every field without claiming current disk presence."""
    if (
        type(value) is not DurableUnitEnrollmentV1
        or type(value.created) is not bool
    ):
        raise DurableUnitEnrollmentValidationError(
            "durable unit enrollment is invalid"
        )
    try:
        structural = bind_prospective_unit_enrollment_v1(
            value.structural_binding.enrollment
        )
    except (RuntimeError, AttributeError) as exc:
        raise DurableUnitEnrollmentValidationError(
            "durable unit enrollment is invalid"
        ) from exc
    expected = DurableUnitEnrollmentV1(
        DURABLE_UNIT_ENROLLMENT_STATUS,
        value.created,
        _record_id(structural.enrollment.enrollment_key),
        structural,
        STORE_CLOSED_UNIT_ENROLLMENT_REQUIREMENTS,
        STORE_UNRESOLVED_UNIT_ENROLLMENT_AUTHORITY,
        True,
        True,
        True,
        False,
        False,
        False,
    )
    if not same_wire_value(value, expected):
        raise DurableUnitEnrollmentValidationError(
            "durable unit enrollment is invalid"
        )
