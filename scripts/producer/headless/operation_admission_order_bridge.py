"""Read-only V3 admission lookup while the shared order lock is held."""

from __future__ import annotations

import os

from .authority_record import read_authority_record
from .cross_ledger_order_lock import (
    CrossLedgerOrderLockError,
    CrossLedgerOrderLockV1,
    validate_cross_ledger_order_lock_v1,
)
from .durable_files import (
    DurableFileError,
    locked_existing_private_dir,
    open_private_child_dir,
)
from .operation_admission_binding import bind_operation_admission_v3
from .operation_admission_store_reader import (
    OperationAdmissionReaderError,
    OperationAdmissionStoredRecordV3,
    load_all_operation_admissions_v3,
)
from .operation_admission_store_result import (
    durable_operation_admission_result,
)
from .operation_admission_store_types import (
    DurableOperationAdmissionV3,
    OperationAdmissionStoreRequestV3,
)

_LOCK_NAME = ".operation-admission-v3.lock"
_STORE_NAME = "operation-admissions-v3"


class OperationAdmissionOrderBridgeError(RuntimeError):
    """V3 admission presence cannot be safely observed under order lock."""


def _checked(
    request: object, lock: object
) -> tuple[OperationAdmissionStoreRequestV3, CrossLedgerOrderLockV1]:
    if type(request) is not OperationAdmissionStoreRequestV3:
        raise OperationAdmissionOrderBridgeError("V3 request is invalid")
    try:
        bind_operation_admission_v3(
            request.operation, request.admission, request.proposal
        )
        validate_cross_ledger_order_lock_v1(lock)
    except (RuntimeError, CrossLedgerOrderLockError) as exc:
        raise OperationAdmissionOrderBridgeError(
            "V3 order-lock request is invalid"
        ) from exc
    if request.authority_root != lock.authority_root:
        raise OperationAdmissionOrderBridgeError(
            "V3 order lock crosses authority root"
        )
    return request, lock


def _missing_store(lock: CrossLedgerOrderLockV1) -> bool:
    try:
        store_fd = open_private_child_dir(lock.root_fd, _STORE_NAME)
    except (DurableFileError, OperationAdmissionReaderError) as exc:
        if isinstance(exc.__cause__, FileNotFoundError):
            return True
        raise OperationAdmissionOrderBridgeError("V3 store is unsafe") from exc
    os.close(store_fd)
    return False


def _records(
    request: OperationAdmissionStoreRequestV3,
    lock: CrossLedgerOrderLockV1,
) -> tuple[OperationAdmissionStoredRecordV3, ...]:
    try:
        with locked_existing_private_dir(
            request.authority_root, _LOCK_NAME
        ) as root_fd:
            expected = {
                "authorityId": request.admission.authority_id,
                "schemaVersion": 1,
            }
            if read_authority_record(root_fd) != expected:
                raise OperationAdmissionOrderBridgeError(
                    "V3 authority is invalid"
                )
            store_fd = open_private_child_dir(root_fd, _STORE_NAME)
            try:
                return load_all_operation_admissions_v3(
                    store_fd, request.admission.authority_id
                )
            finally:
                os.close(store_fd)
    except (DurableFileError, OperationAdmissionReaderError) as exc:
        if isinstance(exc.__cause__, FileNotFoundError) and _missing_store(
            lock
        ):
            return ()
        raise OperationAdmissionOrderBridgeError(
            "V3 admission reobservation failed"
        ) from exc


def operation_admission_exists_for_request_v3_under_order_lock(
    request: object, lock: object
) -> bool:
    """Return whether any V3 uniqueness identity is already admitted."""
    checked, held = _checked(request, lock)
    records = _records(checked, held)
    return any(
        row.admission.idempotency_key == checked.admission.idempotency_key
        or row.admission.attempt_id == checked.admission.attempt_id
        or row.admission.intended_child_generation_id
        == checked.admission.intended_child_generation_id
        for row in records
    )


def reobserve_unit_operation_admission_v3_under_order_lock(
    request: object, lock: object
) -> DurableOperationAdmissionV3 | None:
    """Return an admission only when its exact bytes match the request."""
    checked, held = _checked(request, lock)
    matches = tuple(
        row
        for row in _records(checked, held)
        if row.admission.idempotency_key == checked.admission.idempotency_key
    )
    if not matches:
        return None
    if len(matches) != 1:
        raise OperationAdmissionOrderBridgeError(
            "idempotency key has multiple V3 admissions"
        )
    retained = matches[0]
    same = (
        retained.admission.document_json == checked.admission.document_json
        and retained.operation.document_json == checked.operation.document_json
    )
    if not same:
        raise OperationAdmissionOrderBridgeError(
            "unit admission conflicts with requested exact bytes"
        )
    return durable_operation_admission_result(False, retained)
