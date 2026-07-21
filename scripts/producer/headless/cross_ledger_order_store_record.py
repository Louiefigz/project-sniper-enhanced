"""Stable bounded reader for one cross-ledger order record."""

from __future__ import annotations

import os

from .cross_ledger_order_fs import durable_directory_snapshot
from .cross_ledger_order_schema import (
    CrossLedgerOrderDocumentV1,
    parse_cross_ledger_order_document_v1,
)
from .cross_ledger_order_store_write import (
    INTENT_NAME,
    RECEIPT_NAME,
    RECEIPT_PENDING,
    REJECTION_NAME,
)
from .cross_ledger_order_types import (
    CrossLedgerOrderError,
    CrossLedgerOrderStateV1,
)
from .durable_files import (
    bounded_directory_entries,
    DurableFileError,
    exact_directory_entries,
    open_private_child_dir,
    read_private_file,
)

_MAX_DOCUMENT_BYTES = 16_384


def _read_exact(record_fd: int, name: str) -> bytes:
    first = read_private_file(record_fd, name, _MAX_DOCUMENT_BYTES)
    second = read_private_file(record_fd, name, _MAX_DOCUMENT_BYTES)
    if first != second:
        raise CrossLedgerOrderError("cross-ledger order bytes changed")
    return first


def _parse(record_fd: int, name: str) -> CrossLedgerOrderDocumentV1:
    try:
        return parse_cross_ledger_order_document_v1(
            _read_exact(record_fd, name)
        )
    except (DurableFileError, RuntimeError) as exc:
        raise CrossLedgerOrderError(
            "cross-ledger order document is invalid"
        ) from exc


def _record_values(record_fd: int, names: frozenset[str]) -> tuple:
    if names == {INTENT_NAME}:
        return _parse(record_fd, INTENT_NAME), None, None, "prepared"
    if names in (
        {INTENT_NAME, RECEIPT_NAME},
        {INTENT_NAME, RECEIPT_PENDING},
    ):
        intent = _parse(record_fd, INTENT_NAME)
        receipt_name = (
            RECEIPT_NAME if RECEIPT_NAME in names else RECEIPT_PENDING
        )
        state = (
            "committed" if receipt_name == RECEIPT_NAME else "commit-pending"
        )
        return intent, _parse(record_fd, receipt_name), None, state
    if names == {REJECTION_NAME}:
        return None, None, _parse(record_fd, REJECTION_NAME), "rejected"
    if names == {INTENT_NAME, REJECTION_NAME}:
        return (
            _parse(record_fd, INTENT_NAME),
            None,
            _parse(record_fd, REJECTION_NAME),
            "rejected",
        )
    raise CrossLedgerOrderError("cross-ledger order record closure is invalid")


def load_cross_ledger_order_record_from_fd_v1(
    record_fd: int, name: str
) -> CrossLedgerOrderStateV1:
    """Read one record through an already-pinned directory handle."""
    before = durable_directory_snapshot(os.fstat(record_fd))
    names = frozenset(bounded_directory_entries(record_fd, 3))
    intent, receipt, rejection, state = _record_values(record_fd, names)
    after = durable_directory_snapshot(os.fstat(record_fd))
    if before != after or not exact_directory_entries(record_fd, names):
        raise CrossLedgerOrderError("cross-ledger order record changed")
    return CrossLedgerOrderStateV1(state, name, intent, receipt, rejection)


def load_cross_ledger_order_record_v1(
    store_fd: int, name: str
) -> CrossLedgerOrderStateV1:
    """Read one named record with endpoint mutation checks."""
    record_fd = open_private_child_dir(store_fd, name)
    try:
        return load_cross_ledger_order_record_from_fd_v1(record_fd, name)
    finally:
        os.close(record_fd)
