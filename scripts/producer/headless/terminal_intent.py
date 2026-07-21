"""Durable terminal-result intent written before the terminal trace frame."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import uuid
from typing import Any

from .durable_files import (
    DurableFileError,
    read_private_file,
    write_pending_replace,
)
from .trace_frames import TraceError, canonical
from .trace_state import TERMINAL_DISPOSITIONS

INTENT_NAME = "terminal-intent.json"
PENDING_NAME = ".terminal-intent.pending"
_KEYS = {
    "attemptId", "authorityId", "buildId", "disposition", "expectedParent",
    "policyId", "releaseId", "requestDigest", "result", "resultDigest",
    "schemaVersion", "unitId",
}
_DIGEST = re.compile(r"[0-9a-f]{64}")
_ERROR_CODE = re.compile(r"[A-Z][A-Z0-9_]{1,63}")
_MAX_INTENT_BYTES = 1_000_000
_FAILURE_KEYS = {"errorCode", "evidenceDigest", "schemaVersion"}
_SUCCESS_KEYS = {
    "authorityId", "commitDigest", "generationId",
    "generationVerificationDigest", "mediaFacts", "mp4RelativePath",
    "publicationSeq", "schemaVersion", "sha256",
}
_MEDIA_KEYS = {
    "audioCodec", "durationSeconds", "fps", "frameCount", "height",
    "sizeBytes", "videoCodec", "width",
}


class TerminalIntentError(RuntimeError):
    """A durable terminal intent is missing, malformed, or contradictory."""


def _encode(value: dict) -> bytes:
    try:
        encoded = canonical(value) + b"\n"
    except TraceError as exc:
        raise TerminalIntentError(str(exc)) from exc
    if len(encoded) > _MAX_INTENT_BYTES:
        raise TerminalIntentError("terminal intent exceeds its size limit")
    return encoded


def terminal_result_digest(result: dict[str, Any]) -> str:
    """Return the domain-separated digest committed by the terminal trace."""
    if not isinstance(result, dict):
        raise TerminalIntentError("terminal result must be an object")
    try:
        encoded = canonical(result)
    except TraceError as exc:
        raise TerminalIntentError(str(exc)) from exc
    return hashlib.sha256(b"sniper-terminal-result-v1\0" + encoded).hexdigest()


def _valid_failure(result: dict[str, Any]) -> bool:
    return (
        set(result) == _FAILURE_KEYS and result.get("schemaVersion") == 1
        and isinstance(result.get("errorCode"), str)
        and bool(_ERROR_CODE.fullmatch(result["errorCode"]))
        and isinstance(result.get("evidenceDigest"), str)
        and bool(_DIGEST.fullmatch(result["evidenceDigest"]))
    )


def _valid_media(media: Any) -> bool:
    if not isinstance(media, dict) or set(media) != _MEDIA_KEYS:
        return False
    numeric = (media["durationSeconds"], media["fps"])
    integers = (media["width"], media["height"], media["frameCount"],
                media["sizeBytes"])
    return (
        all(type(value) in {int, float} and math.isfinite(value) and value > 0
            for value in numeric)
        and all(type(value) is int and value > 0 for value in integers)
        and isinstance(media["videoCodec"], str) and bool(media["videoCodec"])
        and (media["audioCodec"] is None
             or (isinstance(media["audioCodec"], str)
                 and bool(media["audioCodec"])))
    )


def _valid_relative_mp4(path: Any) -> bool:
    if not isinstance(path, str) or not path.endswith(".mp4") or "\\" in path:
        return False
    normalized = os.path.normpath(path)
    return (normalized == path and not os.path.isabs(path)
            and all(part not in {"", ".", ".."} for part in path.split("/")))


def _valid_success(result: dict[str, Any], identity: dict[str, Any]) -> bool:
    try:
        generation = str(uuid.UUID(str(result.get("generationId", ""))))
    except ValueError:
        return False
    return (
        set(result) == _SUCCESS_KEYS and result.get("schemaVersion") == 1
        and result.get("authorityId") == identity["authorityId"]
        and type(result.get("publicationSeq")) is int
        and result["publicationSeq"] > 0
        and generation == result.get("generationId")
        and all(bool(_DIGEST.fullmatch(str(result.get(key, ""))))
                for key in ("commitDigest", "generationVerificationDigest", "sha256"))
        and _valid_relative_mp4(result.get("mp4RelativePath"))
        and _valid_media(result.get("mediaFacts"))
    )


def validate_terminal_result(disposition: str, result: dict[str, Any],
                             identity: dict[str, Any]) -> None:
    """Validate the closed terminal-result union before it becomes durable."""
    if not isinstance(result, dict):
        raise TerminalIntentError("terminal result must be an object")
    valid = (_valid_success(result, identity) if disposition == "SUCCEEDED"
             else _valid_failure(result))
    if not valid:
        raise TerminalIntentError(
            f"terminal result is invalid for disposition {disposition}")


def build_terminal_intent(identity: dict[str, Any], disposition: str,
                          result: dict[str, Any]) -> dict:
    """Build and validate one immutable terminal-result intent."""
    required = {
        "attemptId", "authorityId", "buildId", "expectedParent", "policyId",
        "releaseId", "requestDigest", "unitId",
    }
    if set(identity) != required:
        raise TerminalIntentError("terminal intent identity is invalid")
    validate_terminal_result(disposition, result, identity)
    value = {
        **identity,
        "disposition": disposition,
        "result": result,
        "resultDigest": terminal_result_digest(result),
        "schemaVersion": 3,
    }
    return decode_terminal_intent(_encode(value))


def decode_terminal_intent(raw: bytes) -> dict:
    """Decode one exact canonical terminal intent."""
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TerminalIntentError("terminal intent is invalid JSON") from exc
    if not isinstance(value, dict) or set(value) != _KEYS or _encode(value) != raw:
        raise TerminalIntentError("terminal intent schema or encoding is invalid")
    valid = (
        value["schemaVersion"] == 3
        and value["disposition"] in TERMINAL_DISPOSITIONS
        and isinstance(value["attemptId"], str) and bool(value["attemptId"])
        and isinstance(value["authorityId"], str) and bool(value["authorityId"])
        and isinstance(value["buildId"], str) and bool(value["buildId"])
        and isinstance(value["policyId"], str) and bool(value["policyId"])
        and isinstance(value["releaseId"], str) and bool(value["releaseId"])
        and (value["expectedParent"] is None
             or (isinstance(value["expectedParent"], str)
                 and bool(value["expectedParent"])))
        and isinstance(value["unitId"], str) and bool(value["unitId"])
        and isinstance(value["requestDigest"], str)
        and bool(_DIGEST.fullmatch(value["requestDigest"]))
        and isinstance(value["resultDigest"], str)
        and bool(_DIGEST.fullmatch(value["resultDigest"]))
        and isinstance(value["result"], dict)
        and value["resultDigest"] == terminal_result_digest(value["result"])
    )
    if not valid:
        raise TerminalIntentError("terminal intent values are invalid")
    identity = {key: value for key, value in value.items() if key in {
        "attemptId", "authorityId", "buildId", "expectedParent", "policyId",
        "releaseId", "requestDigest", "unitId",
    }}
    validate_terminal_result(value["disposition"], value["result"], identity)
    return value


def read_terminal_intent(dir_fd: int) -> dict | None:
    """Read an optional terminal intent through an already locked directory."""
    try:
        raw = read_private_file(dir_fd, INTENT_NAME)
    except DurableFileError as exc:
        if isinstance(exc.__cause__, FileNotFoundError):
            return None
        raise TerminalIntentError(str(exc)) from exc
    return decode_terminal_intent(raw)


def ensure_terminal_intent(dir_fd: int, intent: dict) -> dict:
    """Durably create one intent or require byte-equivalent replay."""
    expected = decode_terminal_intent(_encode(intent))
    existing = read_terminal_intent(dir_fd)
    if existing is not None:
        if existing != expected:
            raise TerminalIntentError("terminal result intent is immutable")
        return existing
    write_pending_replace(dir_fd, (PENDING_NAME, INTENT_NAME), _encode(expected))
    return read_terminal_intent(dir_fd) or expected
