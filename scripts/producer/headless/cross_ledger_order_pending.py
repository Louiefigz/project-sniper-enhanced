"""Writer-only recovery of uncommitted cross-ledger record directories."""

from __future__ import annotations

import os
import re

from .authority_record import read_authority_record
from .cross_ledger_order_lock import (
    CrossLedgerOrderLockV1,
    validate_cross_ledger_order_lock_v1,
)
from .cross_ledger_order_store_write import (
    INTENT_NAME,
    REJECTION_NAME,
    STORE_NAME,
)
from .cross_ledger_order_schema import (
    CrossLedgerOrderSchemaError,
    parse_cross_ledger_order_document_v1,
)
from .cross_ledger_order_store import cross_ledger_order_record_name_v1
from .cross_ledger_order_recovery import (
    reconcile_cross_ledger_pending_receipts_v1,
)
from .durable_files import (
    bounded_directory_entries,
    DurableFileError,
    open_private_child_dir,
)
from .pending_cleanup_fs import (
    PendingCleanupFileError,
    remove_empty_private_pending_dir,
    remove_private_pending_file,
)

_PENDING = re.compile(r"\.pending-([0-9a-f]{64})-([0-9a-f]{32})")
_MAX_ENTRIES = 100_000
_MAX_DOCUMENT_BYTES = 16_384


class CrossLedgerOrderPendingError(RuntimeError):
    """Abandoned order-record scratch state is unsafe or ambiguous."""


def _open_store(lock: CrossLedgerOrderLockV1) -> int | None:
    try:
        return open_private_child_dir(lock.root_fd, STORE_NAME)
    except DurableFileError as exc:
        if isinstance(exc.__cause__, FileNotFoundError):
            return None
        raise CrossLedgerOrderPendingError("order store is unsafe") from exc


def _pending_targets(names: tuple[str, ...]) -> dict[str, str]:
    pending = {}
    for name in names:
        if not name.startswith(".pending-"):
            continue
        match = _PENDING.fullmatch(name)
        if match is None or match.group(1) in pending:
            raise CrossLedgerOrderPendingError(
                "order pending identity is ambiguous"
            )
        pending[match.group(1)] = name
    if any(target in names for target in pending):
        raise CrossLedgerOrderPendingError(
            "order pending and final records coexist"
        )
    return pending


def _validate_document_target(raw: bytes, file_name: str, target: str) -> None:
    try:
        document = parse_cross_ledger_order_document_v1(raw)
    except CrossLedgerOrderSchemaError:
        return
    expected_file = (
        INTENT_NAME if document.state == "prepared" else REJECTION_NAME
    )
    expected_target = cross_ledger_order_record_name_v1(
        document.identity.idempotency_key
    )
    if (file_name, target) != (expected_file, expected_target):
        raise CrossLedgerOrderPendingError(
            "order pending identity disagrees with its target"
        )


def _discard(store_fd: int, name: str, target: str) -> None:
    record_fd = open_private_child_dir(store_fd, name)
    try:
        entries = bounded_directory_entries(record_fd, 2)
        allowed = {INTENT_NAME, REJECTION_NAME}
        if len(entries) > 1 or any(entry not in allowed for entry in entries):
            raise CrossLedgerOrderPendingError(
                "order pending closure is unsafe"
            )
        if entries:
            remove_private_pending_file(
                record_fd,
                entries[0],
                _MAX_DOCUMENT_BYTES,
                lambda raw: _validate_document_target(raw, entries[0], target),
            )
    finally:
        os.close(record_fd)
    remove_empty_private_pending_dir(store_fd, name)


def cleanup_abandoned_cross_ledger_order_pending_v1(lock: object) -> None:
    """Discard only pre-rename records while the shared writer lock is held."""
    try:
        validate_cross_ledger_order_lock_v1(lock)
        store_fd = _open_store(lock)
        if store_fd is None:
            return
        try:
            before = bounded_directory_entries(store_fd, _MAX_ENTRIES)
            pending = _pending_targets(before)
            retained = frozenset(set(before) - set(pending.values()))
            for target, name in pending.items():
                _discard(store_fd, name, target)
            after = frozenset(
                bounded_directory_entries(store_fd, _MAX_ENTRIES)
            )
            if after != retained:
                raise CrossLedgerOrderPendingError(
                    "order store changed during pending cleanup"
                )
            authority = read_authority_record(lock.root_fd)
            if authority is None:
                raise CrossLedgerOrderPendingError(
                    "order store has no retained authority identity"
                )
            reconcile_cross_ledger_pending_receipts_v1(
                store_fd, authority["authorityId"]
            )
        finally:
            os.close(store_fd)
    except CrossLedgerOrderPendingError:
        raise
    except (DurableFileError, PendingCleanupFileError, RuntimeError) as exc:
        raise CrossLedgerOrderPendingError(
            "order pending cleanup failed"
        ) from exc
