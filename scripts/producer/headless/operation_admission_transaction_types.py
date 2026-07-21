"""Non-authorizing types for one locked V3 admission transaction."""

from __future__ import annotations

from dataclasses import dataclass

from .operation_admission_lock import OperationAdmissionWriterLockV3
from .operation_admission_store_reader import OperationAdmissionStoredRecordV3
from .operation_admission_store_types import OperationAdmissionStoreRequestV3


@dataclass(frozen=True)
class OperationAdmissionPreflightV3:
    """Classification observed under both admission locks."""

    status: str
    capacity_reserved: bool


@dataclass(frozen=True)
class OperationAdmissionTransactionV3:
    """Opaque stable V3 record-set snapshot held under both writer locks."""

    request: OperationAdmissionStoreRequestV3
    writer: OperationAdmissionWriterLockV3
    records: tuple[OperationAdmissionStoredRecordV3, ...]
    reserved_keys: tuple[str, ...]
    creator_pid: int
    context_token: bytes
