"""No-overwrite writes and exact-target recovery for start intents."""

from __future__ import annotations

import hashlib
import os
import re
import stat

from .durable_files import (
    bounded_directory_entries,
    open_private_file,
    write_all,
)
from .fence_order_start_schema import parse_fence_order_start_intent_v1
from .fence_order_start_types import (
    MAX_FENCE_ORDER_START_BYTES,
    MAX_FENCE_ORDER_START_RECORDS,
    FenceOrderStartConflictV1,
    FenceOrderStartError,
)
from .record_durability import (
    assert_named_private_file_identity,
    fsync_read_stable_private_fd,
    read_stable_private_fd,
)

_RECORD_NAME = re.compile(r"[0-9a-f]{64}")
_PENDING_NAME = re.compile(r"\.pending-([0-9a-f]{64})")
_RECORD_DOMAIN = b"sniper-fence-order-start-record-v1\0"


def _record_name(attempt_id: str) -> str:
    return hashlib.sha256(
        _RECORD_DOMAIN + attempt_id.encode("ascii")
    ).hexdigest()


def _safe(info: os.stat_result, links: int) -> bool:
    return (
        stat.S_ISREG(info.st_mode)
        and info.st_nlink == links
        and info.st_uid == os.geteuid()
        and stat.S_IMODE(info.st_mode) == 0o600
    )


def _open_pending(store_fd: int, pending: str) -> int:
    flags = os.O_RDWR | os.O_NONBLOCK | os.O_NOFOLLOW
    flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(pending, flags, dir_fd=store_fd)
    except OSError as exc:
        raise FenceOrderStartError("start pending file is unsafe") from exc
    links = os.fstat(fd).st_nlink
    if links in {1, 2} and _safe(os.fstat(fd), links):
        return fd
    os.close(fd)
    raise FenceOrderStartError("start pending file is unsafe")


def _complete_prefix(fd: int, expected: bytes) -> None:
    raw = read_stable_private_fd(fd, MAX_FENCE_ORDER_START_BYTES)
    if raw != expected[: len(raw)]:
        raise FenceOrderStartConflictV1("start pending bytes conflict")
    if raw != expected:
        os.lseek(fd, 0, os.SEEK_END)
        offset = len(raw)
        write_all(fd, expected[offset:])
    os.fsync(fd)
    retained = read_stable_private_fd(fd, MAX_FENCE_ORDER_START_BYTES)
    if retained != expected:
        raise FenceOrderStartError("start pending reconstruction failed")
    parse_fence_order_start_intent_v1(retained)


def _require_pair(store_fd: int, pending: str, final: str, fd: int) -> None:
    held = os.fstat(fd)
    pending_info = os.stat(pending, dir_fd=store_fd, follow_symlinks=False)
    final_info = os.stat(final, dir_fd=store_fd, follow_symlinks=False)
    identities = {
        (held.st_dev, held.st_ino),
        (pending_info.st_dev, pending_info.st_ino),
        (final_info.st_dev, final_info.st_ino),
    }
    safe = all(_safe(info, 2) for info in (held, pending_info, final_info))
    if len(identities) != 1 or not safe:
        raise FenceOrderStartConflictV1(
            "start final conflicts with pending publication"
        )


def _promote(store_fd: int, name: str, expected: bytes) -> None:
    pending = f".pending-{name}"
    fd = _open_pending(store_fd, pending)
    try:
        links = os.fstat(fd).st_nlink
        names = bounded_directory_entries(
            store_fd, MAX_FENCE_ORDER_START_RECORDS + 1
        )
        final_exists = name in names
        if links == 1 and not final_exists:
            _complete_prefix(fd, expected)
            try:
                os.link(
                    pending,
                    name,
                    src_dir_fd=store_fd,
                    dst_dir_fd=store_fd,
                    follow_symlinks=False,
                )
            except FileExistsError as exc:
                raise FenceOrderStartConflictV1(
                    "start final appeared during publication"
                ) from exc
        elif links != 2 or not final_exists:
            raise FenceOrderStartConflictV1(
                "start pending link state conflicts"
            )
        _require_pair(store_fd, pending, name, fd)
        raw, _ = fsync_read_stable_private_fd(fd, MAX_FENCE_ORDER_START_BYTES)
        if raw != expected:
            raise FenceOrderStartConflictV1("start pending identity conflicts")
        os.unlink(pending, dir_fd=store_fd)
        os.fsync(store_fd)
        assert_named_private_file_identity(store_fd, name, fd)
    finally:
        os.close(fd)


def _discard_complete_other(
    store_fd: int, pending: str, target: str, names: tuple[str, ...]
) -> None:
    fd = _open_pending(store_fd, pending)
    try:
        links = os.fstat(fd).st_nlink
        final_exists = target in names
        if (links, final_exists) not in {(1, False), (2, True)}:
            raise FenceOrderStartConflictV1(
                "unrelated start pending state conflicts"
            )
        if final_exists:
            _require_pair(store_fd, pending, target, fd)
        raw, _ = fsync_read_stable_private_fd(fd, MAX_FENCE_ORDER_START_BYTES)
        try:
            intent = parse_fence_order_start_intent_v1(raw)
        except RuntimeError as exc:
            raise FenceOrderStartError(
                "unrelated start pending is incomplete"
            ) from exc
        if _record_name(intent.attempt_id) != target:
            raise FenceOrderStartConflictV1(
                "unrelated start pending targets another record"
            )
        if not final_exists:
            assert_named_private_file_identity(store_fd, pending, fd)
        os.unlink(pending, dir_fd=store_fd)
        os.fsync(store_fd)
        if final_exists:
            assert_named_private_file_identity(store_fd, target, fd)
    finally:
        os.close(fd)


def recover_fence_order_start_pending_v1(
    store_fd: int, name: str, expected: bytes
) -> None:
    """Recover this target; unrelated incomplete scratch stays closed."""
    pending = f".pending-{name}"
    names = bounded_directory_entries(
        store_fd, MAX_FENCE_ORDER_START_RECORDS * 2
    )
    unknown = tuple(
        item
        for item in names
        if not _RECORD_NAME.fullmatch(item)
        and not _PENDING_NAME.fullmatch(item)
    )
    if unknown:
        raise FenceOrderStartError("start store has unknown entries")
    for item in names:
        match = _PENDING_NAME.fullmatch(item)
        if match is not None and item != pending:
            _discard_complete_other(store_fd, item, match.group(1), names)
    retained = bounded_directory_entries(
        store_fd, MAX_FENCE_ORDER_START_RECORDS + 1
    )
    if pending in retained:
        _promote(store_fd, name, expected)


def write_fence_order_start_record_v1(
    store_fd: int, name: str, raw: bytes
) -> None:
    """Publish one immutable start intent with a no-overwrite commit."""
    if len(raw) > MAX_FENCE_ORDER_START_BYTES:
        raise FenceOrderStartError("start intent bytes exceed limit")
    pending = f".pending-{name}"
    fd = open_private_file(
        store_fd, pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL
    )
    try:
        write_all(fd, raw)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.fsync(store_fd)
    _promote(store_fd, name, raw)
