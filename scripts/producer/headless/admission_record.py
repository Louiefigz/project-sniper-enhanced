"""Canonical legacy admission request and durable record wire contract."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import uuid
from dataclasses import dataclass

_DIGEST = re.compile(r"[0-9a-f]{64}")
_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")
_RECORD_KEYS = frozenset(
    "attemptId authorityId buildId expectedParent firstSubmittedAt "
    "idempotencyKey policyId releaseId requestIdentityDigest schemaVersion "
    "unitId".split()
)


class AdmissionError(RuntimeError):
    """Base error for durable admission."""


class IdempotencyConflict(AdmissionError):
    """An idempotency key was reused with another request identity."""


class AttemptConflict(AdmissionError):
    """An attempt ID is already claimed by another admission."""


class AttemptNotAdmitted(AdmissionError):
    """No durable admission owns the requested attempt ID."""


class AttemptStateConflict(AdmissionError):
    """An admitted attempt's initialization state is missing or unsafe."""


@dataclass(frozen=True)
class AdmissionRequest:
    """Immutable values persisted before returning durable acceptance."""

    authority_root: str
    authority_id: str
    idempotency_key: str
    request_identity_digest: str
    attempt_id: str
    unit_id: str
    first_submitted_at: str
    release_id: str
    build_id: str
    policy_id: str
    expected_parent: str | None


def _canonical(value: dict) -> bytes:
    text = json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    )
    return (text + "\n").encode("ascii")


def _uuid(label: str, value: str) -> str:
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise AdmissionError(f"{label} must be a UUID") from exc
    if str(parsed) != value:
        raise AdmissionError(f"{label} must use canonical lowercase UUID form")
    return value


def _parent(value: object) -> str | None:
    if value is None:
        return None
    if type(value) is not str:
        raise AdmissionError("expected parent is invalid")
    encoded = value.encode("utf-8")
    if (
        not value
        or len(encoded) > 1024
        or any(ord(char) < 32 for char in value)
    ):
        raise AdmissionError("expected parent is invalid")
    return value


def _identity(label: str, value: object) -> str:
    if type(value) is not str or not _IDENTITY.fullmatch(value):
        raise AdmissionError(f"{label} is invalid")
    return value


def _timestamp(value: object) -> str:
    try:
        timestamp = dt.datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise AdmissionError(
            "firstSubmittedAt must be an ISO timestamp"
        ) from exc
    if timestamp.utcoffset() != dt.timedelta(0):
        raise AdmissionError("firstSubmittedAt must be UTC")
    return value


def _record(request: AdmissionRequest) -> dict:
    authority = _identity("authority ID", request.authority_id)
    release = _identity("release ID", request.release_id)
    build = _identity("build ID", request.build_id)
    policy = _identity("policy ID", request.policy_id)
    _uuid("idempotency key", request.idempotency_key)
    _uuid("attempt ID", request.attempt_id)
    _uuid("unit ID", request.unit_id)
    digest = request.request_identity_digest
    if type(digest) is not str or not _DIGEST.fullmatch(digest):
        raise AdmissionError(
            "request identity digest must be lowercase SHA-256"
        )
    submitted = _timestamp(request.first_submitted_at)
    return {
        "attemptId": request.attempt_id,
        "authorityId": authority,
        "buildId": build,
        "expectedParent": _parent(request.expected_parent),
        "firstSubmittedAt": submitted,
        "idempotencyKey": request.idempotency_key,
        "policyId": policy,
        "releaseId": release,
        "requestIdentityDigest": digest,
        "schemaVersion": 2,
        "unitId": request.unit_id,
    }


def _decode(raw: bytes) -> dict:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdmissionError("admission record is invalid JSON") from exc
    if type(value) is not dict or set(value) != _RECORD_KEYS:
        raise AdmissionError("admission record schema is invalid")
    if _canonical(value) != raw:
        raise AdmissionError("admission record is not canonical")
    reconstructed = _record(
        AdmissionRequest(
            "",
            value["authorityId"],
            value["idempotencyKey"],
            value["requestIdentityDigest"],
            value["attemptId"],
            value["unitId"],
            value["firstSubmittedAt"],
            value["releaseId"],
            value["buildId"],
            value["policyId"],
            value["expectedParent"],
        )
    )
    if reconstructed != value:
        raise AdmissionError("admission record values are invalid")
    return value


def _record_name(key: str) -> str:
    digest = hashlib.sha256(
        b"sniper-idempotency-v1\0" + key.encode("ascii")
    ).hexdigest()
    return f"{digest}.json"
