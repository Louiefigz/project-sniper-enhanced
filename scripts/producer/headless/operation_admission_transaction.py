"""One outer-to-inner locked V3 admission preflight and transaction."""

from __future__ import annotations

import contextlib
import os
import secrets
from collections.abc import Iterator

from .cross_ledger_order_guard import (
    require_cross_ledger_order_allows_admission_v1,
)
from .cross_ledger_order_lock import (
    CrossLedgerOrderLockV1,
    validate_cross_ledger_order_lock_v1,
)
from .cross_ledger_order_pending import (
    cleanup_abandoned_cross_ledger_order_pending_v1,
)
from .operation_admission_binding import (
    OperationAdmissionBindingError,
    bind_operation_admission_v3,
)
from .operation_admission_lock import (
    OperationAdmissionWriterLockV3,
    locked_operation_admission_writer_v3,
    validate_operation_admission_writer_lock_v3,
)
from .operation_admission_pending import (
    cleanup_abandoned_operation_admission_pending_v3,
)
from .operation_admission_recovery import recover_exact_operation_admission_v3
from .operation_admission_store_errors import (
    OperationAdmissionAttemptConflictV3,
    OperationAdmissionChildConflictV3,
    OperationAdmissionIdempotencyConflictV3,
    OperationAdmissionStoreError,
)
from .operation_admission_store_persistence import (
    OperationAdmissionPersistenceError,
    persist_operation_admission_record_v3,
)
from .operation_admission_store_reader import (
    OperationAdmissionReaderError,
    OperationAdmissionStoredRecordV3,
    load_all_operation_admissions_v3,
    load_operation_admission_record_v3,
    operation_admission_record_name_v3,
)
from .operation_admission_store_result import (
    durable_operation_admission_result,
)
from .operation_admission_store_types import (
    DurableOperationAdmissionV3,
    OperationAdmissionStoreRequestV3,
)
from .operation_admission_transaction_types import (
    OperationAdmissionPreflightV3,
    OperationAdmissionTransactionV3,
)

_MAX_RECORDS = 50_000
_ACTIVE_TRANSACTIONS: dict[bytes, object] = {}
_load_record = load_operation_admission_record_v3


def _checked_request(value: object) -> OperationAdmissionStoreRequestV3:
    if type(value) is not OperationAdmissionStoreRequestV3:
        raise OperationAdmissionStoreError("V3 store request is invalid")
    try:
        bind_operation_admission_v3(
            value.operation, value.admission, value.proposal
        )
    except (OperationAdmissionBindingError, RuntimeError) as exc:
        raise OperationAdmissionStoreError(
            "V3 store request is invalid"
        ) from exc
    return value


def validate_operation_admission_transaction_v3(value: object) -> None:
    """Require an exact registered transaction in its creating process."""
    if type(value) is not OperationAdmissionTransactionV3:
        raise OperationAdmissionStoreError("V3 transaction is invalid")
    registered = _ACTIVE_TRANSACTIONS.get(value.context_token)
    live = (
        type(value.context_token) is bytes
        and len(value.context_token) == 32
        and value.creator_pid == os.getpid()
        and registered is value
    )
    if not live:
        raise OperationAdmissionStoreError(
            "V3 transaction is stale or unregistered"
        )
    try:
        validate_operation_admission_writer_lock_v3(value.writer)
        _checked_request(value.request)
    except RuntimeError as exc:
        raise OperationAdmissionStoreError(
            "V3 transaction lock cannot be reobserved"
        ) from exc
    if value.request.authority_root != value.writer.authority_root:
        raise OperationAdmissionStoreError("V3 transaction crosses authority")


def _records(
    writer: OperationAdmissionWriterLockV3, authority_id: str
) -> tuple[OperationAdmissionStoredRecordV3, ...]:
    try:
        return load_all_operation_admissions_v3(
            writer.store_fd, authority_id, _load_record
        )
    except OperationAdmissionReaderError as exc:
        raise OperationAdmissionStoreError(str(exc)) from exc


@contextlib.contextmanager
def locked_operation_admission_transaction_v3(
    request: object, outer_lock: object
) -> Iterator[OperationAdmissionTransactionV3]:
    """Hold outer then inner continuously across cleanup and admission."""
    stack = contextlib.ExitStack()
    try:
        checked = _checked_request(request)
        validate_cross_ledger_order_lock_v1(outer_lock)
        if type(outer_lock) is not CrossLedgerOrderLockV1:
            raise OperationAdmissionStoreError("V3 outer lock is invalid")
        cleanup_abandoned_cross_ledger_order_pending_v1(outer_lock)
        writer = stack.enter_context(
            locked_operation_admission_writer_v3(
                checked.authority_root,
                checked.admission.authority_id,
                outer_lock,
            )
        )
        cleanup_abandoned_operation_admission_pending_v3(writer)
        reserved = require_cross_ledger_order_allows_admission_v1(
            outer_lock, checked.admission
        )
        transaction = OperationAdmissionTransactionV3(
            checked,
            writer,
            _records(writer, checked.admission.authority_id),
            reserved,
            os.getpid(),
            secrets.token_bytes(32),
        )
    except OperationAdmissionStoreError:
        stack.close()
        raise
    except RuntimeError as exc:
        stack.close()
        raise OperationAdmissionStoreError(str(exc)) from exc
    _ACTIVE_TRANSACTIONS[transaction.context_token] = transaction
    try:
        validate_operation_admission_transaction_v3(transaction)
        yield transaction
    finally:
        _ACTIVE_TRANSACTIONS.pop(transaction.context_token, None)
        stack.close()


def _classification(
    value: OperationAdmissionTransactionV3,
) -> tuple[str, OperationAdmissionStoredRecordV3 | None]:
    request = value.request
    name = operation_admission_record_name_v3(
        request.admission.idempotency_key
    )
    existing = next((row for row in value.records if row.name == name), None)
    if existing is not None:
        exact = (
            existing.admission.document_json == request.admission.document_json
            and existing.operation.document_json
            == request.operation.document_json
        )
        return ("exact" if exact else "idempotency-conflict"), existing
    if any(
        row.admission.attempt_id == request.admission.attempt_id
        for row in value.records
    ):
        return "attempt-conflict", None
    if any(
        row.admission.intended_child_generation_id
        == request.admission.intended_child_generation_id
        for row in value.records
    ):
        return "child-conflict", None
    return "absent", None


def _require_capacity(value: OperationAdmissionTransactionV3) -> bool:
    admitted = {row.admission.idempotency_key for row in value.records}
    claims = admitted | set(value.reserved_keys)
    key = value.request.admission.idempotency_key
    if len(claims) > _MAX_RECORDS or (
        key not in claims and len(claims) >= _MAX_RECORDS
    ):
        raise OperationAdmissionStoreError(
            "V3 admission capacity is already reserved"
        )
    return key in value.reserved_keys and key not in admitted


def preflight_operation_admission_transaction_v3(
    value: object,
) -> OperationAdmissionPreflightV3:
    """Classify conflicts and reserve logical capacity without writing."""
    validate_operation_admission_transaction_v3(value)
    transaction = value
    if type(transaction) is not OperationAdmissionTransactionV3:
        raise OperationAdmissionStoreError("V3 transaction is invalid")
    status, _record = _classification(transaction)
    reserved = False
    if status == "absent":
        reserved = _require_capacity(transaction)
    return OperationAdmissionPreflightV3(status, reserved)


def _raise_conflict(status: str) -> None:
    errors = {
        "idempotency-conflict": OperationAdmissionIdempotencyConflictV3,
        "attempt-conflict": OperationAdmissionAttemptConflictV3,
        "child-conflict": OperationAdmissionChildConflictV3,
    }
    error = errors.get(status)
    if error is None:
        return
    raise error(f"V3 admission has {status}")


def persist_or_replay_operation_admission_v3_in_transaction(
    value: object,
) -> DurableOperationAdmissionV3:
    """Persist or replay while the exact outer-to-inner transaction is held."""
    validate_operation_admission_transaction_v3(value)
    transaction = value
    if type(transaction) is not OperationAdmissionTransactionV3:
        raise OperationAdmissionStoreError("V3 transaction is invalid")
    status, existing = _classification(transaction)
    _raise_conflict(status)
    if status == "exact" and existing is not None:
        request = transaction.request
        name = operation_admission_record_name_v3(
            request.admission.idempotency_key
        )
        return recover_exact_operation_admission_v3(
            transaction.writer.store_fd, name, request
        )
    _require_capacity(transaction)
    request = transaction.request
    name = operation_admission_record_name_v3(
        request.admission.idempotency_key
    )
    try:
        persist_operation_admission_record_v3(
            transaction.writer.store_fd,
            name,
            request.admission,
            request.operation,
        )
        retained = load_operation_admission_record_v3(
            transaction.writer.store_fd, name
        )
        return durable_operation_admission_result(True, retained)
    except (
        OperationAdmissionPersistenceError,
        OperationAdmissionReaderError,
    ) as exc:
        raise OperationAdmissionStoreError(str(exc)) from exc


def reobserve_operation_admission_v3_in_transaction(
    value: object,
) -> DurableOperationAdmissionV3:
    """Reopen the requested exact record while both writer locks remain held."""
    validate_operation_admission_transaction_v3(value)
    transaction = value
    if type(transaction) is not OperationAdmissionTransactionV3:
        raise OperationAdmissionStoreError("V3 transaction is invalid")
    request = transaction.request
    name = operation_admission_record_name_v3(
        request.admission.idempotency_key
    )
    try:
        retained = _load_record(transaction.writer.store_fd, name)
    except OperationAdmissionReaderError as exc:
        raise OperationAdmissionStoreError(str(exc)) from exc
    exact = (
        retained.admission.document_json == request.admission.document_json
        and retained.operation.document_json == request.operation.document_json
    )
    if not exact:
        raise OperationAdmissionStoreError(
            "V3 transaction did not retain the exact admission"
        )
    return durable_operation_admission_result(False, retained)
