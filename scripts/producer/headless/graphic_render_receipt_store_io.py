"""Directory-FD persistence for one atomic graphic receipt set."""

from __future__ import annotations

import os

from .durable_files import (
    bounded_directory_entries,
    open_private_child_dir,
    open_private_file,
    private_child_dir,
    write_all,
)
from .graphic_render_receipt_store_types import GraphicRenderReceiptStoreError

LOCK_NAME = ".graphic-render-receipts.lock"
STORE_NAME = "graphic-render-receipts"
PENDING_NAME = ".pending"
FINAL_NAME = "retained"


def receipt_store_path(attempt_root: str) -> str:
    """Validate one canonical attempt root and derive its private store path."""
    valid = type(attempt_root) is str and os.path.isabs(attempt_root)
    valid = valid and os.path.realpath(attempt_root) == attempt_root
    if not valid:
        raise GraphicRenderReceiptStoreError(
            "graphic receipt authority is invalid"
        )
    return os.path.join(attempt_root, "work", STORE_NAME)


def store_entries(store_fd: int) -> tuple[str, ...]:
    """Return only the two protocol-owned directory names."""
    names = bounded_directory_entries(store_fd, 2)
    if any(name not in {PENDING_NAME, FINAL_NAME} for name in names):
        raise GraphicRenderReceiptStoreError(
            "graphic receipt store is poisoned"
        )
    if PENDING_NAME in names and FINAL_NAME in names:
        raise GraphicRenderReceiptStoreError(
            "graphic receipt store state is ambiguous"
        )
    return names


def open_store(root_fd: int, create: bool) -> tuple[int, int] | None:
    """Open the attempt work/store directories without following aliases."""
    work_fd = open_private_child_dir(root_fd, "work")
    try:
        if not create and not _named_child_exists(work_fd, STORE_NAME):
            os.close(work_fd)
            return None
        opener = private_child_dir if create else open_private_child_dir
        store_fd = opener(work_fd, STORE_NAME)
    except BaseException:
        os.close(work_fd)
        raise
    return work_fd, store_fd


def _named_child_exists(parent_fd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise GraphicRenderReceiptStoreError(
            "graphic receipt store cannot be observed"
        ) from exc
    return True


def _write_one(directory_fd: int, name: str, raw: bytes) -> None:
    """Write and flush one new private file; exposed as a crash-test seam."""
    fd = open_private_file(
        directory_fd, name, os.O_WRONLY | os.O_CREAT | os.O_EXCL
    )
    try:
        write_all(fd, raw)
        os.fsync(fd)
    finally:
        os.close(fd)


def _assert_named_identity(parent_fd: int, name: str, child_fd: int) -> None:
    try:
        held = os.fstat(child_fd)
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as exc:
        raise GraphicRenderReceiptStoreError(
            "graphic receipt pending identity cannot be observed"
        ) from exc
    if (held.st_dev, held.st_ino) != (named.st_dev, named.st_ino):
        raise GraphicRenderReceiptStoreError(
            "graphic receipt pending directory was replaced"
        )


def _read_pinned(fd: int, limit: int) -> bytes:
    chunks, remaining = [], limit + 1
    while remaining:
        chunk = os.read(fd, min(1024 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _unlink_pinned(directory_fd: int, name: str, expected: bytes) -> None:
    fd = open_private_file(directory_fd, name, os.O_RDONLY | os.O_NONBLOCK)
    try:
        held = os.fstat(fd)
        named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        identity = (held.st_dev, held.st_ino) == (named.st_dev, named.st_ino)
        raw = _read_pinned(fd, len(expected))
        prefix = len(raw) <= len(expected) and expected.startswith(raw)
        if not identity or held.st_size != len(raw) or not prefix:
            raise GraphicRenderReceiptStoreError(
                "graphic receipt pending file belongs to another set"
            )
        os.unlink(name, dir_fd=directory_fd)
        after = os.fstat(fd)
        stable = (
            held.st_dev,
            held.st_ino,
            held.st_mode,
            held.st_uid,
            held.st_size,
            held.st_mtime_ns,
        ) == (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_uid,
            after.st_size,
            after.st_mtime_ns,
        )
        if not stable or after.st_nlink != 0:
            raise GraphicRenderReceiptStoreError(
                "graphic receipt pending file changed during cleanup"
            )
    finally:
        os.close(fd)


def _clear_pending(store_fd: int, documents: dict[str, bytes]) -> None:
    pending_fd = open_private_child_dir(store_fd, PENDING_NAME)
    try:
        _assert_named_identity(store_fd, PENDING_NAME, pending_fd)
        names = bounded_directory_entries(pending_fd, len(documents))
        if not set(names).issubset(documents):
            raise GraphicRenderReceiptStoreError(
                "graphic receipt pending directory is poisoned"
            )
        for name in names:
            _unlink_pinned(pending_fd, name, documents[name])
        os.fsync(pending_fd)
        _assert_named_identity(store_fd, PENDING_NAME, pending_fd)
    finally:
        os.close(pending_fd)
    os.rmdir(PENDING_NAME, dir_fd=store_fd)
    os.fsync(store_fd)


def _sync_publication(store_fd: int) -> None:
    """Crash-test seam for the directory flush after final rename."""
    os.fsync(store_fd)


def persist_documents(store_fd: int, documents: dict[str, bytes]) -> None:
    """Replace a safe stale pending set, then publish the full set at once."""
    names = store_entries(store_fd)
    if FINAL_NAME in names:
        raise GraphicRenderReceiptStoreError(
            "graphic receipt set already exists"
        )
    if PENDING_NAME in names:
        _clear_pending(store_fd, documents)
    os.mkdir(PENDING_NAME, 0o700, dir_fd=store_fd)
    os.chmod(PENDING_NAME, 0o700, dir_fd=store_fd, follow_symlinks=False)
    os.fsync(store_fd)
    pending_fd = open_private_child_dir(store_fd, PENDING_NAME)
    try:
        for name, raw in documents.items():
            _write_one(pending_fd, name, raw)
        os.fsync(pending_fd)
        _assert_named_identity(store_fd, PENDING_NAME, pending_fd)
    finally:
        os.close(pending_fd)
    os.rename(
        PENDING_NAME, FINAL_NAME, src_dir_fd=store_fd, dst_dir_fd=store_fd
    )
    _sync_publication(store_fd)
