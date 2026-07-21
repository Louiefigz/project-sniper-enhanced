"""Crash-safe, attempt-owned evidence trace.

The trace is an integrity and durability journal, not an authorization boundary.
Callers must keep the attempt directory private and pass digests, never raw
provider events or credentials, in event details.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import os
import re
import stat
import time
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from .trace_frames import (
    TraceCorruption,
    TraceError,
    TornTraceTail,
    encode_frame,
    scan,
)

TRACE_NAME = "trace.jsonl"
LOCK_NAME = ".trace.lock"
_HEX_DIGEST = re.compile(r"[0-9a-f]{64}")
_EVENT_NAME = re.compile(r"[A-Z][A-Z0-9_.:-]{0,127}")


class UnsafeTracePath(TraceError):
    """A trace path is not a private, single-link regular file."""


@dataclass(frozen=True)
class TraceContext:
    """Identity fields repeated in every trace event.

    ``boot_id`` is supplied by the trusted controller from the current operating
    system boot, never a per-process UUID. It may change only through a typed
    recovery/terminal event; immutable attempt identity excludes it.
    """

    unit_id: str
    attempt_id: str
    release_id: str
    build_id: str
    boot_id: str
    policy_id: str
    expected_parent: str | None
    request_digest: str
    authority_id: str

    def __post_init__(self) -> None:
        for label, value in (
            ("unit_id", self.unit_id), ("attempt_id", self.attempt_id),
            ("release_id", self.release_id), ("build_id", self.build_id),
            ("boot_id", self.boot_id), ("policy_id", self.policy_id),
            ("authority_id", self.authority_id),
        ):
            _validate_identity(label, value)
        if self.expected_parent is not None:
            _validate_identity("expected_parent", self.expected_parent, 1024)
        if not _HEX_DIGEST.fullmatch(self.request_digest):
            raise ValueError("request_digest must be normalized lowercase SHA-256")


@dataclass(frozen=True)
class TraceState:
    """Validated trace tail visible to the controller."""

    record_count: int
    last_sequence: int
    last_digest: str
    last_event: str | None
    terminal_disposition: str | None
    terminal_result_digest: str | None
    phase: str | None
    boot_id: str | None


@dataclass(frozen=True)
class TraceAppendResult:
    """Identity of one durably appended event."""

    sequence: int
    event_digest: str
    recovered_tail_bytes: int


def _validate_identity(label: str, value: str, limit: int = 256) -> None:
    if not isinstance(value, str) or not value or len(value.encode()) > limit:
        raise ValueError(f"{label} must be a nonempty string of at most {limit} bytes")
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"{label} cannot contain control characters")


def _open_create_or_existing(dir_fd: int, name: str, safe_flags: int,
                             flags: int) -> tuple[int, bool]:
    if flags & os.O_CREAT and not flags & os.O_EXCL:
        try:
            return os.open(name, safe_flags | os.O_EXCL, 0o600,
                           dir_fd=dir_fd), True
        except FileExistsError:
            existing = safe_flags & ~(os.O_EXCL | os.O_CREAT)
            return os.open(name, existing, 0o600, dir_fd=dir_fd), False
    return os.open(name, safe_flags, 0o600, dir_fd=dir_fd), bool(flags & os.O_CREAT)


def _open_regular(dir_fd: int, name: str, flags: int) -> int:
    safe_flags = flags | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW
    missing: OSError | None = None
    created = False
    for _ in range(3):
        try:
            fd, created = _open_create_or_existing(
                dir_fd, name, safe_flags, flags)
            break
        except FileNotFoundError as exc:
            missing = exc
        except OSError as exc:
            raise UnsafeTracePath(f"cannot safely open {name}: {exc}") from exc
    else:
        raise UnsafeTracePath(f"cannot safely open {name}: {missing}") from missing
    if created:
        os.fchmod(fd, 0o600)
    info = os.fstat(fd)
    safe = (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and info.st_uid == os.geteuid()
            and stat.S_IMODE(info.st_mode) == 0o600)
    if safe:
        return fd
    os.close(fd)
    raise UnsafeTracePath(f"{name} must be a private, single-link regular file")


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("zero-byte trace write")
        view = view[written:]


def _commit_frame(dir_fd: int, trace_fd: int, payload: dict[str, Any],
                  tail: Any) -> TraceAppendResult:
    line, digest = encode_frame(payload, tail)
    if tail.torn_bytes:
        os.ftruncate(trace_fd, tail.valid_bytes)
    _write_all(trace_fd, line)
    sync = getattr(os, "fdatasync", os.fsync)
    sync(trace_fd)
    os.fsync(dir_fd)
    return TraceAppendResult(tail.sequence + 1, digest, tail.torn_bytes)


def _validate_attempt_dir(fd: int) -> None:
    """Require an owned directory whose entries other users cannot replace."""
    info = os.fstat(fd)
    writable_by_others = stat.S_IMODE(info.st_mode) & 0o022
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or writable_by_others:
        raise UnsafeTracePath("attempt directory must be owned and not group/world writable")


@contextlib.contextmanager
def _locked_trace_files(attempt_dir: str, create_trace: bool
                        ) -> Iterator[tuple[int, int]]:
    """Open and lock one existing trace, creating files only for an append."""
    dir_flags = (os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
                 | os.O_NOFOLLOW)
    try:
        dir_fd = os.open(attempt_dir, dir_flags)
    except OSError as exc:
        raise UnsafeTracePath(f"cannot safely open attempt directory: {exc}") from exc
    lock_fd = trace_fd = None
    try:
        _validate_attempt_dir(dir_fd)
        lock_flags = os.O_RDWR | (os.O_CREAT if create_trace else 0)
        lock_fd = _open_regular(dir_fd, LOCK_NAME, lock_flags)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        trace_flags = os.O_RDWR | os.O_APPEND
        if create_trace:
            trace_flags |= os.O_CREAT
        trace_fd = _open_regular(dir_fd, TRACE_NAME, trace_flags)
        if create_trace:
            os.fsync(dir_fd)
        yield dir_fd, trace_fd
    finally:
        if trace_fd is not None:
            os.close(trace_fd)
        if lock_fd is not None:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
        os.close(dir_fd)


def validate_existing_trace(attempt_dir: str,
                            expected_identity: Mapping[str, Any]) -> TraceState:
    """Validate an existing trace against the supplied immutable identity subset."""
    with _locked_trace_files(os.fspath(attempt_dir), False) as (_, trace_fd):
        tail = scan(trace_fd, False, expected_identity)
    return TraceState(tail.sequence, tail.sequence, tail.digest,
                      tail.last_event, tail.terminal_disposition,
                      tail.terminal_result_digest, tail.clock.phase,
                      tail.clock.boot_id)


def _validate_existing_admission(tail: TailState) -> None:
    if tail.torn_bytes:
        raise TornTraceTail(tail.torn_bytes)
    return None


class AttemptTrace:
    """Append and validate one attempt's durable evidence chain."""

    def __init__(self, attempt_dir: str, context: TraceContext) -> None:
        self.attempt_dir = os.fspath(attempt_dir)
        self.context = context

    @contextlib.contextmanager
    def _locked_trace(self, create_trace: bool) -> Iterator[tuple[int, int]]:
        with _locked_trace_files(self.attempt_dir, create_trace) as opened:
            yield opened

    def _event_payload(self, event: str, details: Mapping[str, Any],
                       recovered_bytes: int) -> dict[str, Any]:
        if not isinstance(event, str) or not _EVENT_NAME.fullmatch(event):
            raise TraceError("event must be an uppercase bounded event name")
        payload = {
            "attemptId": self.context.attempt_id,
            "authorityId": self.context.authority_id,
            "buildId": self.context.build_id,
            "bootId": self.context.boot_id,
            "details": dict(details),
            "event": event,
            "expectedParent": self.context.expected_parent,
            "monotonicClock": "CLOCK_MONOTONIC",
            "monotonicNs": time.monotonic_ns(),
            "policyId": self.context.policy_id,
            "releaseId": self.context.release_id,
            "requestDigest": self.context.request_digest,
            "unitId": self.context.unit_id,
            "wallTime": dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds"),
            "writerPid": os.getpid(),
        }
        if recovered_bytes:
            payload["traceRecovery"] = {"truncatedTailBytes": recovered_bytes}
        return payload

    def _identity(self) -> dict[str, Any]:
        """Return the immutable fields that every frame must repeat exactly."""
        return {
            "attemptId": self.context.attempt_id,
            "authorityId": self.context.authority_id,
            "buildId": self.context.build_id,
            "expectedParent": self.context.expected_parent,
            "policyId": self.context.policy_id,
            "releaseId": self.context.release_id,
            "requestDigest": self.context.request_digest,
            "unitId": self.context.unit_id,
        }

    def validate(self) -> TraceState:
        """Validate the complete chain; refuse, but never alter, a torn tail."""
        with self._locked_trace(False) as (_, trace_fd):
            tail = scan(trace_fd, False, self._identity())
        return TraceState(tail.sequence, tail.sequence, tail.digest,
                          tail.last_event, tail.terminal_disposition,
                          tail.terminal_result_digest, tail.clock.phase,
                          tail.clock.boot_id)

    def ensure_admitted(self) -> TraceAppendResult | None:
        """Atomically create the first ADMITTED frame or validate its presence."""
        with self._locked_trace(True) as (dir_fd, trace_fd):
            tail = scan(trace_fd, True, self._identity())
            if tail.sequence:
                return _validate_existing_admission(tail)
            payload = self._event_payload("ADMITTED", {}, tail.torn_bytes)
            return _commit_frame(dir_fd, trace_fd, payload, tail)

    def append(self, event: str, details: Mapping[str, Any] | None = None,
               recover_torn_tail: bool = False) -> TraceAppendResult:
        """Append and sync one frame, optionally repairing only a torn tail."""
        event_details = {} if details is None else details
        if not isinstance(event_details, Mapping):
            raise TraceError("event details must be a JSON object")
        with self._locked_trace(True) as (dir_fd, trace_fd):
            tail = scan(trace_fd, recover_torn_tail, self._identity())
            payload = self._event_payload(event, event_details, tail.torn_bytes)
            return _commit_frame(dir_fd, trace_fd, payload, tail)
