"""Bind one reobserved enrollment to one durable V3 operation admission."""

from __future__ import annotations

import datetime as dt

from .operation_admission_binding import bind_operation_admission_v3
from .operation_admission_schema import (
    OperationAdmissionV3,
    validate_operation_admission_v3,
)
from .operation_admission_durable_validation import (
    DurableOperationAdmissionValidationError,
    validate_durable_operation_admission_v3,
)
from .operation_admission_store_types import DurableOperationAdmissionV3
from .operation_admission_types import OperationAdmissionProposalV3
from .operation_contract import (
    InitializeOperationV1,
    QualityPassOperationV1,
    validate_headless_mp4_operation_v1,
)
from .unit_enrollment_admission_types import (
    ENROLLED_ADMISSION_STATUS,
    UNIT_ENROLLMENT_AUTHORITY,
    ReobservedUnitEnrollmentAdmissionBindingV1,
)
from .unit_enrollment_admission_validation import (
    enrolled_admission_unresolved_v1,
)
from .unit_enrollment_binding import project_lineage_digest_for_operation
from .unit_enrollment_durable_validation import (
    DurableUnitEnrollmentValidationError,
    validate_durable_unit_enrollment_v1,
)
from .unit_enrollment_schema import (
    ProspectiveUnitEnrollmentV1,
    validate_prospective_unit_enrollment_v1,
)
from .unit_enrollment_store_types import DurableUnitEnrollmentV1


class UnitEnrollmentAdmissionBindingError(RuntimeError):
    """Durable enrollment and durable V3 admission do not describe one unit."""


def _proposal(admission: OperationAdmissionV3) -> OperationAdmissionProposalV3:
    return OperationAdmissionProposalV3(
        admission.authority_id,
        admission.idempotency_key,
        admission.attempt_id,
        admission.intended_child_generation_id,
        admission.unit_id,
        admission.expected_parent,
        admission.first_submitted_at,
        admission.release_id,
        admission.build_id,
        admission.execution_policy_id,
    )


def _durable_enrollment(value: object) -> DurableUnitEnrollmentV1:
    try:
        validate_durable_unit_enrollment_v1(value)
    except DurableUnitEnrollmentValidationError as exc:
        raise UnitEnrollmentAdmissionBindingError(
            "durable enrollment is invalid"
        ) from exc
    return value


def _durable_admission(value: object) -> DurableOperationAdmissionV3:
    try:
        validate_durable_operation_admission_v3(value)
    except DurableOperationAdmissionValidationError as exc:
        raise UnitEnrollmentAdmissionBindingError(
            "durable admission is invalid"
        ) from exc
    return value


def _operation_values(operation: object) -> tuple[str, str]:
    if type(operation) is InitializeOperationV1:
        return "initialize", ""
    if type(operation) is QualityPassOperationV1:
        return "quality-pass", "graphicsTrack"
    raise UnitEnrollmentAdmissionBindingError(
        "durable operation kind is invalid"
    )


def _clock_not_after(enrolled_at: str, submitted_at: str) -> bool:
    enrolled = dt.datetime.strptime(enrolled_at, "%Y-%m-%dT%H:%M:%SZ")
    submitted = dt.datetime.strptime(submitted_at, "%Y-%m-%dT%H:%M:%SZ")
    return enrolled <= submitted


def _bind_exact_values(
    enrollment: ProspectiveUnitEnrollmentV1,
    admission: OperationAdmissionV3,
    operation: object,
) -> None:
    kind, lane = _operation_values(operation)
    eligibility = enrollment.eligibility
    identity_valid = (
        enrollment.authority_id == admission.authority_id
        and enrollment.unit_id == admission.unit_id
        and enrollment.project.project_lineage_digest
        == project_lineage_digest_for_operation(operation)
    )
    route_valid = (
        eligibility.operation == kind
        and (kind == "initialize" or lane in eligibility.allowed_lanes)
        and eligibility.release_id == admission.release_id
        and eligibility.build_id == admission.build_id
        and eligibility.execution_policy_id == admission.execution_policy_id
    )
    if not identity_valid or not route_valid:
        raise UnitEnrollmentAdmissionBindingError(
            "unit enrollment and admission identity disagree"
        )
    if not _clock_not_after(
        enrollment.clock.observed_at, admission.first_submitted_at
    ):
        raise UnitEnrollmentAdmissionBindingError(
            "enrollment clock is after first submission"
        )


def require_prospective_enrollment_matches_admission_v1(
    enrollment: object,
    operation: object,
    admission: object,
) -> None:
    """Reject mismatched enrollment before durable admission begins."""
    try:
        validate_prospective_unit_enrollment_v1(enrollment)
        validate_headless_mp4_operation_v1(operation)
        validate_operation_admission_v3(admission)
        bind_operation_admission_v3(operation, admission, _proposal(admission))
        _bind_exact_values(enrollment, admission, operation)
    except UnitEnrollmentAdmissionBindingError:
        raise
    except RuntimeError as exc:
        raise UnitEnrollmentAdmissionBindingError(
            "prospective enrollment and admission are invalid"
        ) from exc


def bind_reobserved_unit_enrollment_to_admission_v1(
    enrollment: object,
    admission: object,
) -> ReobservedUnitEnrollmentAdmissionBindingV1:
    """Close only unit enrollment after both durable records are reobserved."""
    enrolled = _durable_enrollment(enrollment)
    admitted = _durable_admission(admission)
    record = enrolled.structural_binding.enrollment
    admission_record = admitted.structural_binding.admission
    _bind_exact_values(
        record, admission_record, admitted.structural_binding.operation
    )
    return ReobservedUnitEnrollmentAdmissionBindingV1(
        ENROLLED_ADMISSION_STATUS,
        record.unit_id,
        record.enrollment_digest,
        admission_record.admission_digest,
        record.enrollment_policy_digest,
        record.project.project_identity_digest,
        record.project.experiment_identity_digest,
        (UNIT_ENROLLMENT_AUTHORITY,),
        enrolled_admission_unresolved_v1(),
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        False,
        False,
        False,
    )


def require_enrolled_admission_execution_authorized(value: object) -> None:
    """Never treat enrolled-admission diagnostics as execution authority."""
    if type(value) is not ReobservedUnitEnrollmentAdmissionBindingV1:
        raise UnitEnrollmentAdmissionBindingError(
            "enrolled admission is invalid"
        )
    raise UnitEnrollmentAdmissionBindingError(ENROLLED_ADMISSION_STATUS)
