"""Reconcile materialized ``FENCE`` only from explicit journal states."""

from __future__ import annotations

import os

from .active_fence_lock import (
    ActiveFenceLockV1,
    validate_active_fence_lock_v1,
)
from .active_fence_schema import (
    ActiveFenceSchemaError,
    parse_active_fence_document_v1,
)
from .active_fence_types import (
    ActiveFenceJournalScanV1,
    ActiveFenceStateV1,
)
from .durable_files import (
    DurableFileError,
    assert_private_lock_identity,
    open_private_file,
    read_private_file,
    write_pending_replace,
)

ACTIVE_FENCE_NAME = "FENCE"
ACTIVE_FENCE_PENDING_NAME = ".FENCE.pending"
_MAX_FENCE_BYTES = 4_096


class ActiveFenceMaterializedError(RuntimeError):
    """The FENCE projection is forged or cannot be reconciled safely."""


def _exists(root_fd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise ActiveFenceMaterializedError(
            "active-fence projection path cannot be inspected"
        ) from exc


def require_unmaterialized_active_fence_v1(lock: ActiveFenceLockV1) -> None:
    """Require no orphan projection before creating a missing journal."""
    validate_active_fence_lock_v1(lock)
    names = (ACTIVE_FENCE_NAME, ACTIVE_FENCE_PENDING_NAME)
    if any(_exists(lock.root_fd, name) for name in names):
        raise ActiveFenceMaterializedError(
            "active-fence projection exists without a journal"
        )


def _read_optional(lock: ActiveFenceLockV1) -> ActiveFenceStateV1 | None:
    try:
        raw = read_private_file(
            lock.root_fd, ACTIVE_FENCE_NAME, _MAX_FENCE_BYTES
        )
    except DurableFileError as exc:
        if isinstance(exc.__cause__, FileNotFoundError):
            return None
        raise ActiveFenceMaterializedError(
            "materialized active fence is unsafe"
        ) from exc
    try:
        return parse_active_fence_document_v1(raw)
    except ActiveFenceSchemaError as exc:
        raise ActiveFenceMaterializedError(str(exc)) from exc


def _validate_pending(lock: ActiveFenceLockV1) -> bool:
    if not _exists(lock.root_fd, ACTIVE_FENCE_PENDING_NAME):
        return False
    try:
        fd = open_private_file(
            lock.root_fd, ACTIVE_FENCE_PENDING_NAME, os.O_RDWR
        )
    except DurableFileError as exc:
        raise ActiveFenceMaterializedError(
            "active-fence pending projection is unsafe"
        ) from exc
    os.close(fd)
    return True


def _install(lock: ActiveFenceLockV1, state: ActiveFenceStateV1) -> None:
    _validate_pending(lock)
    try:
        write_pending_replace(
            lock.root_fd,
            (ACTIVE_FENCE_PENDING_NAME, ACTIVE_FENCE_NAME),
            state.document_json,
        )
    except (DurableFileError, OSError) as exc:
        raise ActiveFenceMaterializedError(
            "active-fence projection cannot be installed"
        ) from exc
    if _exists(lock.root_fd, ACTIVE_FENCE_PENDING_NAME):
        raise ActiveFenceMaterializedError(
            "active-fence projection changed after installation"
        )
    _resync_current(lock, state)


def _resync_current(
    lock: ActiveFenceLockV1, expected: ActiveFenceStateV1
) -> None:
    fd = None
    try:
        fd = open_private_file(lock.root_fd, ACTIVE_FENCE_NAME, os.O_RDONLY)
        before = os.fstat(fd)
        os.fsync(fd)
        os.fsync(lock.root_fd)
        assert_private_lock_identity(lock.root_fd, ACTIVE_FENCE_NAME, fd)
        raw = os.pread(fd, _MAX_FENCE_BYTES + 1, 0)
        if len(raw) > _MAX_FENCE_BYTES:
            raise ActiveFenceMaterializedError(
                "materialized active fence exceeds size limit"
            )
        observed = parse_active_fence_document_v1(raw)
        after = os.fstat(fd)
        stable = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) == (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if not stable:
            raise ActiveFenceMaterializedError(
                "active-fence projection changed during recovery barrier"
            )
        assert_private_lock_identity(lock.root_fd, ACTIVE_FENCE_NAME, fd)
        validate_active_fence_lock_v1(lock)
    except ActiveFenceMaterializedError:
        raise
    except (ActiveFenceSchemaError, DurableFileError, OSError) as exc:
        raise ActiveFenceMaterializedError(
            "active-fence projection recovery barrier failed"
        ) from exc
    finally:
        if fd is not None:
            os.close(fd)
    if observed != expected:
        raise ActiveFenceMaterializedError(
            "active-fence projection changed across recovery barrier"
        )


def reconcile_materialized_active_fence_v1(
    lock: ActiveFenceLockV1,
    scan: ActiveFenceJournalScanV1,
) -> ActiveFenceStateV1:
    """Advance a missing/stale projection only to the explicit journal tail."""
    validate_active_fence_lock_v1(lock)
    if (
        type(scan) is not ActiveFenceJournalScanV1
        or scan.torn_bytes
        or not scan.transitions
    ):
        raise ActiveFenceMaterializedError(
            "active-fence journal has no committed state"
        )
    tail = scan.transitions[-1].state
    current = _read_optional(lock)
    pending = _validate_pending(lock)
    if current == tail:
        if pending:
            raise ActiveFenceMaterializedError(
                "unexpected pending projection accompanies current FENCE"
            )
        _resync_current(lock, tail)
        return tail
    history = tuple(item.state for item in scan.transitions)
    recoverable_missing = current is None and len(history) == 1
    recoverable_stale = current is not None and current in history[:-1]
    if not recoverable_missing and not recoverable_stale:
        raise ActiveFenceMaterializedError(
            "materialized active fence is not a journal prefix"
        )
    _install(lock, tail)
    return tail
