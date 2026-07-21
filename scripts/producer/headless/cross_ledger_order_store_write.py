"""Durable low-level writers for the cross-ledger order state machine."""

from __future__ import annotations

import os
import uuid

from .cross_ledger_order_lock import CrossLedgerOrderLockV1
from .durable_files import (
    DurableFileError,
    open_private_child_dir,
    open_private_file,
    private_child_dir,
    write_all,
)

STORE_NAME = "cross-ledger-orders-v1"
INTENT_NAME = "intent.json"
RECEIPT_NAME = "receipt.json"
RECEIPT_PENDING = ".receipt.pending"
REJECTION_NAME = "rejection.json"


class CrossLedgerOrderWriteError(RuntimeError):
    """An order state transition could not be durably persisted."""


def _write_file(dir_fd: int, name: str, raw: bytes) -> None:
    fd = open_private_file(dir_fd, name, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        write_all(fd, raw)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.fsync(dir_fd)


def create_cross_ledger_order_record_v1(
    lock: CrossLedgerOrderLockV1,
    name: str,
    final_name: str,
    raw: bytes,
) -> None:
    """Install one single-document order record by atomic rename."""
    store_fd = private_child_dir(lock.root_fd, STORE_NAME)
    pending = f".pending-{name}-{uuid.uuid4().hex}"
    try:
        os.mkdir(pending, 0o700, dir_fd=store_fd)
        os.chmod(pending, 0o700, dir_fd=store_fd, follow_symlinks=False)
        os.fsync(store_fd)
        record_fd = open_private_child_dir(store_fd, pending)
        try:
            _write_file(record_fd, final_name, raw)
        finally:
            os.close(record_fd)
        os.rename(pending, name, src_dir_fd=store_fd, dst_dir_fd=store_fd)
        os.fsync(store_fd)
    except (DurableFileError, OSError) as exc:
        raise CrossLedgerOrderWriteError(
            "cannot persist cross-ledger order"
        ) from exc
    finally:
        os.close(store_fd)


def _assert_pending_identity(record_fd: int, pending_fd: int) -> None:
    try:
        held = os.fstat(pending_fd)
        named = os.stat(
            RECEIPT_PENDING,
            dir_fd=record_fd,
            follow_symlinks=False,
        )
    except OSError as exc:
        raise CrossLedgerOrderWriteError(
            "pending cross-ledger receipt identity changed"
        ) from exc
    if (held.st_dev, held.st_ino) != (named.st_dev, named.st_ino):
        raise CrossLedgerOrderWriteError(
            "pending cross-ledger receipt inode was replaced"
        )


def _resync_pending_receipt(record_fd: int, raw: bytes) -> None:
    fd = open_private_file(record_fd, RECEIPT_PENDING, os.O_RDONLY)
    try:
        _assert_pending_identity(record_fd, fd)
        if os.pread(fd, len(raw) + 1, 0) != raw:
            raise CrossLedgerOrderWriteError(
                "pending cross-ledger receipt bytes conflict"
            )
        os.fsync(fd)
        if os.pread(fd, len(raw) + 1, 0) != raw:
            raise CrossLedgerOrderWriteError(
                "pending cross-ledger receipt bytes changed"
            )
        _assert_pending_identity(record_fd, fd)
        os.fsync(record_fd)
        _assert_pending_identity(record_fd, fd)
    finally:
        os.close(fd)


def append_cross_ledger_order_receipt_v1(
    lock: CrossLedgerOrderLockV1,
    record_name: str,
    raw: bytes,
    recover_pending: bool,
) -> None:
    """Append COMMITTED or finish an exact flushed pending receipt."""
    store_fd = open_private_child_dir(lock.root_fd, STORE_NAME)
    record_fd = None
    try:
        record_fd = open_private_child_dir(store_fd, record_name)
        if recover_pending:
            _resync_pending_receipt(record_fd, raw)
        else:
            _write_file(record_fd, RECEIPT_PENDING, raw)
        os.rename(
            RECEIPT_PENDING,
            RECEIPT_NAME,
            src_dir_fd=record_fd,
            dst_dir_fd=record_fd,
        )
        os.fsync(record_fd)
    except (DurableFileError, OSError) as exc:
        raise CrossLedgerOrderWriteError(
            "cannot commit cross-ledger order"
        ) from exc
    finally:
        if record_fd is not None:
            os.close(record_fd)
        os.close(store_fd)


def append_cross_ledger_order_rejection_v1(
    lock: CrossLedgerOrderLockV1, record_name: str, raw: bytes
) -> None:
    """Append a permanent fail-closed rejection to PREPARED state."""
    store_fd = open_private_child_dir(lock.root_fd, STORE_NAME)
    record_fd = None
    try:
        record_fd = open_private_child_dir(store_fd, record_name)
        _write_file(record_fd, REJECTION_NAME, raw)
    except (DurableFileError, OSError) as exc:
        raise CrossLedgerOrderWriteError(
            "cannot reject cross-ledger order"
        ) from exc
    finally:
        if record_fd is not None:
            os.close(record_fd)
        os.close(store_fd)
