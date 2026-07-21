"""Stable two-pass record-set scan for the durable V3 admission store."""

from __future__ import annotations

from collections.abc import Callable

from .durable_files import DurableFileError, bounded_directory_entries


class OperationAdmissionStoreScanError(RuntimeError):
    """The durable record set changed during one locked scan."""


def _wire_snapshot(records: tuple[object, ...]) -> tuple[tuple, ...]:
    return tuple(
        (
            record.name,
            record.admission.document_json,
            record.operation.document_json,
        )
        for record in records
    )


def load_stable_record_set(
    store_fd: int,
    names: tuple[str, ...],
    loader: Callable[[int, str], object],
    limit: int,
) -> tuple[object, ...]:
    """Reopen every record and exact name before accepting a snapshot."""
    first = tuple(loader(store_fd, name) for name in names)
    try:
        current_names = bounded_directory_entries(store_fd, limit)
    except DurableFileError as exc:
        raise OperationAdmissionStoreScanError(
            "cannot recheck V3 admission store"
        ) from exc
    if current_names != names:
        raise OperationAdmissionStoreScanError(
            "V3 admission store changed during scan"
        )
    second = tuple(loader(store_fd, name) for name in names)
    if _wire_snapshot(first) != _wire_snapshot(second):
        raise OperationAdmissionStoreScanError(
            "V3 admission record changed during scan"
        )
    return second
