"""Promote enrolled-admission diagnostics with a durable order receipt."""

from __future__ import annotations

import dataclasses

from .cross_ledger_order_validation import (
    CrossLedgerOrderValidationError,
    validate_durable_cross_ledger_ordered_admission_v1,
)
from .unit_enrollment_admission_types import (
    CROSS_LEDGER_PROSPECTIVE_ORDER,
    ORDERED_ENROLLED_ADMISSION_STATUS,
    ReobservedUnitEnrollmentAdmissionBindingV1,
)
from .unit_enrollment_admission_validation import (
    UnitEnrollmentAdmissionValidationError,
    validate_reobserved_unit_enrollment_admission_v1,
)


class UnitEnrollmentOrderPromotionError(RuntimeError):
    """The enrollment binding and order receipt do not share exact identity."""


def promote_unit_enrollment_with_order_receipt_v1(
    binding: object, receipt: object
) -> ReobservedUnitEnrollmentAdmissionBindingV1:
    """Close only the prospective-order blocker; never grant execution."""
    try:
        validate_reobserved_unit_enrollment_admission_v1(binding)
        validate_durable_cross_ledger_ordered_admission_v1(receipt)
    except (
        UnitEnrollmentAdmissionValidationError,
        CrossLedgerOrderValidationError,
    ) as exc:
        raise UnitEnrollmentOrderPromotionError(
            "enrollment order evidence is invalid"
        ) from exc
    identity = receipt.intent.identity
    exact = (
        binding.unit_id == identity.unit_id
        and binding.enrollment_digest == identity.enrollment_digest
        and binding.admission_digest == identity.admission_digest
    )
    if not exact:
        raise UnitEnrollmentOrderPromotionError(
            "enrollment order identity disagrees"
        )
    unresolved = tuple(
        row
        for row in binding.unresolved_authority
        if row.code != CROSS_LEDGER_PROSPECTIVE_ORDER
    )
    return dataclasses.replace(
        binding,
        status=ORDERED_ENROLLED_ADMISSION_STATUS,
        closed_requirements=binding.closed_requirements
        + (CROSS_LEDGER_PROSPECTIVE_ORDER,),
        unresolved_authority=unresolved,
        cross_ledger_order_receipt_verified=True,
    )
