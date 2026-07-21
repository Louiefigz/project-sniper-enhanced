"""Diagnostics from binding durable enrollment to durable V3 admission."""

from __future__ import annotations

from dataclasses import dataclass

from .operation_admission_types import OperationAdmissionRequirementV3

ENROLLED_ADMISSION_STATUS = (
    "DURABLE_UNIT_ENROLLMENT_BOUND_TO_V3_ADMISSION_NOT_EXECUTION_AUTHORIZED"
)
ORDERED_ENROLLED_ADMISSION_STATUS = (
    "DURABLE_UNIT_ENROLLMENT_ORDERED_BEFORE_V3_ADMISSION_"
    "NOT_EXECUTION_AUTHORIZED"
)
UNIT_ENROLLMENT_AUTHORITY = "UNIT_ENROLLMENT_AUTHORITY"
CROSS_LEDGER_PROSPECTIVE_ORDER = (
    "DURABLE_CROSS_LEDGER_PROSPECTIVE_ORDER_RECEIPT"
)


@dataclass(frozen=True)
class ReobservedUnitEnrollmentAdmissionBindingV1:
    """Proof that one retained admission matches its enrollment."""

    status: str
    unit_id: str
    enrollment_digest: str
    admission_digest: str
    enrollment_policy_digest: str
    project_identity_digest: str
    experiment_identity_digest: str
    closed_requirements: tuple[str, ...]
    unresolved_authority: tuple[OperationAdmissionRequirementV3, ...]
    enrollment_bytes_reobserved: bool
    admission_and_operation_bytes_reobserved: bool
    global_unit_uniqueness_verified: bool
    authority_unit_and_lineage_bound: bool
    enrollment_clock_not_after_first_submission: bool
    operation_eligibility_and_scope_bound: bool
    release_build_and_policy_bound: bool
    cross_ledger_order_receipt_verified: bool
    execution_authorized: bool
    publication_authorized: bool
