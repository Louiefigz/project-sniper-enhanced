"""Acyclic verification record for one complete R0 generation payload."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass

from .artifact_contract import (
    ArtifactContractError,
    ArtifactRefV1,
    validate_artifact_ref,
)
from .generation_schema import GenerationCommitV1, GenerationManifestRowV1
from .generation_schema import parse_generation_commit
from .wire_identity import same_wire_value

_DIGEST = re.compile(r"[0-9a-f]{64}")
_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")
_PROFILE = "deterministic-mp4-r0-v1"
_DOMAIN = b"sniper-generation-payload-manifest-v1\0"
_KEYS = frozenset(
    "approvedParent attemptId authorityId executionPolicyId fallbackPolicyId "
    "generationId payloadManifestDigest profile qualityPolicyId repairPolicyId "
    "requestDigest schemaVersion status unitId".split()
)
_ARTIFACT_KEYS = frozenset("path sha256 sizeBytes".split())


class GenerationVerificationError(RuntimeError):
    """A generation verification record is malformed or self-referential."""


class _DuplicateKey(ValueError):
    pass


@dataclass(frozen=True)
class GenerationVerificationV1:
    """Pass record written after every payload except this record is frozen."""

    authority_id: str
    generation_id: str
    attempt_id: str
    unit_id: str
    request_digest: str
    execution_policy_id: str
    repair_policy_id: str
    quality_policy_id: str
    fallback_policy_id: str
    approved_parent: ArtifactRefV1
    payload_manifest_digest: str
    document_json: bytes


def _canonical(value: object) -> bytes:
    try:
        text = json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise GenerationVerificationError("verification JSON is not canonical") from exc
    return text.encode("ascii")


def _pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(key)
        result[key] = value
    return result


def _document(raw: object) -> tuple[dict, bytes]:
    if type(raw) is dict:
        return raw, _canonical(raw)
    if type(raw) is not bytes:
        raise GenerationVerificationError("verification must be canonical bytes")
    try:
        value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
    except _DuplicateKey as exc:
        raise GenerationVerificationError("verification has duplicate keys") from exc
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise GenerationVerificationError("verification is invalid JSON") from exc
    if type(value) is not dict or _canonical(value) != raw:
        raise GenerationVerificationError("verification is not exact canonical JSON")
    return value, raw


def _constant(value: str) -> None:
    raise ValueError(f"non-finite value: {value}")


def _artifact(value: object) -> ArtifactRefV1:
    if type(value) is not dict or set(value) != _ARTIFACT_KEYS:
        raise GenerationVerificationError("approved-parent reference is invalid")
    artifact = ArtifactRefV1(
        value.get("path"), value.get("sha256"), value.get("sizeBytes")
    )
    try:
        validate_artifact_ref(artifact)
    except ArtifactContractError as exc:
        raise GenerationVerificationError(str(exc)) from exc
    return artifact


def _uuid(value: object) -> str:
    if type(value) is not str:
        raise GenerationVerificationError("generation ID is invalid")
    try:
        canonical = str(uuid.UUID(value))
    except ValueError as exc:
        raise GenerationVerificationError("generation ID is invalid") from exc
    if canonical != value:
        raise GenerationVerificationError("generation ID is invalid")
    return value


def _row_value(row: GenerationManifestRowV1) -> dict:
    return {
        "artifactClass": row.artifact_class,
        "path": row.path,
        "sha256": row.sha256,
        "sizeBytes": row.size_bytes,
    }


def payload_manifest_digest(rows: object) -> str:
    """Bind every ordered payload row while excluding the verification itself."""
    valid = (
        type(rows) is tuple
        and bool(rows)
        and all(type(row) is GenerationManifestRowV1 for row in rows)
        and not any(row.artifact_class == "generation-verification-v1" for row in rows)
    )
    if not valid:
        raise GenerationVerificationError("payload rows are invalid or recursive")
    ordered = sorted(rows, key=lambda row: row.path)
    return hashlib.sha256(
        _DOMAIN + _canonical([_row_value(row) for row in ordered])
    ).hexdigest()


def parse_generation_verification(value: object) -> GenerationVerificationV1:
    """Parse one exact acyclic verification record."""
    document, raw = _document(value)
    valid = (
        set(document) == _KEYS
        and type(document.get("schemaVersion")) is int
        and document["schemaVersion"] == 1
        and document.get("status") == "pass"
        and document.get("profile") == _PROFILE
        and type(document.get("authorityId")) is str
        and bool(_IDENTITY.fullmatch(document["authorityId"]))
    )
    if not valid:
        raise GenerationVerificationError("verification envelope is invalid")
    digests = (
        document.get("requestDigest"),
        document.get("executionPolicyId"),
        document.get("repairPolicyId"),
        document.get("qualityPolicyId"),
        document.get("fallbackPolicyId"),
        document.get("payloadManifestDigest"),
    )
    if not all(type(item) is str and _DIGEST.fullmatch(item) for item in digests):
        raise GenerationVerificationError("verification digest is invalid")
    return GenerationVerificationV1(
        document["authorityId"],
        _uuid(document["generationId"]),
        _uuid(document["attemptId"]),
        _uuid(document["unitId"]),
        document["requestDigest"],
        document["executionPolicyId"],
        document["repairPolicyId"],
        document["qualityPolicyId"],
        document["fallbackPolicyId"],
        _artifact(document["approvedParent"]),
        document["payloadManifestDigest"],
        raw,
    )


def _payload_rows(
    commit: GenerationCommitV1,
) -> tuple[tuple[GenerationManifestRowV1, ...], int]:
    rows = tuple(
        row
        for row in commit.files
        if row.artifact_class != "generation-verification-v1"
    )
    return rows, len(commit.files) - len(rows)


def validate_generation_verification(
    value: object, commit: GenerationCommitV1, approved_parent: ArtifactRefV1
) -> None:
    """Bind a parsed record to one commit without including its own row."""
    if type(value) is not GenerationVerificationV1:
        raise GenerationVerificationError("verification instance is invalid")
    if type(commit) is not GenerationCommitV1:
        raise GenerationVerificationError("verification commit is invalid")
    try:
        validate_artifact_ref(approved_parent)
    except ArtifactContractError as exc:
        raise GenerationVerificationError(str(exc)) from exc
    parsed = parse_generation_verification(value.document_json)
    if not same_wire_value(value, parsed):
        raise GenerationVerificationError("verification instance identity is invalid")
    reparsed_commit = parse_generation_commit(commit.document_json)
    if not same_wire_value(commit, reparsed_commit):
        raise GenerationVerificationError("verification commit identity is invalid")
    rows, verification_count = _payload_rows(commit)
    expected = (
        commit.authority_id,
        commit.generation_id,
        commit.attempt_id,
        commit.unit_id,
        commit.request_digest,
        commit.execution_policy_id,
        commit.repair_policy_id,
        commit.quality_policy_id,
        commit.fallback_policy_id,
        approved_parent,
        payload_manifest_digest(rows),
    )
    actual = (
        value.authority_id,
        value.generation_id,
        value.attempt_id,
        value.unit_id,
        value.request_digest,
        value.execution_policy_id,
        value.repair_policy_id,
        value.quality_policy_id,
        value.fallback_policy_id,
        value.approved_parent,
        value.payload_manifest_digest,
    )
    if verification_count != 1 or actual != expected:
        raise GenerationVerificationError("verification does not bind the generation")
