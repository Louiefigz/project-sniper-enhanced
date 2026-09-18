"""Noncreating public read path for durable cross-ledger order state."""

from __future__ import annotations

from .authority_record import read_authority_record
from .cross_ledger_order_lock import (
    CrossLedgerOrderLockError,
    locked_existing_cross_ledger_order_root_v1,
)
from .cross_ledger_order_schema import (
    CrossLedgerOrderIdentityV1,
    build_cross_ledger_order_identity_v1,
    require_same_cross_ledger_identity_v1,
)
from .cross_ledger_order_store import (
    load_cross_ledger_order_state_v1,
)
from .cross_ledger_order_types import (
    CrossLedgerOrderError,
    CrossLedgerOrderStateV1,
)


def _validated_identity(value: object) -> CrossLedgerOrderIdentityV1:
    if type(value) is not CrossLedgerOrderIdentityV1:
        raise CrossLedgerOrderError("cross-ledger read identity is invalid")
    values = (
        value.authority_id,
        value.unit_id,
        value.enrollment_key,
        value.enrollment_record_id,
        value.enrollment_digest,
        value.idempotency_key,
        value.attempt_id,
        value.intended_child_generation_id,
        value.admission_record_id,
        value.admission_digest,
    )
    try:
        rebuilt = build_cross_ledger_order_identity_v1(values)
        require_same_cross_ledger_identity_v1(value, rebuilt)
    except RuntimeError as exc:
        raise CrossLedgerOrderError(
            "cross-ledger read identity is invalid"
        ) from exc
    return value


def reobserve_cross_ledger_order_state_v1(
    authority_root: str, identity: object
) -> CrossLedgerOrderStateV1:
    """Read exact state without creating a lock, store, or record."""
    checked = _validated_identity(identity)
    try:
        with locked_existing_cross_ledger_order_root_v1(
            authority_root
        ) as lock:
            authority = read_authority_record(lock.root_fd)
            expected = {
                "authorityId": checked.authority_id,
                "schemaVersion": 1,
            }
            if authority != expected:
                raise CrossLedgerOrderError(
                    "cross-ledger read authority is invalid"
                )
            return load_cross_ledger_order_state_v1(lock, checked)
    except CrossLedgerOrderError:
        raise
    except (CrossLedgerOrderLockError, RuntimeError) as exc:
        raise CrossLedgerOrderError(
            "cross-ledger order cannot be reobserved"
        ) from exc
