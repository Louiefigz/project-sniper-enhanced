"""Exact validation for non-authorizing durable cross-ledger order results."""

from __future__ import annotations

from .cross_ledger_order_schema import (
    parse_cross_ledger_order_document_v1,
)
from .cross_ledger_order_types import (
    CROSS_LEDGER_ORDER_COMMITTED_STATUS,
    CROSS_LEDGER_ORDER_REPLAY_STATUS,
    DurableCrossLedgerOrderedAdmissionV1,
)
from .operation_admission_durable_validation import (
    DurableOperationAdmissionValidationError,
    validate_durable_operation_admission_v3,
)
from .unit_enrollment_durable_validation import (
    DurableUnitEnrollmentValidationError,
    validate_durable_unit_enrollment_v1,
)
from .wire_identity import same_wire_value


class CrossLedgerOrderValidationError(RuntimeError):
    """A cross-ledger order result is malformed or forged."""


def _documents(value: DurableCrossLedgerOrderedAdmissionV1) -> bool:
    try:
        intent = parse_cross_ledger_order_document_v1(
            value.intent.document_json
        )
        receipt = parse_cross_ledger_order_document_v1(
            value.receipt.document_json
        )
    except RuntimeError as exc:
        raise CrossLedgerOrderValidationError(
            "cross-ledger order documents are invalid"
        ) from exc
    identity = intent.identity
    admission = value.admission.structural_binding.admission
    enrollment = value.enrollment.structural_binding.enrollment
    valid = (
        same_wire_value(intent, value.intent)
        and same_wire_value(receipt, value.receipt)
        and intent.state == "prepared"
        and receipt.state == "committed"
        and same_wire_value(identity, receipt.identity)
        and receipt.intent_digest == intent.document_digest
        and identity.authority_id == admission.authority_id
        and identity.authority_id == enrollment.authority_id
        and identity.unit_id == admission.unit_id
        and identity.unit_id == enrollment.unit_id
        and identity.enrollment_key == enrollment.enrollment_key
        and identity.enrollment_record_id == value.enrollment.record_id
        and identity.enrollment_digest == enrollment.enrollment_digest
        and identity.idempotency_key == admission.idempotency_key
        and identity.attempt_id == admission.attempt_id
        and identity.intended_child_generation_id
        == admission.intended_child_generation_id
        and identity.admission_record_id == value.admission.record_id
        and identity.admission_digest == admission.admission_digest
    )
    return valid


def _result_flags(value: DurableCrossLedgerOrderedAdmissionV1) -> bool:
    mode = (value.state, value.status)
    valid_mode = mode in {
        ("committed", CROSS_LEDGER_ORDER_COMMITTED_STATUS),
        ("replay", CROSS_LEDGER_ORDER_REPLAY_STATUS),
    }
    booleans = (
        value.order_created,
        value.admission_created,
        value.enrollment_bytes_reobserved,
        value.intent_committed_before_admission,
        value.exact_admission_reobserved_before_receipt,
        value.receipt_bytes_reobserved,
        value.replay_arbitrated,
        value.cross_ledger_order_receipt_verified,
        value.runtime_verified,
        value.fence_rechecked,
        value.execution_authorized,
        value.publication_authorized,
    )
    typed = all(type(flag) is bool for flag in booleans)
    flags = booleans[2:] == (True,) * 6 + (False,) * 4
    replay_valid = value.state != "replay" or (
        not value.order_created and not value.admission_created
    )
    creation_valid = not value.order_created or value.admission_created
    reobserved = not value.enrollment.created and not value.admission.created
    return (
        valid_mode
        and typed
        and flags
        and replay_valid
        and creation_valid
        and reobserved
    )


def validate_durable_cross_ledger_ordered_admission_v1(
    value: object,
) -> None:
    """Validate exact receipt, admission, states, and false authority flags."""
    if type(value) is not DurableCrossLedgerOrderedAdmissionV1:
        raise CrossLedgerOrderValidationError(
            "cross-ledger order result is invalid"
        )
    try:
        validate_durable_operation_admission_v3(value.admission)
        validate_durable_unit_enrollment_v1(value.enrollment)
    except (
        DurableOperationAdmissionValidationError,
        DurableUnitEnrollmentValidationError,
    ) as exc:
        raise CrossLedgerOrderValidationError(
            "cross-ledger durable admission is invalid"
        ) from exc
    if not (_result_flags(value) and _documents(value)):
        raise CrossLedgerOrderValidationError(
            "cross-ledger order result is invalid"
        )
