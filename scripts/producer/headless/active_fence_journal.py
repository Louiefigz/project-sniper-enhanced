"""Bounded append-only storage for active-fence transition frames."""

from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass

from . import active_fence_frames as frames
from . import active_fence_journal_scan as scanner
from .active_fence_lock import (
    ActiveFenceLockV1,
    validate_active_fence_lock_v1,
)
from .active_fence_schema import ActiveFenceSchemaError
from . import active_fence_types as types
from .durable_files import (
    DurableFileError,
    assert_private_lock_identity,
    open_private_file,
    write_all,
)
from .wire_identity import same_wire_value

ACTIVE_FENCE_JOURNAL_NAME = "active-fence-transitions-v1.jsonl"


class ActiveFenceJournalError(RuntimeError):
    """The authoritative transition journal is missing or corrupt."""


class ActiveFenceJournalMissingError(ActiveFenceJournalError):
    """The transition journal does not exist."""


@dataclass(frozen=True)
class ActiveFenceJournalSessionV1:
    """Open journal descriptor retained under the publisher mutex."""

    lock: ActiveFenceLockV1
    journal_fd: int
    journal_identity: tuple[int, int]


def _identity(fd: int) -> tuple[int, int]:
    info = os.fstat(fd)
    return info.st_dev, info.st_ino


def _assert_session(value: ActiveFenceJournalSessionV1) -> None:
    if type(value) is not ActiveFenceJournalSessionV1:
        raise ActiveFenceJournalError(
            "active-fence journal session is invalid"
        )
    validate_active_fence_lock_v1(value.lock)
    try:
        assert_private_lock_identity(
            value.lock.root_fd,
            ACTIVE_FENCE_JOURNAL_NAME,
            value.journal_fd,
        )
    except DurableFileError as exc:
        raise ActiveFenceJournalError(
            "active-fence journal inode was replaced"
        ) from exc
    if _identity(value.journal_fd) != value.journal_identity:
        raise ActiveFenceJournalError("active-fence journal identity changed")


def open_active_fence_journal_v1(
    lock: ActiveFenceLockV1, create: bool
) -> ActiveFenceJournalSessionV1:
    """Open/create the single journal while retaining its named inode."""
    validate_active_fence_lock_v1(lock)
    flags = os.O_RDWR | (os.O_CREAT if create else 0)
    try:
        fd = open_private_file(lock.root_fd, ACTIVE_FENCE_JOURNAL_NAME, flags)
    except DurableFileError as exc:
        if isinstance(exc.__cause__, FileNotFoundError):
            raise ActiveFenceJournalMissingError(
                "active-fence journal is absent"
            ) from exc
        raise ActiveFenceJournalError(
            "active-fence journal is unsafe"
        ) from exc
    try:
        if create:
            os.fsync(lock.root_fd)
        session = ActiveFenceJournalSessionV1(lock, fd, _identity(fd))
        _assert_session(session)
    except BaseException:
        os.close(fd)
        raise
    return session


def close_active_fence_journal_v1(
    session: ActiveFenceJournalSessionV1,
) -> None:
    """Close a journal session after a final named-inode check."""
    try:
        _assert_session(session)
    finally:
        os.close(session.journal_fd)


def scan_active_fence_journal_v1(
    session: ActiveFenceJournalSessionV1,
) -> types.ActiveFenceJournalScanV1:
    """Validate every committed frame and report only a torn final fragment."""
    try:
        _assert_session(session)
        return scanner.scan_active_fence_descriptor_v1(session.journal_fd)
    except ActiveFenceJournalError:
        raise
    except (
        DurableFileError,
        OSError,
        scanner.ActiveFenceJournalScanError,
    ) as exc:
        raise ActiveFenceJournalError(
            "active-fence journal cannot be scanned"
        ) from exc


def _bind_expected_scan(
    session: ActiveFenceJournalSessionV1,
    expected: types.ActiveFenceJournalScanV1,
) -> types.ActiveFenceJournalScanV1:
    """Bind caller state to the exact retained journal before mutation."""
    if type(expected) is not types.ActiveFenceJournalScanV1:
        raise ActiveFenceJournalError("active-fence expected scan is invalid")
    _assert_session(session)
    identity = _identity(session.journal_fd)
    observed = scan_active_fence_journal_v1(session)
    _assert_session(session)
    if (
        identity != session.journal_identity
        or _identity(session.journal_fd) != identity
    ):
        raise ActiveFenceJournalError(
            "active-fence journal session identity changed"
        )
    if type(observed) is not types.ActiveFenceJournalScanV1:
        raise ActiveFenceJournalError("active-fence observed scan is invalid")
    if not same_wire_value(observed, expected):
        raise ActiveFenceJournalError(
            "active-fence expected scan does not match journal"
        )
    return observed


def resync_active_fence_journal_v1(
    session: ActiveFenceJournalSessionV1,
) -> types.ActiveFenceJournalScanV1:
    """Flush and exactly re-scan visible complete frames before trusting them."""
    before = scan_active_fence_journal_v1(session)
    if before.torn_bytes:
        raise ActiveFenceJournalError(
            "torn active-fence tail must be repaired before resync"
        )
    try:
        _assert_session(session)
        getattr(os, "fdatasync", os.fsync)(session.journal_fd)
        os.fsync(session.lock.root_fd)
        _assert_session(session)
        after = scan_active_fence_journal_v1(session)
    except ActiveFenceJournalError:
        raise
    except OSError as exc:
        raise ActiveFenceJournalError(
            "active-fence journal recovery barrier failed"
        ) from exc
    if after != before:
        raise ActiveFenceJournalError(
            "active-fence journal changed across recovery barrier"
        )
    return after


def repair_torn_active_fence_tail_v1(
    session: ActiveFenceJournalSessionV1,
    scan: types.ActiveFenceJournalScanV1,
) -> types.ActiveFenceJournalScanV1:
    """Discard only the non-newline-committed final fragment."""
    bound = _bind_expected_scan(session, scan)
    if bound.torn_bytes == 0:
        return bound
    try:
        _assert_session(session)
        if os.fstat(session.journal_fd).st_size != (
            bound.valid_bytes + bound.torn_bytes
        ):
            raise ActiveFenceJournalError(
                "active-fence torn tail changed before repair"
            )
        os.ftruncate(session.journal_fd, bound.valid_bytes)
        getattr(os, "fdatasync", os.fsync)(session.journal_fd)
        os.fsync(session.lock.root_fd)
        _assert_session(session)
        observed = scan_active_fence_journal_v1(session)
    except ActiveFenceJournalError:
        raise
    except OSError as exc:
        raise ActiveFenceJournalError(
            "active-fence torn tail cannot be repaired"
        ) from exc
    expected = dataclasses.replace(bound, torn_bytes=0)
    if observed != expected:
        raise ActiveFenceJournalError(
            "active-fence torn-tail repair recheck failed"
        )
    return observed


def _preflight_append_capacity(
    scan: types.ActiveFenceJournalScanV1, frame_bytes: bytes
) -> None:
    next_transitions = len(scan.transitions) + 1
    next_bytes = scan.valid_bytes + len(frame_bytes) + 1
    if next_transitions > scanner.MAX_ACTIVE_FENCE_TRANSITIONS:
        raise ActiveFenceJournalError(
            "active-fence transition capacity is exhausted"
        )
    if next_bytes > scanner.MAX_ACTIVE_FENCE_JOURNAL_BYTES:
        raise ActiveFenceJournalError(
            "active-fence journal byte capacity is exhausted"
        )


def append_active_fence_transition_v1(
    session: ActiveFenceJournalSessionV1,
    scan: types.ActiveFenceJournalScanV1,
    transition: types.ActiveFenceTransitionV1,
) -> types.ActiveFenceJournalScanV1:
    """Flush one frame and reobserve the entire resulting chain."""
    bound = _bind_expected_scan(session, scan)
    if bound.torn_bytes:
        raise ActiveFenceJournalError(
            "torn tail must be repaired before append"
        )
    expected_prior = bound.transitions[-1] if bound.transitions else None
    try:
        parsed = frames.parse_active_fence_transition_v1(
            transition.frame_json, expected_prior
        )
        _preflight_append_capacity(bound, parsed.frame_json)
        _assert_session(session)
        if os.fstat(session.journal_fd).st_size != bound.valid_bytes:
            raise ActiveFenceJournalError(
                "active-fence journal changed before append"
            )
        os.lseek(session.journal_fd, 0, os.SEEK_END)
        write_all(session.journal_fd, parsed.frame_json + b"\n")
        getattr(os, "fdatasync", os.fsync)(session.journal_fd)
        os.fsync(session.lock.root_fd)
        _assert_session(session)
        observed = resync_active_fence_journal_v1(session)
    except (ActiveFenceSchemaError, DurableFileError, OSError) as exc:
        raise ActiveFenceJournalError(
            "active-fence transition cannot be appended"
        ) from exc
    if observed.torn_bytes or observed.transitions != (
        bound.transitions + (parsed,)
    ):
        raise ActiveFenceJournalError("active-fence append recheck failed")
    return observed
