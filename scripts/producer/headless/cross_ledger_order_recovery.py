"""Writer-only durability recovery for retained cross-ledger records."""

from __future__ import annotations

import os
import re
import stat

from .cross_ledger_order_fs import (
    cross_ledger_order_record_name_v1,
    durable_directory_snapshot,
)
from .cross_ledger_order_schema import (
    CrossLedgerOrderDocumentV1,
    build_cross_ledger_order_receipt_v1,
    parse_cross_ledger_order_document_v1,
)
from .cross_ledger_order_store_record import (
    load_cross_ledger_order_record_from_fd_v1,
)
from .cross_ledger_order_store_write import (
    INTENT_NAME,
    RECEIPT_NAME,
    RECEIPT_PENDING,
    REJECTION_NAME,
)
from .durable_files import (
    bounded_directory_entries,
    exact_directory_entries,
    open_private_child_dir,
    open_private_file,
    read_private_file,
    write_all,
)
from .pending_cleanup_fs import remove_private_pending_file
from .wire_identity import same_wire_value

_RECORD = re.compile(r"[0-9a-f]{64}")
_MAX_RECORDS = 50_000
_MAX_DOCUMENT_BYTES = 16_384
_SAFE_CLOSURES = {
    frozenset({INTENT_NAME}),
    frozenset({REJECTION_NAME}),
    frozenset({INTENT_NAME, REJECTION_NAME}),
    frozenset({INTENT_NAME, RECEIPT_NAME}),
    frozenset({INTENT_NAME, RECEIPT_PENDING}),
}


class CrossLedgerOrderRecoveryError(RuntimeError):
    """Visible cross-ledger state cannot be made durably unambiguous."""


def _assert_record_identity(store_fd: int, name: str, record_fd: int) -> None:
    try:
        held = os.fstat(record_fd)
        named = os.stat(name, dir_fd=store_fd, follow_symlinks=False)
    except OSError as exc:
        raise CrossLedgerOrderRecoveryError(
            "cross-ledger record identity cannot be reobserved"
        ) from exc
    private = all(
        stat.S_ISDIR(info.st_mode)
        and info.st_uid == os.geteuid()
        and stat.S_IMODE(info.st_mode) == 0o700
        for info in (held, named)
    )
    if (held.st_dev, held.st_ino) != (
        named.st_dev,
        named.st_ino,
    ) or not private:
        raise CrossLedgerOrderRecoveryError(
            "cross-ledger record inode was replaced"
        )


def _stable_bytes(record_fd: int, name: str) -> bytes:
    first = read_private_file(record_fd, name, _MAX_DOCUMENT_BYTES)
    second = read_private_file(record_fd, name, _MAX_DOCUMENT_BYTES)
    if first != second:
        raise CrossLedgerOrderRecoveryError(
            "cross-ledger recovery bytes changed"
        )
    return first


def _intent(
    record_fd: int, record_name: str, authority_id: str
) -> CrossLedgerOrderDocumentV1:
    try:
        intent = parse_cross_ledger_order_document_v1(
            _stable_bytes(record_fd, INTENT_NAME)
        )
    except RuntimeError as exc:
        raise CrossLedgerOrderRecoveryError(
            "cross-ledger recovery intent is invalid"
        ) from exc
    expected_name = cross_ledger_order_record_name_v1(
        intent.identity.idempotency_key
    )
    valid = (
        intent.state == "prepared"
        and expected_name == record_name
        and intent.identity.authority_id == authority_id
    )
    if not valid:
        raise CrossLedgerOrderRecoveryError(
            "cross-ledger recovery intent identity is invalid"
        )
    return intent


def _write_pending_receipt(record_fd: int, raw: bytes) -> None:
    fd = open_private_file(
        record_fd,
        RECEIPT_PENDING,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
    )
    try:
        write_all(fd, raw)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.fsync(record_fd)


def _repair_incomplete_receipt(
    record_fd: int,
    intent: CrossLedgerOrderDocumentV1,
) -> None:
    expected = build_cross_ledger_order_receipt_v1(
        intent.identity, intent.document_digest
    )
    raw = _stable_bytes(record_fd, RECEIPT_PENDING)
    if raw == expected:
        return
    _assert_incomplete_receipt(raw, expected)
    remove_private_pending_file(
        record_fd,
        RECEIPT_PENDING,
        _MAX_DOCUMENT_BYTES,
        lambda current: _assert_incomplete_receipt(current, expected),
    )
    _write_pending_receipt(record_fd, expected)


def _assert_incomplete_receipt(raw: bytes, expected: bytes) -> None:
    try:
        parse_cross_ledger_order_document_v1(raw)
    except RuntimeError:
        parsed = False
    else:
        parsed = True
    incomplete = len(raw) < len(expected) and expected.startswith(raw)
    if parsed or not incomplete:
        raise CrossLedgerOrderRecoveryError(
            "cross-ledger pending receipt conflicts with deterministic bytes"
        )


def _sync_file(record_fd: int, name: str) -> bytes:
    before = _stable_bytes(record_fd, name)
    fd = open_private_file(record_fd, name, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    after = _stable_bytes(record_fd, name)
    if before != after:
        raise CrossLedgerOrderRecoveryError(
            "cross-ledger file changed across recovery barrier"
        )
    return before


def _validate_state(record_fd: int, name: str) -> object:
    state = load_cross_ledger_order_record_from_fd_v1(record_fd, name)
    documents = tuple(
        row
        for row in (state.intent, state.receipt, state.rejection)
        if row is not None
    )
    identity = documents[0].identity
    valid = all(
        same_wire_value(row.identity, identity) for row in documents
    ) and name == cross_ledger_order_record_name_v1(identity.idempotency_key)
    if state.receipt is not None:
        valid = valid and (
            state.receipt.intent_digest == state.intent.document_digest
        )
    if not valid:
        raise CrossLedgerOrderRecoveryError(
            "cross-ledger recovery state is inconsistent"
        )
    return state


def _record_closure(record_fd: int) -> frozenset[str]:
    names = frozenset(bounded_directory_entries(record_fd, 3))
    if names not in _SAFE_CLOSURES:
        raise CrossLedgerOrderRecoveryError(
            "cross-ledger recovery closure is invalid"
        )
    return names


def _sync_validated_record(store_fd: int, name: str) -> None:
    record_fd = open_private_child_dir(store_fd, name)
    try:
        _assert_record_identity(store_fd, name, record_fd)
        names = _record_closure(record_fd)
        baseline = durable_directory_snapshot(os.fstat(record_fd))
        before = _validate_state(record_fd, name)
        for file_name in sorted(names):
            _sync_file(record_fd, file_name)
        os.fsync(record_fd)
        after = _validate_state(record_fd, name)
        stable = same_wire_value(before, after) and exact_directory_entries(
            record_fd, names
        )
        unchanged = baseline == durable_directory_snapshot(os.fstat(record_fd))
        _assert_record_identity(store_fd, name, record_fd)
        if not stable or not unchanged:
            raise CrossLedgerOrderRecoveryError(
                "cross-ledger record changed during recovery"
            )
    finally:
        os.close(record_fd)


def _record_names(store_fd: int) -> tuple[str, ...]:
    names = bounded_directory_entries(store_fd, _MAX_RECORDS)
    if any(not _RECORD.fullmatch(name) for name in names):
        raise CrossLedgerOrderRecoveryError(
            "cross-ledger recovery store has unknown entries"
        )
    return names


def _reconcile_pending_record(
    store_fd: int, name: str, authority_id: str
) -> None:
    record_fd = open_private_child_dir(store_fd, name)
    try:
        _assert_record_identity(store_fd, name, record_fd)
        names = _record_closure(record_fd)
        if RECEIPT_PENDING not in names:
            return
        intent = _intent(record_fd, name, authority_id)
        _repair_incomplete_receipt(record_fd, intent)
        _assert_record_identity(store_fd, name, record_fd)
    finally:
        os.close(record_fd)
    _sync_validated_record(store_fd, name)


def reconcile_cross_ledger_pending_receipts_v1(
    store_fd: int, authority_id: str
) -> None:
    """Repair and flush pending receipts without promoting COMMITTED."""
    names = _record_names(store_fd)
    for name in names:
        _reconcile_pending_record(store_fd, name, authority_id)
    if not exact_directory_entries(store_fd, frozenset(names)):
        raise CrossLedgerOrderRecoveryError(
            "cross-ledger recovery store changed"
        )


def reflush_cross_ledger_order_records_v1(
    store_fd: int,
    record_names: frozenset[str],
    expected_names: frozenset[str],
) -> None:
    """Flush only request-relevant final records and their parent."""
    valid = (
        type(record_names) is frozenset
        and len(record_names) <= 3
        and record_names <= expected_names
        and all(_RECORD.fullmatch(name) for name in record_names)
    )
    if not valid:
        raise CrossLedgerOrderRecoveryError(
            "cross-ledger recovery targets are invalid"
        )
    for name in sorted(record_names):
        _sync_validated_record(store_fd, name)
    if not record_names:
        return
    os.fsync(store_fd)
    if not exact_directory_entries(store_fd, expected_names):
        raise CrossLedgerOrderRecoveryError(
            "cross-ledger recovery store changed after durability barrier"
        )
