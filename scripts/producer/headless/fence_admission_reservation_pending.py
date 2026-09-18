"""No-overwrite publication and bounded pending recovery for reservations."""

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
from .fence_admission_reservation_schema import (
    parse_fence_admission_reservation_v1,
)
from .fence_admission_reservation_types import (
    MAX_FENCE_ADMISSION_RESERVATION_BYTES,
    MAX_FENCE_ADMISSION_RESERVATION_RECORDS,
    FenceAdmissionReservationConflictV1,
    FenceAdmissionReservationError,
)
from .record_durability import (
    assert_named_private_file_identity,
    fsync_read_stable_private_fd,
    read_stable_private_fd,
)

_RECORD_NAME = re.compile(r"[0-9a-f]{64}")
_PENDING_NAME = re.compile(r"\.pending-([0-9a-f]{64})")
_RECORD_DOMAIN = b"sniper-fence-admission-reservation-record-v1\0"


def _pending_name(name: str) -> str:
    return f".pending-{name}"


def _record_name(attempt_id: str) -> str:
    return hashlib.sha256(
        _RECORD_DOMAIN + attempt_id.encode("ascii")
    ).hexdigest()


def _safe_transition(info: os.stat_result, links: int) -> bool:
    return (
        stat.S_ISREG(info.st_mode)
        and info.st_nlink == links
        and info.st_uid == os.geteuid()
        and stat.S_IMODE(info.st_mode) == 0o600
    )


def _open_transition(store_fd: int, pending: str) -> int:
    flags = os.O_RDWR | os.O_NONBLOCK | os.O_NOFOLLOW
    flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(pending, flags, dir_fd=store_fd)
    except OSError as exc:
        raise FenceAdmissionReservationError(
            "fence reservation pending file is unsafe"
        ) from exc
    links = os.fstat(fd).st_nlink
    if links in {1, 2} and _safe_transition(os.fstat(fd), links):
        return fd
    os.close(fd)
    raise FenceAdmissionReservationError(
        "fence reservation pending file is unsafe"
    )


def _complete_pending(fd: int, expected: bytes) -> None:
    limit = MAX_FENCE_ADMISSION_RESERVATION_BYTES
    raw = read_stable_private_fd(fd, limit)
    if raw != expected[: len(raw)]:
        raise FenceAdmissionReservationConflictV1(
            "fence reservation pending bytes conflict"
        )
    if raw != expected:
        os.lseek(fd, 0, os.SEEK_END)
        offset = len(raw)
        write_all(fd, expected[offset:])
    os.fsync(fd)
    retained = read_stable_private_fd(fd, limit)
    if retained != expected:
        raise FenceAdmissionReservationError(
            "fence reservation pending reconstruction failed"
        )
    parse_fence_admission_reservation_v1(retained)


def _require_link_pair(
    store_fd: int, pending: str, name: str, fd: int
) -> None:
    held = os.fstat(fd)
    pending_info = os.stat(pending, dir_fd=store_fd, follow_symlinks=False)
    final_info = os.stat(name, dir_fd=store_fd, follow_symlinks=False)
    identities = {
        (held.st_dev, held.st_ino),
        (pending_info.st_dev, pending_info.st_ino),
        (final_info.st_dev, final_info.st_ino),
    }
    safe = all(
        _safe_transition(info, 2) for info in (held, pending_info, final_info)
    )
    if len(identities) != 1 or not safe:
        raise FenceAdmissionReservationConflictV1(
            "fence reservation final conflicts with pending publication"
        )


def _promote_pending(store_fd: int, name: str, expected: bytes) -> None:
    pending = _pending_name(name)
    fd = _open_transition(store_fd, pending)
    try:
        links = os.fstat(fd).st_nlink
        names = bounded_directory_entries(
            store_fd, MAX_FENCE_ADMISSION_RESERVATION_RECORDS + 1
        )
        final_exists = name in names
        if links == 1 and not final_exists:
            _complete_pending(fd, expected)
            try:
                os.link(
                    pending,
                    name,
                    src_dir_fd=store_fd,
                    dst_dir_fd=store_fd,
                    follow_symlinks=False,
                )
            except FileExistsError as exc:
                raise FenceAdmissionReservationConflictV1(
                    "fence reservation final appeared during publication"
                ) from exc
        elif links != 2 or not final_exists:
            raise FenceAdmissionReservationConflictV1(
                "fence reservation pending link state conflicts"
            )
        _require_link_pair(store_fd, pending, name, fd)
        raw, _ = fsync_read_stable_private_fd(
            fd, MAX_FENCE_ADMISSION_RESERVATION_BYTES
        )
        if raw != expected:
            raise FenceAdmissionReservationConflictV1(
                "fence reservation pending identity conflicts"
            )
        os.unlink(pending, dir_fd=store_fd)
        os.fsync(store_fd)
        assert_named_private_file_identity(store_fd, name, fd)
    finally:
        os.close(fd)


def _discard_other_complete_pending(
    store_fd: int, pending: str, target: str, names: tuple[str, ...]
) -> None:
    fd = _open_transition(store_fd, pending)
    try:
        links = os.fstat(fd).st_nlink
        final_exists = target in names
        valid_state = (links, final_exists) in {(1, False), (2, True)}
        if not valid_state:
            raise FenceAdmissionReservationConflictV1(
                "unrelated fence reservation pending state conflicts"
            )
        if final_exists:
            _require_link_pair(store_fd, pending, target, fd)
        raw, _ = fsync_read_stable_private_fd(
            fd, MAX_FENCE_ADMISSION_RESERVATION_BYTES
        )
        try:
            reservation = parse_fence_admission_reservation_v1(raw)
        except RuntimeError as exc:
            raise FenceAdmissionReservationError(
                "unrelated fence reservation pending is incomplete"
            ) from exc
        if _record_name(reservation.attempt_id) != target:
            raise FenceAdmissionReservationConflictV1(
                "unrelated fence reservation pending targets another record"
            )
        if not final_exists:
            assert_named_private_file_identity(store_fd, pending, fd)
        os.unlink(pending, dir_fd=store_fd)
        os.fsync(store_fd)
        if final_exists:
            assert_named_private_file_identity(store_fd, target, fd)
    finally:
        os.close(fd)


def recover_fence_admission_reservation_pending_v1(
    store_fd: int, name: str, expected: bytes
) -> None:
    """Recover only this deterministic safe pending target under its writer."""
    pending = _pending_name(name)
    names = bounded_directory_entries(
        store_fd, MAX_FENCE_ADMISSION_RESERVATION_RECORDS * 2
    )
    unknown = tuple(
        item
        for item in names
        if not _RECORD_NAME.fullmatch(item)
        and not _PENDING_NAME.fullmatch(item)
    )
    if unknown:
        raise FenceAdmissionReservationError(
            "fence reservation store has unknown pending entries"
        )
    for item in names:
        match = _PENDING_NAME.fullmatch(item)
        if match is not None and item != pending:
            _discard_other_complete_pending(
                store_fd, item, match.group(1), names
            )
    retained = bounded_directory_entries(
        store_fd, MAX_FENCE_ADMISSION_RESERVATION_RECORDS + 1
    )
    if pending in retained:
        _promote_pending(store_fd, name, expected)


def write_fence_admission_reservation_record_v1(
    store_fd: int, name: str, raw: bytes
) -> None:
    """Publish one immutable file using a no-overwrite hard-link commit."""
    if len(raw) > MAX_FENCE_ADMISSION_RESERVATION_BYTES:
        raise FenceAdmissionReservationError(
            "fence reservation bytes exceed limit"
        )
    pending = _pending_name(name)
    fd = open_private_file(
        store_fd, pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL
    )
    try:
        write_all(fd, raw)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.fsync(store_fd)
    _promote_pending(store_fd, name, raw)
