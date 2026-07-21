"""Atomic attempt-owned storage for canonical overlay-seal receipts."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from headless.durable_files import (
    locked_private_dir,
    open_private_dir,
    private_child_dir,
    read_private_file,
    write_pending_replace,
)

SEAL_NAME = "overlay-seal.json"
_DIGEST = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class OverlaySealLocator:
    """Only stable values allowed to cross the worker process boundary."""

    path: str
    sha256: str


def _receipt_locator(directory: str) -> OverlaySealLocator:
    dir_fd = open_private_dir(directory)
    try:
        raw = read_private_file(dir_fd, SEAL_NAME)
    finally:
        os.close(dir_fd)
    return OverlaySealLocator(os.path.join(directory, SEAL_NAME),
                              hashlib.sha256(raw).hexdigest())


def _persist_new(seal_id: str, seals_fd: int, seals_path: str,
                 build: Callable[[str], bytes]) -> OverlaySealLocator:
    pending = f".pending-{seal_id}-{uuid.uuid4().hex}"
    os.mkdir(pending, 0o700, dir_fd=seals_fd)
    os.chmod(pending, 0o700, dir_fd=seals_fd, follow_symlinks=False)
    os.fsync(seals_fd)
    directory = os.path.join(seals_path, pending)
    try:
        pending_fd = open_private_dir(directory)
        try:
            write_pending_replace(
                pending_fd, (".overlay-seal.pending", SEAL_NAME), build(directory))
        finally:
            os.close(pending_fd)
        os.rename(pending, seal_id, src_dir_fd=seals_fd, dst_dir_fd=seals_fd)
    except BaseException:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    os.fsync(seals_fd)
    return _receipt_locator(os.path.join(seals_path, seal_id))


def _select_or_persist(seal_id: str, seals_fd: int, seals_path: str,
                       build: Callable[[str], bytes]) -> OverlaySealLocator:
    final = os.path.join(seals_path, seal_id)
    if os.path.exists(final):
        return _receipt_locator(final)
    return _persist_new(seal_id, seals_fd, seals_path, build)


def _close_store_fds(work_fd: int | None, seals_fd: int | None) -> None:
    if seals_fd is not None:
        os.close(seals_fd)
    if work_fd is not None:
        os.close(work_fd)


def _store_locked(attempt_root: str, root_fd: int, seal_id: str,
                  build: Callable[[str], bytes]) -> OverlaySealLocator:
    work_fd = seals_fd = None
    try:
        work_fd = private_child_dir(root_fd, "work")
        seals_fd = private_child_dir(work_fd, "overlay-seals")
        seals_path = os.path.join(attempt_root, "work", "overlay-seals")
        return _select_or_persist(seal_id, seals_fd, seals_path, build)
    finally:
        _close_store_fds(work_fd, seals_fd)


def store_overlay_receipt(attempt_root: str, seal_id: str,
                          build: Callable[[str], bytes]) -> OverlaySealLocator:
    """Publish one receipt directory once, or return its existing locator."""
    with locked_private_dir(attempt_root, ".overlay-seal.lock") as root_fd:
        return _store_locked(attempt_root, root_fd, seal_id, build)


def read_overlay_receipt(locator: OverlaySealLocator) -> bytes:
    """Read one exact private receipt and require its locator digest."""
    if (not os.path.isabs(locator.path) or os.path.realpath(locator.path) != locator.path
            or os.path.basename(locator.path) != SEAL_NAME
            or not _DIGEST.fullmatch(locator.sha256)):
        raise RuntimeError("overlay seal locator is invalid")
    directory = os.path.dirname(locator.path)
    dir_fd = open_private_dir(directory)
    try:
        raw = read_private_file(dir_fd, SEAL_NAME)
    finally:
        os.close(dir_fd)
    if hashlib.sha256(raw).hexdigest() != locator.sha256:
        raise RuntimeError("overlay seal receipt digest mismatch")
    return raw
