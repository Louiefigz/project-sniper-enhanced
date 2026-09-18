"""Non-authorizing durable prospective unit-enrollment store results."""

from __future__ import annotations

from dataclasses import dataclass

from .unit_enrollment_schema import ProspectiveUnitEnrollmentV1
from .unit_enrollment_types import (
    CLOSED_UNIT_ENROLLMENT_REQUIREMENTS,
    UNRESOLVED_UNIT_ENROLLMENT_AUTHORITY,
    UnitEnrollmentBindingV1,
    UnitEnrollmentRequirementV1,
)

DURABLE_UNIT_ENROLLMENT_STATUS = "DURABLE_PROSPECTIVE_UNIT_ENROLLMENT_V1_REOBSERVED_NOT_EXECUTION_AUTHORIZED"


@dataclass(frozen=True)
class UnitEnrollmentStoreRequestV1:
    """One exact enrollment submitted to an authority-owned durable root."""

    authority_root: str
    enrollment: ProspectiveUnitEnrollmentV1


@dataclass(frozen=True)
class UnitEnrollmentReadRequestV1:
    """Stable identity required to read without creating enrollment state."""

    authority_root: str
    authority_id: str
    enrollment_key: str


@dataclass(frozen=True)
class DurableUnitEnrollmentV1:
    """Reobserved enrollment and global unit arbitration, never a capability."""

    status: str
    created: bool
    record_id: str
    structural_binding: UnitEnrollmentBindingV1
    closed_requirements: tuple[str, ...]
    unresolved_authority: tuple[UnitEnrollmentRequirementV1, ...]
    enrollment_bytes_reobserved: bool
    replay_arbitrated: bool
    global_unit_uniqueness_verified: bool
    operation_admission_bound: bool
    execution_authorized: bool
    publication_authorized: bool


STORE_CLOSED_UNIT_ENROLLMENT_REQUIREMENTS = (
    CLOSED_UNIT_ENROLLMENT_REQUIREMENTS
    + ("DURABLE_ENROLLMENT_STORE_AND_GLOBAL_UNIT_ARBITRATION",)
)


STORE_UNRESOLVED_UNIT_ENROLLMENT_AUTHORITY = tuple(
    requirement
    for requirement in UNRESOLVED_UNIT_ENROLLMENT_AUTHORITY
    if requirement.code
    != "DURABLE_ENROLLMENT_STORE_AND_GLOBAL_UNIT_ARBITRATION"
)
