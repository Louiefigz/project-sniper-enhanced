"""Canonical frame encoding and validation for the headless attempt trace."""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import math
import os
import re
import zlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .trace_state import (
    ClockState,
    TraceStateViolation,
    advance_clock,
    validate_event_contract,
)

MAX_FRAME_BYTES = 65_536
FRAME_VERSION = 3
ZERO_DIGEST = "0" * 64
_SECRET_KEYS = {"authorization", "cookie", "password", "passwd", "setcookie"}
_SECRET_SUFFIXES = (
    "apikey", "apisecret", "accesstoken", "refreshtoken", "clientsecret",
    "privatekey", "secretkey",
)
_SECRET_VALUES = tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
    r"\b(?:bearer|basic)\s+[a-z0-9._~+/=-]{8,}",
    r"\bsk-(?:ant-|proj-|live-|test-)?[a-z0-9_-]{8,}",
    r"\b(?:gh[pousr]_|github_pat_|xox[baprs]-)[a-z0-9_-]{8,}",
    r"\bAKIA[0-9A-Z]{16}\b",
    r"\bAIza[0-9A-Za-z_-]{20,}\b",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)\s*[:=]\s*\S{6,}",
))
_JWT_CHARS = re.compile(r"[A-Za-z0-9_-]+")
_FRAME_KEYS = {
    "eventDigest", "frameVersion", "payload", "payloadByteLength",
    "payloadCrc32", "priorDigest", "sequence",
}
_PAYLOAD_KEYS = {
    "attemptId", "authorityId", "bootId", "buildId", "details", "event",
    "expectedParent", "monotonicClock", "monotonicNs", "policyId",
    "releaseId", "requestDigest", "unitId", "wallTime", "writerPid",
}
_IMMUTABLE_IDENTITY_KEYS = {
    "attemptId", "authorityId", "buildId", "expectedParent", "policyId",
    "releaseId", "requestDigest", "unitId",
}


class TraceError(RuntimeError):
    """Base error for durable trace operations."""


class TraceCorruption(TraceError):
    """A complete record failed the canonical integrity chain."""


class TornTraceTail(TraceError):
    """The final physical record lacks its newline commit marker."""

    def __init__(self, byte_count: int) -> None:
        super().__init__(f"trace has a torn final record ({byte_count} bytes)")
        self.byte_count = byte_count


@dataclass(frozen=True)
class TailState:
    """Validated tail and optional recoverable final fragment."""

    sequence: int = 0
    digest: str = ZERO_DIGEST
    valid_bytes: int = 0
    torn_bytes: int = 0
    clock: ClockState = ClockState()
    last_event: str | None = None
    terminal_disposition: str | None = None
    terminal_result_digest: str | None = None


def _assert_safe_json(value: Any) -> None:
    """Reject non-JSON values and obvious credential-bearing field names."""
    stack = [value]
    containers: set[int] = set()
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            _push_object(item, stack, containers)
            continue
        if isinstance(item, list):
            _push_array(item, stack, containers)
            continue
        if isinstance(item, float) and not math.isfinite(item):
            raise TraceError("trace numbers must be finite")
        if isinstance(item, str):
            _validate_string(item)
        if item is None or isinstance(item, (str, int, float, bool)):
            continue
        raise TraceError(f"trace value is not canonical JSON: {type(item).__name__}")


def _validate_string(value: str) -> None:
    if len(value.encode("utf-8")) > MAX_FRAME_BYTES:
        raise TraceError("trace string exceeds the frame size bound")
    if any(rule.search(value) for rule in _SECRET_VALUES):
        raise TraceError("trace string resembles a credential and is forbidden")
    for token in value.split():
        parts = token.strip("'\"()[]{}<>,;:").split(".")
        if len(parts) == 3 and all(
                len(part) >= 12 and _JWT_CHARS.fullmatch(part) for part in parts):
            raise TraceError("trace string resembles a credential and is forbidden")


def _push_object(item: dict, stack: list[Any], containers: set[int]) -> None:
    if id(item) in containers:
        raise TraceError("trace JSON cannot contain repeated or cyclic containers")
    containers.add(id(item))
    for key, nested in item.items():
        if not isinstance(key, str):
            raise TraceError("trace object keys must be strings")
        normalized = re.sub(r"[^a-z0-9]", "", key.lower())
        if normalized in _SECRET_KEYS or normalized.endswith(_SECRET_SUFFIXES):
            raise TraceError(f"secret-bearing trace field is forbidden: {key}")
        stack.append(nested)


def _push_array(item: list, stack: list[Any], containers: set[int]) -> None:
    if id(item) in containers:
        raise TraceError("trace JSON cannot contain repeated or cyclic containers")
    containers.add(id(item))
    stack.extend(item)


def canonical(value: Any) -> bytes:
    """Encode one value as bounded-schema canonical JSON bytes."""
    _assert_safe_json(value)
    try:
        text = json.dumps(value, allow_nan=False, ensure_ascii=False,
                          separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError, RecursionError) as exc:
        raise TraceError(f"cannot canonicalize trace JSON: {exc}") from exc
    return text.encode("utf-8")


def _validate_payload(payload: dict[str, Any]) -> None:
    keys = set(payload)
    if keys not in (_PAYLOAD_KEYS, _PAYLOAD_KEYS | {"traceRecovery"}):
        raise TraceCorruption("trace payload has an invalid event schema")
    try:
        wall_time = dt.datetime.fromisoformat(payload["wallTime"])
    except (TypeError, ValueError) as exc:
        raise TraceCorruption("trace wall timestamp is invalid") from exc
    valid = (
        isinstance(payload["details"], dict)
        and isinstance(payload["bootId"], str) and bool(payload["bootId"])
        and len(payload["bootId"].encode("utf-8")) <= 256
        and isinstance(payload["event"], str) and bool(payload["event"])
        and payload["monotonicClock"] == "CLOCK_MONOTONIC"
        and type(payload["monotonicNs"]) is int and payload["monotonicNs"] >= 0
        and type(payload["writerPid"]) is int and payload["writerPid"] > 0
        and wall_time.utcoffset() == dt.timedelta(0)
    )
    if not valid:
        raise TraceCorruption("trace event metadata is invalid")
    try:
        validate_event_contract(payload)
    except TraceStateViolation as exc:
        raise TraceCorruption(str(exc)) from exc
    recovery = payload.get("traceRecovery")
    if recovery is None:
        return
    valid_recovery = (
        isinstance(recovery, dict) and set(recovery) == {"truncatedTailBytes"}
        and type(recovery["truncatedTailBytes"]) is int
        and recovery["truncatedTailBytes"] > 0
    )
    if not valid_recovery:
        raise TraceCorruption("trace recovery metadata is invalid")


def _advance_clock(state: ClockState, payload: dict[str, Any]) -> ClockState:
    try:
        return advance_clock(state, payload)
    except TraceStateViolation as exc:
        raise TraceCorruption(str(exc)) from exc


def _validate_frame(raw: bytes, sequence: int,
                    prior: str) -> tuple[str, dict[str, Any]]:
    try:
        frame = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TraceCorruption(f"complete trace record is invalid JSON: {exc}") from exc
    if not isinstance(frame, dict) or set(frame) != _FRAME_KEYS:
        raise TraceCorruption("trace record has an invalid frame schema")
    try:
        if canonical(frame) != raw:
            raise TraceCorruption("trace record is not exact canonical JSON")
        payload = frame["payload"]
        if not isinstance(payload, dict):
            raise TraceCorruption("trace payload must be a JSON object")
        _validate_payload(payload)
        payload_bytes = canonical(payload)
    except TraceError as exc:
        raise TraceCorruption(str(exc)) from exc
    valid_header = (
        type(frame["frameVersion"]) is int
        and frame["frameVersion"] == FRAME_VERSION
        and type(frame["sequence"]) is int
        and frame["sequence"] == sequence
        and frame["priorDigest"] == prior
        and type(frame["payloadByteLength"]) is int
        and frame["payloadByteLength"] == len(payload_bytes)
        and frame["payloadCrc32"] == f"{zlib.crc32(payload_bytes) & 0xffffffff:08x}"
    )
    if not valid_header:
        raise TraceCorruption("trace sequence, predecessor, length, or CRC is invalid")
    core = {key: value for key, value in frame.items() if key != "eventDigest"}
    digest = hashlib.sha256(b"sniper-trace-event-v3\0" + canonical(core)).hexdigest()
    if frame["eventDigest"] != digest:
        raise TraceCorruption("trace event digest is invalid")
    return digest, payload


def _scan_line(line: bytes, state: TailState, position: tuple[int, int, int, bool],
               identities: tuple[Mapping[str, Any], dict | None]
               ) -> tuple[TailState, tuple[dict | None, bool]]:
    start, end, size, accept_torn = position
    expected, observed = identities
    if not line.endswith(b"\n"):
        return _incomplete_tail(state, start, end, (size, accept_torn)), (observed, True)
    if len(line) > MAX_FRAME_BYTES:
        raise TraceCorruption("trace record exceeds the frame size bound")
    digest, payload = _validate_frame(line[:-1], state.sequence + 1, state.digest)
    if any(payload.get(key) != value for key, value in expected.items()):
        raise TraceCorruption("trace record identity changed within the attempt")
    current = {key: payload.get(key) for key in _IMMUTABLE_IDENTITY_KEYS}
    if observed is None:
        observed = current
    if current != observed:
        raise TraceCorruption("trace immutable identity changed between frames")
    clock = _advance_clock(state.clock, payload)
    terminal = payload["event"] == "TERMINAL_SEALED"
    disposition = payload["details"].get("disposition") if terminal else None
    result_digest = payload["details"].get("resultDigest") if terminal else None
    tail = TailState(state.sequence + 1, digest, end, 0, clock,
                     payload["event"], disposition, result_digest)
    return tail, (observed, False)


def scan(fd: int, accept_torn: bool,
         expected_identity: Mapping[str, Any]) -> TailState:
    """Validate a trace, optionally reporting its incomplete final line."""
    size, state, observed, stopped = os.fstat(fd).st_size, TailState(), None, False
    with os.fdopen(os.dup(fd), "rb", buffering=0) as reader:
        while state.valid_bytes < size and not stopped:
            start = state.valid_bytes
            line, end = reader.readline(MAX_FRAME_BYTES + 2), reader.tell()
            state, progress = _scan_line(
                line, state, (start, end, size, accept_torn),
                (expected_identity, observed))
            observed, stopped = progress
    return state


def _incomplete_tail(state: TailState, start: int, end: int,
                     bounds: tuple[int, bool]) -> TailState:
    """Classify a bounded final fragment without mutating the trace."""
    size, allowed = bounds
    if end != size:
        raise TraceCorruption("trace contains an oversized or interior partial record")
    torn = size - start
    if not allowed:
        raise TornTraceTail(torn)
    return TailState(state.sequence, state.digest, start, torn, state.clock,
                     state.last_event, state.terminal_disposition,
                     state.terminal_result_digest)


def encode_frame(payload: dict[str, Any], tail: TailState) -> tuple[bytes, str]:
    """Build one canonical line chained to a validated tail."""
    _validate_payload(payload)
    _advance_clock(tail.clock, payload)
    payload_bytes = canonical(payload)
    core = {
        "frameVersion": FRAME_VERSION,
        "payload": payload,
        "payloadByteLength": len(payload_bytes),
        "payloadCrc32": f"{zlib.crc32(payload_bytes) & 0xffffffff:08x}",
        "priorDigest": tail.digest,
        "sequence": tail.sequence + 1,
    }
    digest = hashlib.sha256(b"sniper-trace-event-v3\0" + canonical(core)).hexdigest()
    line = canonical({**core, "eventDigest": digest}) + b"\n"
    if len(line) > MAX_FRAME_BYTES:
        raise TraceError(f"trace frame exceeds {MAX_FRAME_BYTES} bytes")
    return line, digest
