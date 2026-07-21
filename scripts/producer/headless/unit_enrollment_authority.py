"""Fail-closed authority guard for durable prospective enrollment."""

from __future__ import annotations

from .unit_enrollment_store_errors import UnitEnrollmentStoreError
from .unit_enrollment_store_types import (
    DURABLE_UNIT_ENROLLMENT_STATUS,
    DurableUnitEnrollmentV1,
)


def require_durable_unit_enrollment_execution_authorized(
    value: object,
) -> None:
    """Never promote durable enrollment evidence into render authority."""
    if type(value) is not DurableUnitEnrollmentV1:
        raise UnitEnrollmentStoreError("durable unit enrollment is invalid")
    raise UnitEnrollmentStoreError(DURABLE_UNIT_ENROLLMENT_STATUS)
