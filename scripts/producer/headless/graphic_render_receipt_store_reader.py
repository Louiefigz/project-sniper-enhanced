"""Pinned read, replay-flush, and parse logic for graphic receipt sets."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

from .durable_files import (
    exact_directory_entries,
    open_private_child_dir,
    open_private_file,
)
from .graphic_render_receipt_semantics import (
    GraphicRenderReceiptSchemaError,
    GraphicRenderReceiptV1,
    parse_graphic_render_receipt_v1,
)
from .graphic_render_receipt_set_manifest import parse_set_manifest
from .graphic_render_receipt_store_io import FINAL_NAME
from .graphic_render_receipt_store_types import (
    GraphicRenderReceiptSetExpectationV1,
    GraphicRenderReceiptSetLocatorV1,
    GraphicRenderReceiptStoreError,
    StoredGraphicRenderReceiptSetV1,
)
from .graphic_render_receipt_store_validation import receipt_matches

MANIFEST_NAME = "manifest.json"
_MAX_RECEIPT_BYTES = 1024 * 1024
_MAX_MANIFEST_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class _PinnedFile:
    name: str
    fd: int
    raw: bytes
    identity: tuple[int, ...]


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_uid,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _read_bounded(fd: int, limit: int) -> bytes:
    chunks, remaining = [], limit + 1
    while remaining:
        chunk = os.read(fd, min(1024 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    raw = b"".join(chunks)
    if len(raw) > limit:
        raise GraphicRenderReceiptStoreError(
            "retained graphic receipt is oversized"
        )
    return raw


def _assert_pinned(dir_fd: int, pinned: _PinnedFile) -> None:
    try:
        held = os.fstat(pinned.fd)
        named = os.stat(pinned.name, dir_fd=dir_fd, follow_symlinks=False)
    except OSError as exc:
        raise GraphicRenderReceiptStoreError(
            "retained graphic receipt identity cannot be observed"
        ) from exc
    if (
        _identity(held) != pinned.identity
        or _identity(named) != pinned.identity
    ):
        raise GraphicRenderReceiptStoreError(
            "retained graphic receipt inode was replaced"
        )


def _open_retained(
    dir_fd: int, name: str, limit: int, replayed: bool
) -> _PinnedFile:
    fd = open_private_file(dir_fd, name, os.O_RDONLY | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        raw = _read_bounded(fd, limit)
        if before.st_size != len(raw):
            raise GraphicRenderReceiptStoreError(
                "retained graphic receipt size changed during read"
            )
        pinned = _PinnedFile(name, fd, raw, _identity(before))
        _assert_pinned(dir_fd, pinned)
        if replayed:
            os.fsync(fd)
        _assert_pinned(dir_fd, pinned)
        return pinned
    except BaseException:
        os.close(fd)
        raise


def _read_receipts(
    final_fd: int,
    rows: tuple[dict, ...],
    expectation: GraphicRenderReceiptSetExpectationV1,
    replayed: bool,
) -> tuple[tuple[GraphicRenderReceiptV1, ...], tuple[_PinnedFile, ...]]:
    receipts, pinned_files = [], []
    try:
        for index, row in enumerate(rows):
            pinned = _open_retained(
                final_fd, row["file"], _MAX_RECEIPT_BYTES, replayed
            )
            pinned_files.append(pinned)
            observed = (
                hashlib.sha256(pinned.raw).hexdigest(),
                len(pinned.raw),
            )
            if observed != (row["sha256"], row["sizeBytes"]):
                raise GraphicRenderReceiptStoreError(
                    "graphic receipt bytes are stale"
                )
            try:
                receipt = parse_graphic_render_receipt_v1(pinned.raw)
            except GraphicRenderReceiptSchemaError as exc:
                raise GraphicRenderReceiptStoreError(
                    "retained graphic receipt is invalid"
                ) from exc
            receipt_matches(receipt, expectation, index)
            receipts.append(receipt)
    except BaseException:
        for pinned in pinned_files:
            os.close(pinned.fd)
        raise
    return tuple(receipts), tuple(pinned_files)


def _assert_final(
    store_fd: int, final_fd: int, identity: tuple[int, ...]
) -> None:
    try:
        held = os.fstat(final_fd)
        named = os.stat(FINAL_NAME, dir_fd=store_fd, follow_symlinks=False)
    except OSError as exc:
        raise GraphicRenderReceiptStoreError(
            "graphic receipt final identity cannot be observed"
        ) from exc
    if _identity(held) != identity or _identity(named) != identity:
        raise GraphicRenderReceiptStoreError(
            "graphic receipt final directory was replaced"
        )


def _sync_replay_directories(final_fd: int, store_fd: int) -> None:
    """Crash-test seam for the final and store directory replay barrier."""
    os.fsync(final_fd)
    os.fsync(store_fd)


def read_final_receipt_set(
    store_fd: int,
    expectation: GraphicRenderReceiptSetExpectationV1,
    replayed: bool,
) -> StoredGraphicRenderReceiptSetV1:
    """Parse one final set and durably re-flush exact replay bytes."""
    final_fd = open_private_child_dir(store_fd, FINAL_NAME)
    final_identity = _identity(os.fstat(final_fd))
    pinned_files: tuple[_PinnedFile, ...] = ()
    try:
        _assert_final(store_fd, final_fd, final_identity)
        manifest_file = _open_retained(
            final_fd, MANIFEST_NAME, _MAX_MANIFEST_BYTES, replayed
        )
        pinned_files = (manifest_file,)
        rows = parse_set_manifest(manifest_file.raw, expectation)
        names = {MANIFEST_NAME} | {row["file"] for row in rows}
        if not exact_directory_entries(final_fd, names):
            raise GraphicRenderReceiptStoreError(
                "graphic receipt set directory closure is invalid"
            )
        receipts, receipt_files = _read_receipts(
            final_fd, rows, expectation, replayed
        )
        pinned_files += receipt_files
        for pinned in pinned_files:
            _assert_pinned(final_fd, pinned)
        _assert_final(store_fd, final_fd, final_identity)
        if replayed:
            _sync_replay_directories(final_fd, store_fd)
        for pinned in pinned_files:
            _assert_pinned(final_fd, pinned)
        _assert_final(store_fd, final_fd, final_identity)
    finally:
        for pinned in pinned_files:
            os.close(pinned.fd)
        os.close(final_fd)
    locator = GraphicRenderReceiptSetLocatorV1(
        hashlib.sha256(manifest_file.raw).hexdigest(), len(receipts)
    )
    return StoredGraphicRenderReceiptSetV1(locator, receipts, replayed)
