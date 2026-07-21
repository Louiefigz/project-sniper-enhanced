"""Bounded stable-set reader for authority-owned V3 admissions."""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Callable
from dataclasses import dataclass

from .durable_files import (
    bounded_directory_entries,
    DurableFileError,
    exact_directory_entries,
    open_private_child_dir,
    read_private_file,
)
from .operation_admission_binding import (
    OperationAdmissionBindingError,
    bind_operation_admission_v3,
)
from .operation_admission_schema import (
    OperationAdmissionV3,
    parse_operation_admission_v3,
)
from .operation_admission_store_scan import (
    OperationAdmissionStoreScanError,
    load_stable_record_set,
)
from .operation_admission_types import OperationAdmissionProposalV3
from .operation_contract import (
    HeadlessMp4OperationV1,
    parse_headless_mp4_operation_v1,
)

_ADMISSION_NAME = "admission.json"
_ARTIFACTS_NAME = "artifacts"
_RECORD = re.compile(r"[0-9a-f]{64}")
_RECORD_DOMAIN = b"sniper-operation-admission-record-v3\0"
_MAX_RECORDS = 50_000


class OperationAdmissionReaderError(RuntimeError):
    """A retained V3 admission set is unsafe or inconsistent."""


@dataclass(frozen=True)
class OperationAdmissionStoredRecordV3:
    """Exact retained admission and operation bytes under one record name."""

    name: str
    admission: OperationAdmissionV3
    operation: HeadlessMp4OperationV1


def operation_admission_record_name_v3(idempotency_key: str) -> str:
    """Derive one stable V3 admission record ID."""
    return hashlib.sha256(
        _RECORD_DOMAIN + idempotency_key.encode("ascii")
    ).hexdigest()


def _proposal(admission: OperationAdmissionV3) -> OperationAdmissionProposalV3:
    return OperationAdmissionProposalV3(
        admission.authority_id,
        admission.idempotency_key,
        admission.attempt_id,
        admission.intended_child_generation_id,
        admission.unit_id,
        admission.expected_parent,
        admission.first_submitted_at,
        admission.release_id,
        admission.build_id,
        admission.execution_policy_id,
    )


def _exact_names(dir_fd: int, expected: set[str], label: str) -> None:
    if not exact_directory_entries(dir_fd, expected):
        raise OperationAdmissionReaderError(f"{label} closure is not exact")


def _read_artifact(record_fd: int, relative_path: str) -> bytes:
    _exact_names(
        record_fd, {_ADMISSION_NAME, _ARTIFACTS_NAME}, "admission record"
    )
    current = open_private_child_dir(record_fd, _ARTIFACTS_NAME)
    opened = [current]
    try:
        parts = relative_path.split("/")
        for part in parts[:-1]:
            _exact_names(current, {part}, "operation artifact directory")
            current = open_private_child_dir(current, part)
            opened.append(current)
        _exact_names(current, {parts[-1]}, "operation artifact directory")
        return read_private_file(current, parts[-1], 16 * 1024 * 1024)
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)


def load_operation_admission_record_from_bytes_v3(
    name: str, admission_raw: bytes, operation_raw: bytes
) -> OperationAdmissionStoredRecordV3:
    """Parse and bind bytes read from already-pinned durable files."""
    try:
        admission = parse_operation_admission_v3(admission_raw)
        operation = parse_headless_mp4_operation_v1(operation_raw)
        bind_operation_admission_v3(operation, admission, _proposal(admission))
    except (
        OperationAdmissionBindingError,
        RuntimeError,
    ) as exc:
        raise OperationAdmissionReaderError(
            "stored V3 admission is invalid"
        ) from exc
    expected = operation_admission_record_name_v3(admission.idempotency_key)
    if name != expected:
        raise OperationAdmissionReaderError(
            "stored V3 admission name is invalid"
        )
    return OperationAdmissionStoredRecordV3(name, admission, operation)


def load_operation_admission_record_v3(
    store_fd: int, name: str
) -> OperationAdmissionStoredRecordV3:
    """Load and bind one exact retained admission record."""
    record_fd = open_private_child_dir(store_fd, name)
    try:
        admission_raw = read_private_file(record_fd, _ADMISSION_NAME)
        admission = parse_operation_admission_v3(admission_raw)
        operation_raw = _read_artifact(
            record_fd, admission.operation.artifact.relative_path
        )
        retained = load_operation_admission_record_from_bytes_v3(
            name, admission_raw, operation_raw
        )
    except (
        DurableFileError,
        OperationAdmissionBindingError,
        RuntimeError,
    ) as exc:
        raise OperationAdmissionReaderError(
            "stored V3 admission is invalid"
        ) from exc
    finally:
        os.close(record_fd)
    return retained


def load_all_operation_admissions_v3(
    store_fd: int,
    authority_id: str,
    loader: Callable[
        [int, str], OperationAdmissionStoredRecordV3
    ] = load_operation_admission_record_v3,
) -> tuple[OperationAdmissionStoredRecordV3, ...]:
    """Twice scan the full bounded set and enforce global uniqueness."""
    try:
        names = bounded_directory_entries(store_fd, _MAX_RECORDS)
    except DurableFileError as exc:
        raise OperationAdmissionReaderError(
            "cannot inspect V3 admission store"
        ) from exc
    if any(name.startswith(".pending-") for name in names):
        raise OperationAdmissionReaderError(
            "torn V3 admission pending record exists"
        )
    if any(not _RECORD.fullmatch(name) for name in names):
        raise OperationAdmissionReaderError(
            "V3 admission store has unknown entries"
        )
    try:
        records = load_stable_record_set(store_fd, names, loader, _MAX_RECORDS)
    except OperationAdmissionStoreScanError as exc:
        raise OperationAdmissionReaderError(str(exc)) from exc
    if any(
        record.admission.authority_id != authority_id for record in records
    ):
        raise OperationAdmissionReaderError(
            "V3 admission store crosses authorities"
        )
    attempts = [record.admission.attempt_id for record in records]
    children = [
        record.admission.intended_child_generation_id for record in records
    ]
    if len(attempts) != len(set(attempts)):
        raise OperationAdmissionReaderError(
            "V3 admission store duplicates an attempt"
        )
    if len(children) != len(set(children)):
        raise OperationAdmissionReaderError(
            "V3 admission store duplicates a child"
        )
    return records
