"""Durability recovery for visible exact V3 admission records."""

from __future__ import annotations

from .operation_admission_store_errors import OperationAdmissionStoreError
from .operation_admission_store_persistence import (
    OperationAdmissionPersistenceError,
    pinned_durable_operation_admission_record_v3,
)
from .operation_admission_store_reader import (
    OperationAdmissionReaderError,
    load_operation_admission_record_v3,
)
from .operation_admission_store_result import (
    durable_operation_admission_result,
)
from .operation_admission_store_types import (
    DurableOperationAdmissionV3,
    OperationAdmissionStoreRequestV3,
)


def recover_exact_operation_admission_v3(
    store_fd: int, name: str, request: OperationAdmissionStoreRequestV3
) -> DurableOperationAdmissionV3:
    """Re-establish barriers, then reobserve exact bytes before replay."""
    try:
        pinned = pinned_durable_operation_admission_record_v3(
            store_fd, name, request.admission
        )
        with pinned as durable:
            observed = load_operation_admission_record_v3(store_fd, name)
            exact = (
                observed.admission.document_json
                == durable.admission.document_json
                and observed.operation.document_json
                == durable.operation.document_json
            )
            if not exact:
                raise OperationAdmissionStoreError(
                    "V3 replay changed during durability recovery"
                )
    except (
        OperationAdmissionPersistenceError,
        OperationAdmissionReaderError,
    ) as exc:
        raise OperationAdmissionStoreError(str(exc)) from exc
    requested = (
        durable.admission.document_json == request.admission.document_json
        and durable.operation.document_json == request.operation.document_json
    )
    if not requested:
        raise OperationAdmissionStoreError(
            "V3 replay changed during durability recovery"
        )
    return durable_operation_admission_result(False, durable)
