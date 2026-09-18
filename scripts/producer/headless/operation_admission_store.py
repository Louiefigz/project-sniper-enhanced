"""Public exact-byte durable V3 operation-admission entry points."""

from __future__ import annotations

from .cross_ledger_order_lock import (
    CrossLedgerOrderLockError,
    locked_cross_ledger_order_root_v1,
)
from .operation_admission_store_errors import (
    OperationAdmissionAttemptConflictV3,
    OperationAdmissionChildConflictV3,
    OperationAdmissionIdempotencyConflictV3,
    OperationAdmissionStoreError,
)
from .operation_admission_store_types import (
    DURABLE_OPERATION_ADMISSION_STATUS,
    DurableOperationAdmissionV3,
)
from .operation_admission_transaction import (
    locked_operation_admission_transaction_v3,
    persist_or_replay_operation_admission_v3_in_transaction,
)

__all__ = (
    "OperationAdmissionAttemptConflictV3",
    "OperationAdmissionChildConflictV3",
    "OperationAdmissionIdempotencyConflictV3",
    "OperationAdmissionStoreError",
    "persist_or_replay_operation_admission_v3",
    "persist_or_replay_operation_admission_v3_under_order_lock",
    "require_durable_operation_admission_execution_authorized",
)


def persist_or_replay_operation_admission_v3_under_order_lock(
    request: object, lock: object
) -> DurableOperationAdmissionV3:
    """Persist V3 bytes under one already-held shared outer lock."""
    with locked_operation_admission_transaction_v3(
        request, lock
    ) as transaction:
        return persist_or_replay_operation_admission_v3_in_transaction(
            transaction
        )


def persist_or_replay_operation_admission_v3(
    request: object,
) -> DurableOperationAdmissionV3:
    """Take the shared outer lock once, then persist or replay exact V3."""
    authority_root = getattr(request, "authority_root", None)
    if type(authority_root) is not str:
        raise OperationAdmissionStoreError("V3 store request is invalid")
    try:
        with locked_cross_ledger_order_root_v1(authority_root) as lock:
            return persist_or_replay_operation_admission_v3_under_order_lock(
                request, lock
            )
    except OperationAdmissionStoreError:
        raise
    except (CrossLedgerOrderLockError, RuntimeError) as exc:
        raise OperationAdmissionStoreError(
            "V3 cross-ledger transaction failed"
        ) from exc


def require_durable_operation_admission_execution_authorized(
    value: object,
) -> None:
    """Never promote durable admission evidence into render authority."""
    if type(value) is not DurableOperationAdmissionV3:
        raise OperationAdmissionStoreError("durable V3 admission is invalid")
    raise OperationAdmissionStoreError(DURABLE_OPERATION_ADMISSION_STATUS)
