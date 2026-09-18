"""Fail-closed diagnostic promotion after unit-enrollment binding."""

from __future__ import annotations

import dataclasses

from .admitted_quality_pass_composition_types import (
    NonAuthorizingAdmittedQualityPassCompositionV1,
)
from .enrolled_admitted_quality_pass_types import (
    EnrolledAdmittedQualityPassCompositionError,
)
from .quality_pass_composition_types import (
    CompositionAuthorityRequirementV1,
    NonAuthorizingQualityPassCompositionV1,
)
from .unit_enrollment_admission_types import (
    CROSS_LEDGER_PROSPECTIVE_ORDER,
    UNIT_ENROLLMENT_AUTHORITY,
    ReobservedUnitEnrollmentAdmissionBindingV1,
)
from .unit_enrollment_admission_validation import (
    UnitEnrollmentAdmissionValidationError,
    validate_ordered_unit_enrollment_admission_v1,
)
from .wire_identity import same_wire_value


def _requirement_codes(rows: object) -> tuple[str, ...]:
    valid = type(rows) is tuple and all(
        type(row) is CompositionAuthorityRequirementV1
        and type(row.code) is str
        for row in rows
    )
    if not valid:
        raise EnrolledAdmittedQualityPassCompositionError(
            "composition authority requirements are invalid"
        )
    return tuple(row.code for row in rows)


def _remaining_authority(
    rows: tuple[CompositionAuthorityRequirementV1, ...],
) -> tuple[CompositionAuthorityRequirementV1, ...]:
    _requirement_codes(rows)
    return tuple(
        row
        for row in rows
        if row.code
        not in {UNIT_ENROLLMENT_AUTHORITY, CROSS_LEDGER_PROSPECTIVE_ORDER}
    )


def _validated_composition(
    value: object,
    binding: ReobservedUnitEnrollmentAdmissionBindingV1,
) -> NonAuthorizingQualityPassCompositionV1:
    if type(value) is not NonAuthorizingAdmittedQualityPassCompositionV1:
        raise EnrolledAdmittedQualityPassCompositionError(
            "admitted composition type is invalid"
        )
    composition = value.composition
    if type(composition) is not NonAuthorizingQualityPassCompositionV1:
        raise EnrolledAdmittedQualityPassCompositionError(
            "admitted composition diagnostics are invalid"
        )
    outer_codes = _requirement_codes(value.unresolved_authority)
    nested_codes = _requirement_codes(composition.unresolved_authority)
    closed = composition.closed_checks
    closed_valid = type(closed) is tuple and all(
        type(row) is str for row in closed
    )
    identity = same_wire_value(
        (value.admission_digest, composition.unit_id),
        (binding.admission_digest, binding.unit_id),
    )
    flags = (
        value.unit_enrollment_verified,
        value.operation_runtime_verified,
        value.fence_rechecked,
        value.execution_authorized,
        value.publication_authorized,
        composition.operation_runtime_verified,
        composition.fence_rechecked,
        composition.execution_authorized,
        composition.publication_authorized,
    )
    valid = (
        identity
        and closed_valid
        and UNIT_ENROLLMENT_AUTHORITY in outer_codes
        and UNIT_ENROLLMENT_AUTHORITY in nested_codes
        and UNIT_ENROLLMENT_AUTHORITY not in composition.closed_checks
        and same_wire_value(flags, (False,) * 9)
    )
    if not valid:
        raise EnrolledAdmittedQualityPassCompositionError(
            "admitted composition diagnostics are invalid"
        )
    return composition


def promote_enrolled_admitted_composition(
    value: object,
    binding: ReobservedUnitEnrollmentAdmissionBindingV1,
) -> NonAuthorizingAdmittedQualityPassCompositionV1:
    """Close enrollment and durable order in non-authorizing diagnostics."""
    try:
        validate_ordered_unit_enrollment_admission_v1(binding)
    except UnitEnrollmentAdmissionValidationError as exc:
        raise EnrolledAdmittedQualityPassCompositionError(
            "enrolled admission binding is invalid"
        ) from exc
    composition = _validated_composition(value, binding)
    promoted = dataclasses.replace(
        composition,
        closed_checks=composition.closed_checks
        + (UNIT_ENROLLMENT_AUTHORITY, CROSS_LEDGER_PROSPECTIVE_ORDER),
        unresolved_authority=_remaining_authority(
            composition.unresolved_authority
        ),
    )
    return dataclasses.replace(
        value,
        unresolved_authority=_remaining_authority(value.unresolved_authority),
        composition=promoted,
        unit_enrollment_verified=True,
    )
