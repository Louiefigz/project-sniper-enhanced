"""Admission-side guard for retained cross-ledger unit reservations."""

from __future__ import annotations

from .cross_ledger_order_barrier import (
    load_writer_durable_cross_ledger_order_set_v1,
)
from .cross_ledger_order_lock import CrossLedgerOrderLockV1
from .cross_ledger_order_store import (
    cross_ledger_order_record_name_v1,
)
from .cross_ledger_order_types import CrossLedgerOrderConflictV1
from .operation_admission_schema import OperationAdmissionV3


def require_cross_ledger_order_allows_admission_v1(
    lock: CrossLedgerOrderLockV1, admission: OperationAdmissionV3
) -> tuple[str, ...]:
    """Reject reservation conflicts and return unmaterialized slot keys."""
    roles = (
        admission.idempotency_key,
        admission.attempt_id,
        admission.intended_child_generation_id,
    )
    states = load_writer_durable_cross_ledger_order_set_v1(
        lock, admission.authority_id, roles
    )
    name = cross_ledger_order_record_name_v1(admission.idempotency_key)
    for state in states:
        document = state.intent or state.rejection
        identity = document.identity
        collides = (
            state.name == name
            or identity.attempt_id == admission.attempt_id
            or identity.intended_child_generation_id
            == admission.intended_child_generation_id
        )
        exact = (
            state.name == name
            and identity.attempt_id == admission.attempt_id
            and identity.intended_child_generation_id
            == admission.intended_child_generation_id
            and identity.admission_digest == admission.admission_digest
        )
        if collides and (state.state == "rejected" or not exact):
            raise CrossLedgerOrderConflictV1(
                "operation admission conflicts with durable order state"
            )
    return tuple(
        sorted(
            (state.intent or state.rejection).identity.idempotency_key
            for state in states
            if state.state in {"prepared", "commit-pending"}
        )
    )
