"""Writer-only recovery of uncommitted V3 admission directories."""

from __future__ import annotations

import os
import re

from .durable_files import (
    bounded_directory_entries,
    DurableFileError,
    open_private_child_dir,
    read_private_file,
)
from .operation_admission_schema import (
    OperationAdmissionV3,
    parse_operation_admission_v3,
)
from .operation_admission_lock import (
    OperationAdmissionWriterLockV3,
    validate_operation_admission_writer_lock_v3,
)
from .operation_admission_store_reader import (
    operation_admission_record_name_v3,
)
from .pending_cleanup_fs import (
    PendingCleanupFileError,
    remove_empty_private_pending_dir,
    remove_private_pending_file,
)

_ADMISSION_NAME = "admission.json"
_ARTIFACTS_NAME = "artifacts"
_PENDING = re.compile(r"\.pending-([0-9a-f]{64})-([0-9a-f]{32})")
_MAX_ENTRIES = 100_000
_MAX_ADMISSION_BYTES = 65_536


class OperationAdmissionPendingError(RuntimeError):
    """Abandoned V3 admission scratch state is unsafe or ambiguous."""


def _pending_targets(names: tuple[str, ...]) -> dict[str, str]:
    pending = {}
    for name in names:
        if not name.startswith(".pending-"):
            continue
        match = _PENDING.fullmatch(name)
        if match is None or match.group(1) in pending:
            raise OperationAdmissionPendingError(
                "V3 pending identity is ambiguous"
            )
        pending[match.group(1)] = name
    if any(target in names for target in pending):
        raise OperationAdmissionPendingError(
            "V3 pending and final records coexist"
        )
    return pending


def _admission_state(
    record_fd: int,
) -> tuple[bytes, OperationAdmissionV3 | None]:
    raw = read_private_file(record_fd, _ADMISSION_NAME, _MAX_ADMISSION_BYTES)
    try:
        return raw, parse_operation_admission_v3(raw)
    except RuntimeError:
        return raw, None


def _require_same_admission(raw: bytes, expected: bytes) -> None:
    if raw != expected:
        raise OperationAdmissionPendingError(
            "V3 pending admission changed before unlink"
        )


def _discard_artifact_branch(
    parent_fd: int, parts: tuple[str, ...], max_bytes: int
) -> None:
    entries = bounded_directory_entries(parent_fd, 2)
    if not entries:
        return
    if entries != (parts[0],):
        raise OperationAdmissionPendingError(
            "V3 pending artifact closure is unsafe"
        )
    if len(parts) == 1:
        remove_private_pending_file(parent_fd, parts[0], max_bytes)
        return
    child_fd = open_private_child_dir(parent_fd, parts[0])
    try:
        _discard_artifact_branch(child_fd, parts[1:], max_bytes)
    finally:
        os.close(child_fd)
    remove_empty_private_pending_dir(parent_fd, parts[0])


def _discard_artifacts(
    record_fd: int, admission: OperationAdmissionV3
) -> None:
    artifacts_fd = open_private_child_dir(record_fd, _ARTIFACTS_NAME)
    try:
        parts = tuple(admission.operation.artifact.relative_path.split("/"))
        _discard_artifact_branch(
            artifacts_fd, parts, admission.operation.artifact.size_bytes
        )
    finally:
        os.close(artifacts_fd)
    remove_empty_private_pending_dir(record_fd, _ARTIFACTS_NAME)


def _discard(store_fd: int, name: str, target: str) -> None:
    record_fd = open_private_child_dir(store_fd, name)
    try:
        entries = frozenset(bounded_directory_entries(record_fd, 3))
        allowed = frozenset({_ADMISSION_NAME, _ARTIFACTS_NAME})
        if not entries.issubset(allowed):
            raise OperationAdmissionPendingError(
                "V3 pending closure is unsafe"
            )
        admission_raw, admission = (
            _admission_state(record_fd)
            if _ADMISSION_NAME in entries
            else (None, None)
        )
        if admission is not None:
            expected = operation_admission_record_name_v3(
                admission.idempotency_key
            )
            if expected != target:
                raise OperationAdmissionPendingError(
                    "V3 pending identity disagrees with its target"
                )
        if _ARTIFACTS_NAME in entries:
            if admission is None:
                raise OperationAdmissionPendingError(
                    "V3 pending closure is unsafe"
                )
            _discard_artifacts(record_fd, admission)
        if _ADMISSION_NAME in entries:
            if type(admission_raw) is not bytes:
                raise OperationAdmissionPendingError(
                    "V3 pending admission bytes are unavailable"
                )
            remove_private_pending_file(
                record_fd,
                _ADMISSION_NAME,
                _MAX_ADMISSION_BYTES,
                lambda raw: _require_same_admission(raw, admission_raw),
            )
    finally:
        os.close(record_fd)
    remove_empty_private_pending_dir(store_fd, name)


def cleanup_abandoned_operation_admission_pending_v3(value: object) -> None:
    """Discard pre-rename V3 records under outer and admission locks."""
    try:
        validate_operation_admission_writer_lock_v3(value)
        writer = value
        if type(writer) is not OperationAdmissionWriterLockV3:
            raise OperationAdmissionPendingError("V3 writer lock is invalid")
        store_fd = writer.store_fd
        before = bounded_directory_entries(store_fd, _MAX_ENTRIES)
        pending = _pending_targets(before)
        retained = frozenset(set(before) - set(pending.values()))
        for target, name in pending.items():
            _discard(store_fd, name, target)
        after = frozenset(bounded_directory_entries(store_fd, _MAX_ENTRIES))
        if after != retained:
            raise OperationAdmissionPendingError(
                "V3 store changed during pending cleanup"
            )
    except OperationAdmissionPendingError:
        raise
    except (DurableFileError, PendingCleanupFileError, RuntimeError) as exc:
        raise OperationAdmissionPendingError(
            "V3 pending cleanup failed"
        ) from exc
