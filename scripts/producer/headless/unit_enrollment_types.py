"""Typed proposals and non-authorizing unit-enrollment results."""

from __future__ import annotations

from dataclasses import dataclass

from .unit_enrollment_schema import (
    EnrollmentClockV1,
    EnrollmentOperationEligibilityV1,
    EnrollmentProjectIdentityV1,
    ProspectiveUnitEnrollmentV1,
)

UNIT_ENROLLMENT_STATUS = (
    "STRUCTURAL_PROSPECTIVE_UNIT_ENROLLMENT_V1_NOT_EXECUTION_AUTHORIZED"
)


@dataclass(frozen=True)
class UnitEnrollmentProposalV1:
    """Caller identities fixed before feedback or controller submission."""

    authority_id: str
    enrollment_key: str
    unit_id: str
    clock: EnrollmentClockV1
    project: EnrollmentProjectIdentityV1
    eligibility: EnrollmentOperationEligibilityV1
    enrollment_policy_digest: str


@dataclass(frozen=True)
class UnitEnrollmentRequirementV1:
    """One authority deliberately unavailable from unit enrollment alone."""

    code: str
    required_proof: str


@dataclass(frozen=True)
class UnitEnrollmentBindingV1:
    """Exact enrollment identity with all downstream gates left closed."""

    status: str
    enrollment: ProspectiveUnitEnrollmentV1
    closed_requirements: tuple[str, ...]
    unresolved_authority: tuple[UnitEnrollmentRequirementV1, ...]
    exact_enrollment_bytes_reparsed: bool
    feedback_and_outcome_absent: bool
    clock_identity_bound: bool
    project_lineage_experiment_bound: bool
    operation_eligibility_and_scope_bound: bool
    enrollment_policy_bound: bool
    durable_store_reobserved: bool
    operation_admission_bound: bool
    execution_authorized: bool
    publication_authorized: bool


CLOSED_UNIT_ENROLLMENT_REQUIREMENTS = (
    "EXACT_PROSPECTIVE_ENROLLMENT_BYTES",
    "FEEDBACK_AND_OUTCOME_FIELDS_ABSENT",
    "ENROLLMENT_CLOCK_IDENTITY",
    "PROJECT_LINEAGE_AND_EXPERIMENT_IDENTITY",
    "DECLARED_OPERATION_ELIGIBILITY_AND_SCOPE",
    "IMMUTABLE_ENROLLMENT_POLICY_DIGEST",
)


UNRESOLVED_UNIT_ENROLLMENT_AUTHORITY = (
    UnitEnrollmentRequirementV1(
        "DURABLE_ENROLLMENT_STORE_AND_GLOBAL_UNIT_ARBITRATION",
        "reobserve exact enrollment bytes under the authority-owned shared lock",
    ),
    UnitEnrollmentRequirementV1(
        "OPERATION_DURABLE_ADMISSION_AND_CHILD_BINDING",
        "bind the enrolled unit to one exact durable V3 operation admission",
    ),
    UnitEnrollmentRequirementV1(
        "RUNTIME_EXECUTION_CHILD_SEAL_AND_FENCED_PUBLICATION",
        "execute under trusted runtime authority and fence the sealed child",
    ),
)
