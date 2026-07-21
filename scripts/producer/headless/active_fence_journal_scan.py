"""Bounded descriptor scan for the active-fence transition journal."""

from __future__ import annotations

import os

from . import active_fence_frames as frames
from . import active_fence_types as types
from .active_fence_schema import ActiveFenceSchemaError

MAX_ACTIVE_FENCE_JOURNAL_BYTES = 16_777_216
MAX_ACTIVE_FENCE_TRANSITIONS = 100_000


class ActiveFenceJournalScanError(RuntimeError):
    """Journal bytes are oversized, unstable, or semantically invalid."""


def _metadata(fd: int) -> tuple[int, ...]:
    info = os.fstat(fd)
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


def _read_bounded(fd: int) -> bytes:
    chunks = []
    offset = 0
    remaining = MAX_ACTIVE_FENCE_JOURNAL_BYTES + 1
    while remaining:
        chunk = os.pread(fd, min(1_048_576, remaining), offset)
        if not chunk:
            break
        chunks.append(chunk)
        offset += len(chunk)
        remaining -= len(chunk)
    raw = b"".join(chunks)
    if len(raw) > MAX_ACTIVE_FENCE_JOURNAL_BYTES:
        raise ActiveFenceJournalScanError(
            "active-fence journal exceeds size limit"
        )
    return raw


def _split_committed(raw: bytes) -> tuple[tuple[bytes, ...], int]:
    last_newline = raw.rfind(b"\n")
    if last_newline < 0:
        prefix, tail = b"", raw
    else:
        prefix_end = last_newline + 1
        prefix, tail = raw[:prefix_end], raw[prefix_end:]
    if len(tail) > frames.MAX_FENCE_FRAME_BYTES:
        raise ActiveFenceJournalScanError(
            "torn active-fence frame is oversized"
        )
    records = tuple(prefix[:-1].split(b"\n")) if prefix else ()
    if len(records) > MAX_ACTIVE_FENCE_TRANSITIONS:
        raise ActiveFenceJournalScanError(
            "active-fence transition limit exceeded"
        )
    if any(not record for record in records):
        raise ActiveFenceJournalScanError(
            "active-fence journal has a blank frame"
        )
    return records, len(tail)


def _retain_identity(
    transition: types.ActiveFenceTransitionV1,
    tokens: set[str],
    reserved_attempts: set[str],
) -> None:
    token = transition.state.fence_token
    if token in tokens:
        raise ActiveFenceJournalScanError(
            "active-fence token recurs in journal"
        )
    tokens.add(token)
    if transition.event != "RESERVE":
        return
    if transition.attempt_id in reserved_attempts:
        raise ActiveFenceJournalScanError(
            "active-fence attempt is re-reserved"
        )
    reserved_attempts.add(transition.attempt_id or "")


def _parse_records(records: tuple[bytes, ...]) -> tuple:
    transitions = []
    prior = None
    tokens: set[str] = set()
    reserved_attempts: set[str] = set()
    try:
        for raw in records:
            prior = frames.parse_active_fence_transition_v1(raw, prior)
            _retain_identity(prior, tokens, reserved_attempts)
            transitions.append(prior)
    except ActiveFenceSchemaError as exc:
        raise ActiveFenceJournalScanError(str(exc)) from exc
    return tuple(transitions)


def scan_active_fence_descriptor_v1(
    journal_fd: int,
) -> types.ActiveFenceJournalScanV1:
    """Scan one retained private descriptor without trusting its path."""
    before = _metadata(journal_fd)
    raw = _read_bounded(journal_fd)
    after = _metadata(journal_fd)
    if before != after or before[5] != len(raw):
        raise ActiveFenceJournalScanError(
            "active-fence journal changed while scanning"
        )
    records, torn_bytes = _split_committed(raw)
    transitions = _parse_records(records)
    return types.ActiveFenceJournalScanV1(
        transitions, len(raw) - torn_bytes, torn_bytes
    )
