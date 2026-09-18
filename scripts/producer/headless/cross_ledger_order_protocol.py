"""Crash-recoverable prospective enrollment-to-admission order transaction."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator

from .cross_ledger_order_barrier import (
    load_writer_durable_cross_ledger_order_state_v1,
)
from .cross_ledger_order_lock import (
    CrossLedgerOrderLockError,
    CrossLedgerOrderLockV1,
    locked_cross_ledger_order_root_v1,
    validate_cross_ledger_order_lock_v1,
    validate_publish_bound_cross_ledger_order_lock_v1,
)
from .cross_ledger_order_pending import (
    cleanup_abandoned_cross_ledger_order_pending_v1,
)
from .cross_ledger_order_request import (
    build_cross_ledger_order_request_identity_v1,
    checked_cross_ledger_order_request_v1,
)
from .cross_ledger_order_schema import CrossLedgerOrderIdentityV1
from .cross_ledger_order_store import (
    persist_cross_ledger_order_committed_v1,
    persist_cross_ledger_order_prepared_v1,
    persist_cross_ledger_order_rejection_v1,
    reject_prepared_cross_ledger_order_v1,
)
from .cross_ledger_order_types import (
    CROSS_LEDGER_ORDER_COMMITTED_STATUS,
    CROSS_LEDGER_ORDER_REPLAY_STATUS,
    CrossLedgerOrderError,
    CrossLedgerOrderPermanentRejectionV1,
    CrossLedgerOrderRequestV1,
    CrossLedgerOrderStateV1,
    DurableCrossLedgerOrderedAdmissionV1,
)
from .operation_admission_store_errors import OperationAdmissionStoreError
from .operation_admission_transaction import (
    locked_operation_admission_transaction_v3,
    persist_or_replay_operation_admission_v3_in_transaction,
    preflight_operation_admission_transaction_v3,
    reobserve_operation_admission_v3_in_transaction,
)
from .operation_admission_transaction_types import (
    OperationAdmissionPreflightV3,
    OperationAdmissionTransactionV3,
)
from .operation_admission_store_types import DurableOperationAdmissionV3
from .unit_enrollment_store import (
    UnitEnrollmentStoreError,
    reobserve_prospective_unit_enrollment_v1,
)
from .unit_enrollment_store_types import (
    DurableUnitEnrollmentV1,
    UnitEnrollmentReadRequestV1,
)
from .wire_identity import same_wire_value

_checked_request = checked_cross_ledger_order_request_v1
_identity = build_cross_ledger_order_request_identity_v1


def _reobserve_enrollment(
    request: CrossLedgerOrderRequestV1,
) -> DurableUnitEnrollmentV1:
    expected = request.enrollment
    enrollment = expected.structural_binding.enrollment
    try:
        observed = reobserve_prospective_unit_enrollment_v1(
            UnitEnrollmentReadRequestV1(
                request.authority_root,
                enrollment.authority_id,
                enrollment.enrollment_key,
            )
        )
    except UnitEnrollmentStoreError as exc:
        raise CrossLedgerOrderError(
            "durable enrollment cannot be reobserved"
        ) from exc
    exact = observed.record_id == expected.record_id and same_wire_value(
        observed.structural_binding, expected.structural_binding
    )
    if not exact:
        raise CrossLedgerOrderError("durable enrollment identity changed")
    return observed


def _reject_preexisting(
    lock: object,
    identity: CrossLedgerOrderIdentityV1,
    initial: CrossLedgerOrderStateV1,
    preflight: OperationAdmissionPreflightV3,
) -> None:
    conflict = preflight.status in {
        "idempotency-conflict",
        "attempt-conflict",
        "child-conflict",
    }
    if initial.state == "committed" and preflight.status != "exact":
        raise CrossLedgerOrderError(
            "committed order has no retained exact admission"
        )
    if initial.state in {"prepared", "commit-pending"} and conflict:
        reject_prepared_cross_ledger_order_v1(
            lock,
            identity,
            "ADMISSION_UNIQUENESS_STOLEN_AFTER_PREPARED",
        )
        raise CrossLedgerOrderPermanentRejectionV1(
            "prepared order conflicts with a retained admission"
        )
    if initial.state != "absent" or preflight.status == "absent":
        return
    persist_cross_ledger_order_rejection_v1(lock, identity)
    raise CrossLedgerOrderPermanentRejectionV1(
        "operation admission predated durable prospective intent"
    )


def _admit_or_replay(
    transaction: OperationAdmissionTransactionV3,
    initial: CrossLedgerOrderStateV1,
) -> tuple[bool, DurableOperationAdmissionV3]:
    written = persist_or_replay_operation_admission_v3_in_transaction(
        transaction
    )
    if initial.state == "committed" and written.created:
        raise CrossLedgerOrderError(
            "committed order recreated a missing admission"
        )
    retained = reobserve_operation_admission_v3_in_transaction(transaction)
    return written.created, retained


def _result(
    initial: CrossLedgerOrderStateV1,
    committed: CrossLedgerOrderStateV1,
    outcome: tuple[bool, DurableUnitEnrollmentV1, DurableOperationAdmissionV3],
) -> DurableCrossLedgerOrderedAdmissionV1:
    admission_created, enrollment, admission = outcome
    replayed = initial.state == "committed"
    status = (
        CROSS_LEDGER_ORDER_REPLAY_STATUS
        if replayed
        else CROSS_LEDGER_ORDER_COMMITTED_STATUS
    )
    return DurableCrossLedgerOrderedAdmissionV1(
        status,
        "replay" if replayed else "committed",
        initial.state == "absent",
        admission_created,
        committed.intent,
        committed.receipt,
        enrollment,
        admission,
        True,
        True,
        True,
        True,
        True,
        True,
        False,
        False,
        False,
        False,
    )


def _validate_lock(lock: object, publish_bound: bool) -> None:
    validator = (
        validate_publish_bound_cross_ledger_order_lock_v1
        if publish_bound
        else validate_cross_ledger_order_lock_v1
    )
    validator(lock)


@contextlib.contextmanager
def _mutation(lock: object, publish_bound: bool) -> Iterator[None]:
    _validate_lock(lock, publish_bound)
    try:
        yield
    finally:
        _validate_lock(lock, publish_bound)


def _persist_under_lock(
    request: CrossLedgerOrderRequestV1,
    lock: CrossLedgerOrderLockV1,
    publish_bound: bool,
) -> DurableCrossLedgerOrderedAdmissionV1:
    identity = _identity(request)
    with _mutation(lock, publish_bound):
        cleanup_abandoned_cross_ledger_order_pending_v1(lock)
    _reobserve_enrollment(request)
    initial = load_writer_durable_cross_ledger_order_state_v1(lock, identity)
    with _mutation(
        lock, publish_bound
    ), locked_operation_admission_transaction_v3(
        request.admission, lock
    ) as transaction:
        preflight = preflight_operation_admission_transaction_v3(transaction)
        with _mutation(lock, publish_bound):
            _reject_preexisting(lock, identity, initial, preflight)
        with _mutation(lock, publish_bound):
            persist_cross_ledger_order_prepared_v1(lock, identity)
        with _mutation(lock, publish_bound):
            admission_created, admitted = _admit_or_replay(
                transaction, initial
            )
        if initial.state == "absent" and not admission_created:
            with _mutation(lock, publish_bound):
                reject_prepared_cross_ledger_order_v1(lock, identity)
            raise CrossLedgerOrderPermanentRejectionV1(
                "fresh intent observed a preexisting admission"
            )
    enrolled = _reobserve_enrollment(request)
    with _mutation(lock, publish_bound):
        committed = persist_cross_ledger_order_committed_v1(lock, identity)
    return _result(initial, committed, (admission_created, enrolled, admitted))


def _checked_lock_request(
    value: object, lock: object, publish_bound: bool
) -> CrossLedgerOrderRequestV1:
    request = _checked_request(value)
    _validate_lock(lock, publish_bound)
    if request.authority_root != lock.authority_root:
        raise CrossLedgerOrderError(
            "cross-ledger request crosses the held authority root"
        )
    return request


def preflight_cross_ledger_ordered_admission_under_lock_v1(
    value: object, lock: object
) -> CrossLedgerOrderStateV1:
    """Reobserve current order state under exact live publisher lineage."""
    try:
        request = _checked_lock_request(value, lock, True)
        _reobserve_enrollment(request)
        identity = _identity(request)
        with _mutation(lock, True):
            cleanup_abandoned_cross_ledger_order_pending_v1(lock)
        state = load_writer_durable_cross_ledger_order_state_v1(lock, identity)
        _validate_lock(lock, True)
        return state
    except CrossLedgerOrderError:
        raise
    except (CrossLedgerOrderLockError, RuntimeError) as exc:
        raise CrossLedgerOrderError(
            "cross-ledger controller preflight failed"
        ) from exc


def persist_or_replay_cross_ledger_ordered_admission_under_lock_v1(
    value: object, lock: object
) -> DurableCrossLedgerOrderedAdmissionV1:
    """Commit or replay using the caller's exact live cross-ledger lock."""
    try:
        request = _checked_lock_request(value, lock, True)
        return _persist_under_lock(request, lock, True)
    except CrossLedgerOrderError:
        raise
    except (
        CrossLedgerOrderLockError,
        OperationAdmissionStoreError,
        RuntimeError,
    ) as exc:
        raise CrossLedgerOrderError(
            "cross-ledger prospective order failed"
        ) from exc


def persist_or_replay_cross_ledger_ordered_admission_v1(
    value: object,
) -> DurableCrossLedgerOrderedAdmissionV1:
    """Commit PREPARED before admission and COMMITTED after reobservation."""
    request = _checked_request(value)
    try:
        with locked_cross_ledger_order_root_v1(request.authority_root) as lock:
            return _persist_under_lock(request, lock, False)
    except CrossLedgerOrderError:
        raise
    except (CrossLedgerOrderLockError, RuntimeError) as exc:
        raise CrossLedgerOrderError(
            "cross-ledger prospective order failed"
        ) from exc


def require_cross_ledger_order_execution_authorized(value: object) -> None:
    """Never treat an order receipt as runtime or render-start authority."""
    if type(value) is not DurableCrossLedgerOrderedAdmissionV1:
        raise CrossLedgerOrderError("cross-ledger order result is invalid")
    raise CrossLedgerOrderError(value.status)
