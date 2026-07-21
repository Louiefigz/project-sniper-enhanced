"""Types for enrolled, durably admitted quality-pass inspection."""

from __future__ import annotations

from dataclasses import dataclass

from .admitted_quality_pass_composition_types import (
    AdmittedQualityPassCompositionRequestV1,
    NonAuthorizingAdmittedQualityPassCompositionV1,
)
from .quality_pass_composition_types import CompositionAuthorityRequirementV1
from .unit_enrollment_schema import ProspectiveUnitEnrollmentV1

ENROLLED_ADMITTED_COMPOSITION_STATUS = (
    "UNIT_ENROLLMENT_AND_ORDERED_DURABLE_ADMISSION_BOUND_"
    "NOT_EXECUTION_AUTHORIZED"
)


class EnrolledAdmittedQualityPassCompositionError(RuntimeError):
    """Enrollment, admission, and composition did not form one exact unit."""


@dataclass(frozen=True)
class EnrolledAdmittedQualityPassCompositionRequestV1:
    """Prospective enrollment plus the existing exact admitted request."""

    enrollment: ProspectiveUnitEnrollmentV1
    admitted: AdmittedQualityPassCompositionRequestV1


@dataclass(frozen=True)
class NonAuthorizingEnrolledAdmittedQualityPassCompositionV1:
    """Diagnostics after enrollment and admission reobservation."""

    status: str
    unit_id: str
    enrollment_digest: str
    enrollment_policy_digest: str
    project_identity_digest: str
    experiment_identity_digest: str
    admission_digest: str
    request_identity_digest: str
    intended_child_generation_id: str
    enrollment_created: bool
    admission_created: bool
    newly_closed_checks: tuple[str, ...]
    unresolved_authority: tuple[CompositionAuthorityRequirementV1, ...]
    admitted_composition: NonAuthorizingAdmittedQualityPassCompositionV1
    enrollment_bytes_reobserved: bool
    admission_and_operation_bytes_reobserved: bool
    global_unit_uniqueness_verified: bool
    enrollment_clock_not_after_first_submission: bool
    operation_eligibility_and_scope_bound: bool
    unit_enrollment_verified: bool
    cross_ledger_order_receipt_verified: bool
    operation_runtime_verified: bool
    fence_rechecked: bool
    execution_authorized: bool
    publication_authorized: bool
