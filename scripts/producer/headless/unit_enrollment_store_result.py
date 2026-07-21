"""Non-authorizing durable result projection for unit enrollment."""

from __future__ import annotations

from .unit_enrollment_binding import bind_prospective_unit_enrollment_v1
from .unit_enrollment_schema import ProspectiveUnitEnrollmentV1
from .unit_enrollment_store_types import (
    DURABLE_UNIT_ENROLLMENT_STATUS,
    STORE_CLOSED_UNIT_ENROLLMENT_REQUIREMENTS,
    STORE_UNRESOLVED_UNIT_ENROLLMENT_AUTHORITY,
    DurableUnitEnrollmentV1,
)


def durable_unit_enrollment_result(
    created: bool, record_id: str, enrollment: ProspectiveUnitEnrollmentV1
) -> DurableUnitEnrollmentV1:
    """Project retained enrollment bytes without execution authority."""
    binding = bind_prospective_unit_enrollment_v1(enrollment)
    return DurableUnitEnrollmentV1(
        DURABLE_UNIT_ENROLLMENT_STATUS,
        created,
        record_id,
        binding,
        STORE_CLOSED_UNIT_ENROLLMENT_REQUIREMENTS,
        STORE_UNRESOLVED_UNIT_ENROLLMENT_AUTHORITY,
        True,
        True,
        True,
        False,
        False,
        False,
    )
