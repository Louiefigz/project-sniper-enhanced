"""Exact validation for non-authorizing enrolled-admission diagnostics."""

from __future__ import annotations

from . import quality_receipt_json as wire
from .operation_admission_store_types import STORE_UNRESOLVED_AUTHORITY
from .operation_admission_types import OperationAdmissionRequirementV3
from .unit_enrollment_admission_types import (
    CROSS_LEDGER_PROSPECTIVE_ORDER,
    ENROLLED_ADMISSION_STATUS,
    ORDERED_ENROLLED_ADMISSION_STATUS,
    UNIT_ENROLLMENT_AUTHORITY,
    ReobservedUnitEnrollmentAdmissionBindingV1,
)
from .wire_identity import same_wire_value


class UnitEnrollmentAdmissionValidationError(RuntimeError):
    """Enrolled-admission diagnostics are malformed or forged."""


def enrolled_admission_unresolved_v1() -> (
    tuple[OperationAdmissionRequirementV3, ...]
):
    """Return the exact authority remaining after enrollment binding."""
    retained = tuple(
        row
        for row in STORE_UNRESOLVED_AUTHORITY
        if row.code != UNIT_ENROLLMENT_AUTHORITY
    )
    return retained + (
        OperationAdmissionRequirementV3(
            CROSS_LEDGER_PROSPECTIVE_ORDER,
            "prove the enrollment commit preceded any retained V3 admission",
        ),
    )


def _validated_identities(
    value: ReobservedUnitEnrollmentAdmissionBindingV1,
) -> tuple[str, ...]:
    return (
        wire.canonical_uuid(value.unit_id, "enrolled unit ID"),
        wire.digest(value.enrollment_digest, "enrollment digest"),
        wire.digest(value.admission_digest, "admission digest"),
        wire.digest(
            value.enrollment_policy_digest, "enrollment policy digest"
        ),
        wire.digest(value.project_identity_digest, "project identity digest"),
        wire.digest(
            value.experiment_identity_digest, "experiment identity digest"
        ),
    )


def validate_reobserved_unit_enrollment_admission_v1(value: object) -> None:
    """Validate every field while retaining the cross-ledger-order blocker."""
    if type(value) is not ReobservedUnitEnrollmentAdmissionBindingV1:
        raise UnitEnrollmentAdmissionValidationError(
            "enrolled admission is invalid"
        )
    try:
        identities = _validated_identities(value)
    except RuntimeError as exc:
        raise UnitEnrollmentAdmissionValidationError(
            "enrolled admission is invalid"
        ) from exc
    expected = ReobservedUnitEnrollmentAdmissionBindingV1(
        ENROLLED_ADMISSION_STATUS,
        *identities,
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
    if not same_wire_value(value, expected):
        raise UnitEnrollmentAdmissionValidationError(
            "enrolled admission is invalid"
        )


def validate_ordered_unit_enrollment_admission_v1(value: object) -> None:
    """Validate the exact promoted variant after receipt verification."""
    if type(value) is not ReobservedUnitEnrollmentAdmissionBindingV1:
        raise UnitEnrollmentAdmissionValidationError(
            "ordered enrolled admission is invalid"
        )
    try:
        identities = _validated_identities(value)
    except RuntimeError as exc:
        raise UnitEnrollmentAdmissionValidationError(
            "ordered enrolled admission is invalid"
        ) from exc
    unresolved = tuple(
        row
        for row in enrolled_admission_unresolved_v1()
        if row.code != CROSS_LEDGER_PROSPECTIVE_ORDER
    )
    expected = ReobservedUnitEnrollmentAdmissionBindingV1(
        ORDERED_ENROLLED_ADMISSION_STATUS,
        *identities,
        (UNIT_ENROLLMENT_AUTHORITY, CROSS_LEDGER_PROSPECTIVE_ORDER),
        unresolved,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        False,
        False,
    )
    if not same_wire_value(value, expected):
        raise UnitEnrollmentAdmissionValidationError(
            "ordered enrolled admission is invalid"
        )
