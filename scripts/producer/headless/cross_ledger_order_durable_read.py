"""Descriptor-pinned durability reads for cross-ledger replay decisions."""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from dataclasses import dataclass

from . import cross_ledger_order_recovery as recovery
from .cross_ledger_order_fs import (
    cross_ledger_order_record_name_v1,
    durable_directory_snapshot,
)
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
from .cross_ledger_order_types import CrossLedgerOrderStateV1
from .durable_files import (
    DurableFileError,
    exact_directory_entries,
    open_private_child_dir,
    open_private_file,
)
from .record_durability import (
    assert_named_private_file_identity,
    assert_private_file_snapshot,
    fsync_read_stable_private_fd,
    read_stable_private_fd,
)
from .wire_identity import same_wire_value

_MAX_DOCUMENT_BYTES = 16_384


@dataclass(frozen=True)
class _PinnedOrderRecord:
    name: str
    record_fd: int
    files: tuple[tuple[str, int], ...]
    closure: frozenset[str]
    baseline: tuple[int, ...]
    raw: tuple[tuple[str, bytes], ...]
    snapshots: tuple[tuple[str, tuple[int, ...]], ...]
    state: CrossLedgerOrderStateV1


def _parse(raw: bytes) -> CrossLedgerOrderDocumentV1:
    try:
        return parse_cross_ledger_order_document_v1(raw)
    except RuntimeError as exc:
        raise recovery.CrossLedgerOrderRecoveryError(
            "cross-ledger durable bytes are invalid"
        ) from exc


def _state_values(raw: dict[str, bytes], names: frozenset[str]) -> tuple:
    if names == {INTENT_NAME}:
        return _parse(raw[INTENT_NAME]), None, None, "prepared"
    if names in ({INTENT_NAME, RECEIPT_NAME}, {INTENT_NAME, RECEIPT_PENDING}):
        receipt_name = (
            RECEIPT_NAME if RECEIPT_NAME in names else RECEIPT_PENDING
        )
        state = (
            "committed" if receipt_name == RECEIPT_NAME else "commit-pending"
        )
        return _parse(raw[INTENT_NAME]), _parse(raw[receipt_name]), None, state
    if names == {REJECTION_NAME}:
        return None, None, _parse(raw[REJECTION_NAME]), "rejected"
    if names == {INTENT_NAME, REJECTION_NAME}:
        return (
            _parse(raw[INTENT_NAME]),
            None,
            _parse(raw[REJECTION_NAME]),
            "rejected",
        )
    raise recovery.CrossLedgerOrderRecoveryError(
        "cross-ledger durable closure is invalid"
    )


def _build_state(
    name: str, pairs: tuple[tuple[str, bytes], ...]
) -> CrossLedgerOrderStateV1:
    raw = dict(pairs)
    intent, receipt, rejection, state = _state_values(raw, frozenset(raw))
    result = CrossLedgerOrderStateV1(state, name, intent, receipt, rejection)
    documents = tuple(
        row for row in (intent, receipt, rejection) if row is not None
    )
    identity = documents[0].identity
    valid = all(
        same_wire_value(row.identity, identity) for row in documents
    ) and name == cross_ledger_order_record_name_v1(identity.idempotency_key)
    if receipt is not None:
        valid = valid and receipt.intent_digest == intent.document_digest
    if not valid:
        raise recovery.CrossLedgerOrderRecoveryError(
            "cross-ledger durable state is inconsistent"
        )
    return result


def _close_record(pinned: _PinnedOrderRecord) -> None:
    for _name, descriptor in reversed(pinned.files):
        os.close(descriptor)
    os.close(pinned.record_fd)


def _read_files(files: tuple[tuple[str, int], ...]) -> tuple:
    return tuple(
        (name, read_stable_private_fd(fd, _MAX_DOCUMENT_BYTES))
        for name, fd in files
    )


def _sync_read_files(files: tuple[tuple[str, int], ...]) -> tuple:
    raw, snapshots = [], []
    for name, descriptor in files:
        value, snapshot = fsync_read_stable_private_fd(
            descriptor, _MAX_DOCUMENT_BYTES
        )
        raw.append((name, value))
        snapshots.append((name, snapshot))
    return tuple(raw), tuple(snapshots)


def _assert_record(store_fd: int, pinned: _PinnedOrderRecord) -> None:
    recovery._assert_record_identity(store_fd, pinned.name, pinned.record_fd)
    for file_name, descriptor in pinned.files:
        assert_named_private_file_identity(
            pinned.record_fd, file_name, descriptor
        )
    snapshots = dict(pinned.snapshots)
    for file_name, descriptor in pinned.files:
        assert_private_file_snapshot(descriptor, snapshots[file_name])
    raw = _read_files(pinned.files)
    state = _build_state(pinned.name, raw)
    unchanged = (
        durable_directory_snapshot(os.fstat(pinned.record_fd))
        == pinned.baseline
    )
    closed = exact_directory_entries(pinned.record_fd, pinned.closure)
    if raw != pinned.raw or not same_wire_value(state, pinned.state):
        raise recovery.CrossLedgerOrderRecoveryError(
            "cross-ledger durable bytes changed"
        )
    if not unchanged or not closed:
        raise recovery.CrossLedgerOrderRecoveryError(
            "cross-ledger durable record changed"
        )


def _open_record(store_fd: int, name: str) -> _PinnedOrderRecord:
    record_fd = open_private_child_dir(store_fd, name)
    files: list[tuple[str, int]] = []
    try:
        recovery._assert_record_identity(store_fd, name, record_fd)
        closure = recovery._record_closure(record_fd)
        baseline = durable_directory_snapshot(os.fstat(record_fd))
        for file_name in sorted(closure):
            descriptor = open_private_file(record_fd, file_name, os.O_RDONLY)
            files.append((file_name, descriptor))
        for file_name, descriptor in files:
            assert_named_private_file_identity(
                record_fd, file_name, descriptor
            )
        raw, snapshots = _sync_read_files(tuple(files))
        os.fsync(record_fd)
        pinned = _PinnedOrderRecord(
            name,
            record_fd,
            tuple(files),
            closure,
            baseline,
            raw,
            snapshots,
            _build_state(name, raw),
        )
        _assert_record(store_fd, pinned)
        return pinned
    except (DurableFileError, OSError, RuntimeError):
        for _file_name, descriptor in reversed(files):
            os.close(descriptor)
        os.close(record_fd)
        raise


def _validate_targets(
    targets: frozenset[str], expected: frozenset[str]
) -> None:
    valid = (
        type(targets) is frozenset
        and len(targets) <= 3
        and targets <= expected
        and all(recovery._RECORD.fullmatch(name) for name in targets)
    )
    if not valid:
        raise recovery.CrossLedgerOrderRecoveryError(
            "cross-ledger recovery targets are invalid"
        )


@contextlib.contextmanager
def pinned_durable_cross_ledger_order_records_v1(
    store_fd: int,
    targets: frozenset[str],
    expected: frozenset[str],
) -> Iterator[tuple[CrossLedgerOrderStateV1, ...]]:
    """Keep exact flushed rows pinned across the caller's named reload."""
    _validate_targets(targets, expected)
    pinned: list[_PinnedOrderRecord] = []
    try:
        for name in sorted(targets):
            pinned.append(_open_record(store_fd, name))
        if targets:
            os.fsync(store_fd)
        if not exact_directory_entries(store_fd, expected):
            raise recovery.CrossLedgerOrderRecoveryError(
                "cross-ledger recovery store changed after barrier"
            )
    except (DurableFileError, OSError, RuntimeError):
        for item in reversed(pinned):
            _close_record(item)
        raise
    completed = False
    try:
        yield tuple(item.state for item in pinned)
        completed = True
    finally:
        try:
            if completed:
                for item in pinned:
                    _assert_record(store_fd, item)
                if not exact_directory_entries(store_fd, expected):
                    raise recovery.CrossLedgerOrderRecoveryError(
                        "cross-ledger store changed across named reload"
                    )
        finally:
            for item in reversed(pinned):
                _close_record(item)
