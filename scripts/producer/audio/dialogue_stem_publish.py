"""Durable, no-replace publication for one dialogue-stem generation."""
from __future__ import annotations

import ctypes
import errno
import os
import stat

from audio.dialogue_stem_contracts import DialogueStemRenderError

RECEIPT_NAME = "dialogue-stem-receipt.json"
_FINAL_NAMES = {"dialogue-stem.wav", RECEIPT_NAME}


def _open_leaf(directory_fd: int, name: str) -> int:
    flags = os.O_RDONLY | os.O_NOFOLLOW
    try:
        descriptor = os.open(name, flags, dir_fd=directory_fd)
        info = os.fstat(descriptor)
    except OSError as exc:
        raise DialogueStemRenderError(
            f"dialogue generation leaf is unsafe: {name}") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        os.close(descriptor)
        raise DialogueStemRenderError(
            f"dialogue generation leaf is not immutable: {name}")
    return descriptor


def _seal_leaf(directory_fd: int, name: str) -> None:
    descriptor = _open_leaf(directory_fd, name)
    try:
        os.fsync(descriptor)
        os.fchmod(descriptor, 0o400)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _rename_noreplace(parent_fd: int, source: str, target: str) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    unsupported = {errno.EINVAL, errno.ENOSYS, errno.ENOTSUP}
    for symbol, flag in (("renameatx_np", 4), ("renameat2", 1)):
        function = getattr(libc, symbol, None)
        if function is None:
            continue
        function.argtypes = (
            ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p,
            ctypes.c_uint)
        function.restype = ctypes.c_int
        result = function(
            parent_fd, os.fsencode(source), parent_fd, os.fsencode(target),
            flag)
        if result == 0:
            return
        error = ctypes.get_errno()
        if error in {errno.EEXIST, errno.ENOTEMPTY}:
            raise DialogueStemRenderError(
                "dialogue generation destination raced or already exists")
        if error in unsupported:
            continue
        raise DialogueStemRenderError(
            f"dialogue generation rename failed: {os.strerror(error)}")
    raise DialogueStemRenderError(
        "atomic no-replace generation rename is unavailable")


def _directory_snapshot(descriptor: int) -> tuple[int, int]:
    info = os.fstat(descriptor)
    if not stat.S_ISDIR(info.st_mode):
        raise DialogueStemRenderError("dialogue staging node is not a directory")
    return info.st_dev, info.st_ino


def publish_named_generation(
    stage_dir: str,
    generation_dir: str,
    expected_names: set[str],
) -> None:
    """Seal one exact leaf closure and atomically install its directory."""
    parent = os.path.dirname(generation_dir)
    if os.path.dirname(stage_dir) != parent:
        raise DialogueStemRenderError(
            "dialogue generation must stage on the destination filesystem")
    parent_fd = os.open(
        parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    stage_fd = os.open(
        os.path.basename(stage_dir),
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        dir_fd=parent_fd)
    try:
        names = set(os.listdir(stage_fd))
        if not expected_names or names != expected_names:
            raise DialogueStemRenderError(
                "dialogue generation staging closure changed")
        for name in sorted(names):
            _seal_leaf(stage_fd, name)
        before = _directory_snapshot(stage_fd)
        os.fchmod(stage_fd, 0o500)
        os.fsync(stage_fd)
        _rename_noreplace(
            parent_fd, os.path.basename(stage_dir),
            os.path.basename(generation_dir))
        installed = os.stat(
            os.path.basename(generation_dir),
            dir_fd=parent_fd, follow_symlinks=False)
        if (installed.st_dev, installed.st_ino) != before:
            raise DialogueStemRenderError(
                "installed dialogue generation inode changed")
        os.fsync(parent_fd)
    finally:
        os.close(stage_fd)
        os.close(parent_fd)


def publish_generation(stage_dir: str, generation_dir: str) -> None:
    """Seal exactly the two dialogue-stem leaves and install atomically."""
    publish_named_generation(stage_dir, generation_dir, _FINAL_NAMES)
