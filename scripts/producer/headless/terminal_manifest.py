"""Crash-recoverable terminal manifest bound to the final trace frame."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

from .attempt_trace import (
    AttemptTrace,
    TornTraceTail,
    TraceCorruption,
    validate_existing_trace,
)
from .durable_files import (
    DurableFileError,
    locked_private_dir,
    read_private_file,
    write_pending_replace,
)
from .trace_frames import TraceError, canonical
from .trace_state import TERMINAL_DISPOSITIONS
from .terminal_intent import (
    TerminalIntentError,
    build_terminal_intent,
    ensure_terminal_intent,
    read_terminal_intent,
    terminal_result_digest,
    validate_terminal_result,
)

MANIFEST_NAME = "terminal-manifest.json"
_PENDING_NAME = ".terminal-manifest.pending"
_LOCK_NAME = ".terminal-manifest.lock"
_KEYS = {
    "attemptId", "authorityId", "buildId", "disposition", "expectedParent",
    "policyId", "releaseId", "requestDigest", "result", "resultDigest",
    "schemaVersion", "terminalSequence", "terminalTraceDigest", "unitId",
}
_DIGEST = re.compile(r"[0-9a-f]{64}")
_MAX_MANIFEST_BYTES = 1_000_000


class TerminalManifestError(RuntimeError):
    """A terminal trace and manifest cannot be reconciled exactly."""


@dataclass(frozen=True)
class TerminalSealRequest:
    """Terminal outcome to seal for one trace."""

    trace: AttemptTrace
    disposition: str
    result: dict[str, Any]


def _encode(value: dict) -> bytes:
    try:
        encoded = canonical(value) + b"\n"
    except TraceError as exc:
        raise TerminalManifestError(str(exc)) from exc
    if len(encoded) > _MAX_MANIFEST_BYTES:
        raise TerminalManifestError("terminal manifest exceeds its size limit")
    return encoded


def _decode(raw: bytes) -> dict:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TerminalManifestError("terminal manifest is invalid JSON") from exc
    if not isinstance(value, dict) or set(value) != _KEYS or _encode(value) != raw:
        raise TerminalManifestError("terminal manifest schema or encoding is invalid")
    try:
        computed_result_digest = terminal_result_digest(value.get("result"))
    except TerminalIntentError as exc:
        raise TerminalManifestError(str(exc)) from exc
    valid = (
        value["schemaVersion"] == 4
        and value["disposition"] in TERMINAL_DISPOSITIONS
        and isinstance(value["attemptId"], str) and bool(value["attemptId"])
        and isinstance(value["authorityId"], str) and bool(value["authorityId"])
        and isinstance(value["buildId"], str) and bool(value["buildId"])
        and isinstance(value["policyId"], str) and bool(value["policyId"])
        and isinstance(value["releaseId"], str) and bool(value["releaseId"])
        and (value["expectedParent"] is None
             or (isinstance(value["expectedParent"], str)
                 and bool(value["expectedParent"])))
        and isinstance(value["requestDigest"], str)
        and bool(_DIGEST.fullmatch(value["requestDigest"]))
        and isinstance(value["unitId"], str) and bool(value["unitId"])
        and type(value["terminalSequence"]) is int
        and value["terminalSequence"] > 0
        and isinstance(value["terminalTraceDigest"], str)
        and bool(_DIGEST.fullmatch(value["terminalTraceDigest"]))
        and isinstance(value["resultDigest"], str)
        and bool(_DIGEST.fullmatch(value["resultDigest"]))
        and isinstance(value["result"], dict)
        and value["resultDigest"] == computed_result_digest
    )
    if not valid:
        raise TerminalManifestError("terminal manifest values are invalid")
    identity = {key: value[key] for key in (
        "attemptId", "authorityId", "buildId", "expectedParent", "policyId",
        "releaseId", "requestDigest", "unitId")}
    try:
        validate_terminal_result(value["disposition"], value["result"], identity)
    except TerminalIntentError as exc:
        raise TerminalManifestError(str(exc)) from exc
    return value


def _manifest(trace: AttemptTrace, intent: dict) -> dict:
    state = trace.validate()
    if state.terminal_disposition != intent["disposition"]:
        raise TerminalManifestError("trace terminal disposition does not match request")
    if state.terminal_result_digest != intent["resultDigest"]:
        raise TerminalManifestError("trace terminal result does not match request")
    context = trace.context
    return {
        "attemptId": context.attempt_id,
        "authorityId": context.authority_id,
        "buildId": context.build_id,
        "disposition": intent["disposition"],
        "expectedParent": context.expected_parent,
        "policyId": context.policy_id,
        "releaseId": context.release_id,
        "requestDigest": context.request_digest,
        "result": intent["result"],
        "resultDigest": intent["resultDigest"],
        "schemaVersion": 4,
        "terminalSequence": state.last_sequence,
        "terminalTraceDigest": state.last_digest,
        "unitId": context.unit_id,
    }


def _read_locked(dir_fd: int) -> dict | None:
    try:
        raw = read_private_file(dir_fd, MANIFEST_NAME)
    except DurableFileError as exc:
        if isinstance(exc.__cause__, FileNotFoundError):
            return None
        raise TerminalManifestError(str(exc)) from exc
    return _decode(raw)


def _validate_manifest_trace(attempt_dir: str, manifest: dict) -> None:
    try:
        state = validate_existing_trace(attempt_dir, {
            "attemptId": manifest["attemptId"],
            "authorityId": manifest["authorityId"],
            "buildId": manifest["buildId"],
            "expectedParent": manifest["expectedParent"],
            "policyId": manifest["policyId"],
            "releaseId": manifest["releaseId"],
            "requestDigest": manifest["requestDigest"],
            "unitId": manifest["unitId"],
        })
    except TraceError as exc:
        raise TerminalManifestError("terminal trace is invalid") from exc
    matches = (
        state.last_event == "TERMINAL_SEALED"
        and state.last_sequence == manifest["terminalSequence"]
        and state.last_digest == manifest["terminalTraceDigest"]
        and state.terminal_disposition == manifest["disposition"]
        and state.terminal_result_digest == manifest["resultDigest"]
    )
    if not matches:
        raise TerminalManifestError("terminal manifest is not bound to its trace")


def read_terminal_manifest(attempt_dir: str) -> dict | None:
    """Read and validate a sealed terminal manifest, if one exists."""
    with locked_private_dir(attempt_dir, _LOCK_NAME) as dir_fd:
        manifest = _read_locked(dir_fd)
        if manifest is None:
            return None
        _validate_manifest_trace(attempt_dir, manifest)
        return manifest


def _identity(trace: AttemptTrace) -> dict[str, Any]:
    context = trace.context
    return {
        "attemptId": context.attempt_id,
        "authorityId": context.authority_id,
        "buildId": context.build_id,
        "expectedParent": context.expected_parent,
        "policyId": context.policy_id,
        "releaseId": context.release_id,
        "requestDigest": context.request_digest,
        "unitId": context.unit_id,
    }


def _preflight_terminal(request: TerminalSealRequest) -> None:
    state = request.trace.validate()
    if state.terminal_disposition is not None:
        return
    if state.phase is None:
        raise TraceCorruption("terminal seal requires durable admission")
    if request.disposition == "SUCCEEDED" and state.phase != "POINTER_COMMITTED":
        raise TraceCorruption("success requires a committed pointer")


def _seal_locked(trace: AttemptTrace, intent: dict, dir_fd: int) -> dict:
    repair_torn_tail = False
    try:
        state = trace.validate()
    except TornTraceTail:
        repair_torn_tail = True
        state = None
    if state is None or state.terminal_disposition is None:
        trace.append(
            "TERMINAL_SEALED", {
                "disposition": intent["disposition"],
                "resultDigest": intent["resultDigest"],
            },
            recover_torn_tail=repair_torn_tail)
    expected = _manifest(trace, intent)
    existing = _read_locked(dir_fd)
    if existing is not None:
        if existing != expected:
            raise TerminalManifestError("terminal manifest is immutable")
        return existing
    write_pending_replace(
        dir_fd, (_PENDING_NAME, MANIFEST_NAME), _encode(expected))
    return _read_locked(dir_fd) or expected


def _manifest_without_intent(trace: AttemptTrace, dir_fd: int) -> dict | None:
    manifest = _read_locked(dir_fd)
    if manifest is not None:
        _validate_manifest_trace(trace.attempt_dir, manifest)
    return manifest


def recover_terminal_manifest(trace: AttemptTrace) -> dict | None:
    """Finish a terminal seal from its durable intent after process death."""
    with locked_private_dir(trace.attempt_dir, _LOCK_NAME) as dir_fd:
        try:
            intent = read_terminal_intent(dir_fd)
        except TerminalIntentError as exc:
            raise TerminalManifestError(str(exc)) from exc
        if intent is None:
            return _manifest_without_intent(trace, dir_fd)
        if any(intent[key] != value for key, value in _identity(trace).items()):
            raise TerminalManifestError("terminal intent does not match trace identity")
        return _seal_locked(trace, intent, dir_fd)


def seal_terminal_manifest(request: TerminalSealRequest) -> dict:
    """Seal the trace if needed, then recoverably publish one immutable manifest."""
    if request.disposition not in TERMINAL_DISPOSITIONS:
        raise TerminalManifestError("terminal disposition is invalid")
    _preflight_terminal(request)
    try:
        intent = build_terminal_intent(
            _identity(request.trace), request.disposition, request.result)
    except TerminalIntentError as exc:
        raise TerminalManifestError(str(exc)) from exc
    with locked_private_dir(request.trace.attempt_dir, _LOCK_NAME) as dir_fd:
        try:
            persisted = ensure_terminal_intent(dir_fd, intent)
        except TerminalIntentError as exc:
            raise TerminalManifestError(str(exc)) from exc
        return _seal_locked(request.trace, persisted, dir_fd)
