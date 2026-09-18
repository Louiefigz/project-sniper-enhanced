"""Atomic attempt-owned storage for a complete graphic render receipt set."""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Callable
from typing import TypeVar

from .durable_files import (
    locked_existing_private_dir,
    locked_private_dir,
)
from .graphic_render_receipt_semantics import GraphicRenderReceiptV1
from .graphic_render_receipt_set_manifest import (
    build_set_manifest,
    validate_expectation,
)
from .graphic_render_receipt_store_io import (
    FINAL_NAME,
    LOCK_NAME,
    PENDING_NAME,
    open_store,
    persist_documents,
    receipt_store_path,
    store_entries,
)
from .graphic_render_receipt_store_reader import (
    MANIFEST_NAME,
    read_final_receipt_set,
)
from .graphic_render_receipt_store_types import (
    GraphicRenderReceiptSetExpectationV1,
    GraphicRenderReceiptSetLocatorV1,
    GraphicRenderReceiptStoreError,
    StoredGraphicRenderReceiptSetV1,
)
from .graphic_render_receipt_store_validation import checked_receipts

_DIGEST = re.compile(r"[0-9a-f]{64}")
_T = TypeVar("_T")


def _normalized(label: str, operation: Callable[[], _T]) -> _T:
    try:
        return operation()
    except GraphicRenderReceiptStoreError:
        raise
    except (OSError, RuntimeError) as exc:
        raise GraphicRenderReceiptStoreError(
            f"graphic receipt store cannot {label}"
        ) from exc


def _documents(
    expectation: GraphicRenderReceiptSetExpectationV1,
    receipts: tuple[GraphicRenderReceiptV1, ...],
) -> dict[str, bytes]:
    rows, documents = [], {}
    for index, receipt in enumerate(receipts):
        name = f"receipt-{index:04d}.json"
        raw = receipt.document_json
        documents[name] = raw
        rows.append(
            {
                "file": name,
                "graphicId": receipt.graphic_id,
                "ordinal": index,
                "selectionId": receipt.selection_id,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "sizeBytes": len(raw),
            }
        )
    documents[MANIFEST_NAME] = build_set_manifest(expectation, tuple(rows))
    return documents


def _store(
    attempt_root: str,
    expectation: GraphicRenderReceiptSetExpectationV1,
    receipts: tuple[GraphicRenderReceiptV1, ...],
) -> StoredGraphicRenderReceiptSetV1:
    checked = checked_receipts(receipts, expectation)
    documents = _documents(expectation, checked)
    receipt_store_path(attempt_root)
    with locked_private_dir(attempt_root, LOCK_NAME) as root_fd:
        opened = open_store(root_fd, True)
        if opened is None:  # pragma: no cover - create=True is total
            raise GraphicRenderReceiptStoreError(
                "graphic receipt store is absent"
            )
        work_fd, store_fd = opened
        try:
            names = store_entries(store_fd)
            if FINAL_NAME in names:
                stored = read_final_receipt_set(store_fd, expectation, True)
                if tuple(
                    row.document_json for row in stored.receipts
                ) != tuple(row.document_json for row in checked):
                    raise GraphicRenderReceiptStoreError(
                        "graphic receipt replay bytes conflict"
                    )
                return stored
            persist_documents(store_fd, documents)
            return read_final_receipt_set(store_fd, expectation, False)
        finally:
            os.close(store_fd)
            os.close(work_fd)


def store_graphic_render_receipt_set(
    attempt_root: str,
    expectation: GraphicRenderReceiptSetExpectationV1,
    receipts: tuple[GraphicRenderReceiptV1, ...],
) -> StoredGraphicRenderReceiptSetV1:
    """Atomically publish all receipts, or replay the exact retained set."""
    return _normalized(
        "persist exact bytes",
        lambda: _store(attempt_root, expectation, receipts),
    )


def _load(
    attempt_root: str,
    expectation: GraphicRenderReceiptSetExpectationV1,
    locator: GraphicRenderReceiptSetLocatorV1,
) -> StoredGraphicRenderReceiptSetV1:
    validate_expectation(expectation)
    valid = type(locator) is GraphicRenderReceiptSetLocatorV1
    valid = valid and type(locator.manifest_sha256) is str
    valid = valid and bool(_DIGEST.fullmatch(locator.manifest_sha256))
    valid = valid and type(locator.receipt_count) is int
    valid = valid and locator.receipt_count == 1
    if not valid:
        raise GraphicRenderReceiptStoreError(
            "graphic receipt locator is invalid"
        )
    receipt_store_path(attempt_root)
    with locked_existing_private_dir(attempt_root, LOCK_NAME) as root_fd:
        opened = open_store(root_fd, False)
        if opened is None:
            raise GraphicRenderReceiptStoreError(
                "graphic receipt set is absent"
            )
        work_fd, store_fd = opened
        try:
            if store_entries(store_fd) != (FINAL_NAME,):
                raise GraphicRenderReceiptStoreError(
                    "graphic receipt set is incomplete"
                )
            stored = read_final_receipt_set(store_fd, expectation, True)
        finally:
            os.close(store_fd)
            os.close(work_fd)
    if stored.locator != locator:
        raise GraphicRenderReceiptStoreError(
            "graphic receipt locator is stale"
        )
    return stored


def load_graphic_render_receipt_set(
    attempt_root: str,
    expectation: GraphicRenderReceiptSetExpectationV1,
    locator: GraphicRenderReceiptSetLocatorV1,
) -> StoredGraphicRenderReceiptSetV1:
    """Reopen exact private bytes without granting render or publication authority."""
    return _normalized(
        "load exact bytes", lambda: _load(attempt_root, expectation, locator)
    )


def _try_load(
    attempt_root: str, expectation: GraphicRenderReceiptSetExpectationV1
) -> StoredGraphicRenderReceiptSetV1 | None:
    validate_expectation(expectation)
    store_path = receipt_store_path(attempt_root)
    lock_path = os.path.join(attempt_root, LOCK_NAME)
    if not os.path.lexists(lock_path):
        if os.path.lexists(store_path):
            raise GraphicRenderReceiptStoreError(
                "graphic receipt lock is absent"
            )
        return None
    with locked_existing_private_dir(attempt_root, LOCK_NAME) as root_fd:
        opened = open_store(root_fd, False)
        if opened is None:
            return None
        work_fd, store_fd = opened
        try:
            names = store_entries(store_fd)
            if PENDING_NAME in names:
                raise GraphicRenderReceiptStoreError(
                    "graphic receipt persistence needs reconciliation"
                )
            if FINAL_NAME not in names:
                return None
            return read_final_receipt_set(store_fd, expectation, True)
        finally:
            os.close(store_fd)
            os.close(work_fd)


def try_load_graphic_render_receipt_set(
    attempt_root: str, expectation: GraphicRenderReceiptSetExpectationV1
) -> StoredGraphicRenderReceiptSetV1 | None:
    """Return a committed set and reject pending state as reconciliation."""
    return _normalized(
        "probe exact bytes", lambda: _try_load(attempt_root, expectation)
    )
