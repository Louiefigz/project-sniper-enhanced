"""Crash-visible pending-directory writer for V3 operation admissions."""

from __future__ import annotations

import contextlib
import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

from .durable_files import (
    DurableFileError,
    exact_directory_entries,
    open_private_child_dir,
    open_private_file,
    private_child_dir,
    write_all,
)
from .operation_admission_schema import OperationAdmissionV3
from .operation_admission_store_reader import (
    OperationAdmissionStoredRecordV3,
    load_operation_admission_record_from_bytes_v3,
)
from .operation_contract import HeadlessMp4OperationV1
from .record_durability import (
    assert_named_private_directory_identity,
    assert_named_private_file_identity,
    assert_private_file_snapshot,
    fsync_read_stable_private_fd,
)

_ADMISSION_NAME = "admission.json"
_ARTIFACTS_NAME = "artifacts"


class OperationAdmissionPersistenceError(RuntimeError):
    """The exact V3 admission record could not be durably installed."""


@dataclass(frozen=True)
class _PinnedAdmissionRecord:
    record_fd: int
    admission_fd: int
    directories: tuple[tuple[int, str, int], ...]
    artifact_file: tuple[int, str, int]


@dataclass(frozen=True)
class _DurableAdmissionObservation:
    pinned: _PinnedAdmissionRecord
    admission_snapshot: tuple[int, ...]
    artifact_snapshot: tuple[int, ...]
    record: OperationAdmissionStoredRecordV3


def _write_file(dir_fd: int, name: str, raw: bytes) -> None:
    fd = open_private_file(dir_fd, name, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        write_all(fd, raw)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.fsync(dir_fd)


def _write_artifact(record_fd: int, relative_path: str, raw: bytes) -> None:
    current = private_child_dir(record_fd, _ARTIFACTS_NAME)
    opened = [current]
    try:
        parts = relative_path.split("/")
        for part in parts[:-1]:
            current = private_child_dir(current, part)
            opened.append(current)
        _write_file(current, parts[-1], raw)
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)


def persist_operation_admission_record_v3(
    store_fd: int,
    name: str,
    admission: OperationAdmissionV3,
    operation: HeadlessMp4OperationV1,
) -> None:
    """Install one immutable record by a flushed pending-directory rename."""
    pending = f".pending-{name}-{uuid.uuid4().hex}"
    try:
        os.mkdir(pending, 0o700, dir_fd=store_fd)
        os.chmod(pending, 0o700, dir_fd=store_fd, follow_symlinks=False)
        os.fsync(store_fd)
        pending_fd = open_private_child_dir(store_fd, pending)
        try:
            _write_file(pending_fd, _ADMISSION_NAME, admission.document_json)
            _write_artifact(
                pending_fd,
                admission.operation.artifact.relative_path,
                operation.document_json,
            )
            os.fsync(pending_fd)
        finally:
            os.close(pending_fd)
        os.rename(pending, name, src_dir_fd=store_fd, dst_dir_fd=store_fd)
        os.fsync(store_fd)
    except (DurableFileError, OSError) as exc:
        raise OperationAdmissionPersistenceError(
            "cannot persist V3 admission"
        ) from exc


def _close_pinned(pinned: _PinnedAdmissionRecord) -> None:
    os.close(pinned.artifact_file[2])
    for _parent, _name, descriptor in reversed(pinned.directories):
        os.close(descriptor)
    os.close(pinned.admission_fd)
    os.close(pinned.record_fd)


def _open_pinned(
    store_fd: int, name: str, admission: OperationAdmissionV3
) -> _PinnedAdmissionRecord:
    record_fd = open_private_child_dir(store_fd, name)
    admission_fd = None
    directories: list[tuple[int, str, int]] = []
    artifact_fd = None
    try:
        if not exact_directory_entries(
            record_fd, {_ADMISSION_NAME, _ARTIFACTS_NAME}
        ):
            raise DurableFileError("V3 admission record closure changed")
        admission_fd = open_private_file(
            record_fd, _ADMISSION_NAME, os.O_RDONLY
        )
        current = open_private_child_dir(record_fd, _ARTIFACTS_NAME)
        directories.append((record_fd, _ARTIFACTS_NAME, current))
        parts = admission.operation.artifact.relative_path.split("/")
        for part in parts[:-1]:
            if not exact_directory_entries(current, {part}):
                raise DurableFileError("V3 artifact directory closure changed")
            parent = current
            current = open_private_child_dir(current, part)
            directories.append((parent, part, current))
        if not exact_directory_entries(current, {parts[-1]}):
            raise DurableFileError("V3 artifact directory closure changed")
        artifact_fd = open_private_file(current, parts[-1], os.O_RDONLY)
        return _PinnedAdmissionRecord(
            record_fd,
            admission_fd,
            tuple(directories),
            (current, parts[-1], artifact_fd),
        )
    except (DurableFileError, OSError, RuntimeError):
        if artifact_fd is not None:
            os.close(artifact_fd)
        for _parent, _part, descriptor in reversed(directories):
            os.close(descriptor)
        if admission_fd is not None:
            os.close(admission_fd)
        os.close(record_fd)
        raise


def _assert_pinned(
    store_fd: int, name: str, pinned: _PinnedAdmissionRecord
) -> None:
    assert_named_private_directory_identity(store_fd, name, pinned.record_fd)
    if not exact_directory_entries(
        pinned.record_fd, {_ADMISSION_NAME, _ARTIFACTS_NAME}
    ):
        raise DurableFileError("V3 admission record closure changed")
    assert_named_private_file_identity(
        pinned.record_fd, _ADMISSION_NAME, pinned.admission_fd
    )
    for index, (parent_fd, part, descriptor) in enumerate(pinned.directories):
        assert_named_private_directory_identity(parent_fd, part, descriptor)
        expected = (
            pinned.directories[index + 1][1]
            if index + 1 < len(pinned.directories)
            else pinned.artifact_file[1]
        )
        if not exact_directory_entries(descriptor, {expected}):
            raise DurableFileError("V3 artifact directory closure changed")
    artifact_parent, artifact_name, artifact_fd = pinned.artifact_file
    assert_named_private_file_identity(
        artifact_parent, artifact_name, artifact_fd
    )


def _assert_observation(
    store_fd: int, name: str, value: _DurableAdmissionObservation
) -> None:
    _assert_pinned(store_fd, name, value.pinned)
    assert_private_file_snapshot(
        value.pinned.admission_fd, value.admission_snapshot
    )
    assert_private_file_snapshot(
        value.pinned.artifact_file[2], value.artifact_snapshot
    )


def _sync_and_read(
    store_fd: int, name: str, pinned: _PinnedAdmissionRecord
) -> _DurableAdmissionObservation:
    admission_raw, admission_snapshot = fsync_read_stable_private_fd(
        pinned.admission_fd, 1_048_576
    )
    operation_raw, artifact_snapshot = fsync_read_stable_private_fd(
        pinned.artifact_file[2], 16 * 1024 * 1024
    )
    for _parent, _name, descriptor in reversed(pinned.directories):
        os.fsync(descriptor)
    os.fsync(pinned.record_fd)
    os.fsync(store_fd)
    record = load_operation_admission_record_from_bytes_v3(
        name, admission_raw, operation_raw
    )
    return _DurableAdmissionObservation(
        pinned, admission_snapshot, artifact_snapshot, record
    )


def _prepare_pinned(
    store_fd: int, name: str, admission: OperationAdmissionV3
) -> _DurableAdmissionObservation:
    pinned = _open_pinned(store_fd, name, admission)
    try:
        _assert_pinned(store_fd, name, pinned)
        observed = _sync_and_read(store_fd, name, pinned)
        _assert_observation(store_fd, name, observed)
        return observed
    except (DurableFileError, OSError, RuntimeError):
        _close_pinned(pinned)
        raise


@contextlib.contextmanager
def pinned_durable_operation_admission_record_v3(
    store_fd: int, name: str, admission: OperationAdmissionV3
) -> Iterator[OperationAdmissionStoredRecordV3]:
    """Hold and return the exact admission inodes flushed for replay."""
    try:
        observed = _prepare_pinned(store_fd, name, admission)
    except (DurableFileError, OSError, RuntimeError) as exc:
        raise OperationAdmissionPersistenceError(
            "cannot recover V3 admission durability"
        ) from exc
    completed = False
    try:
        yield observed.record
        completed = True
    finally:
        try:
            if completed:
                _assert_observation(store_fd, name, observed)
        except (DurableFileError, OSError) as exc:
            raise OperationAdmissionPersistenceError(
                "V3 admission changed after durability recovery"
            ) from exc
        finally:
            _close_pinned(observed.pinned)


def ensure_operation_admission_record_durable_v3(
    store_fd: int, name: str, admission: OperationAdmissionV3
) -> None:
    """Re-flush a visible final record before accepting it as replayable."""
    with pinned_durable_operation_admission_record_v3(
        store_fd, name, admission
    ):
        pass
