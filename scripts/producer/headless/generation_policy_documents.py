"""Closed policy documents bound to one immutable generation commit."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache

from .generation_schema import GenerationCommitV1, parse_generation_commit
from .quality_policy import (
    DeterministicQualityPolicyV1,
    current_deterministic_quality_policy,
    decode_deterministic_quality_policy,
)
from .repair_intent import (
    AccentRepairPolicy,
    accent_policy,
    current_accent_policy,
)
from .wire_identity import same_wire_value

EXECUTION_POLICY_CLASS = "execution-policy-v1"
REPAIR_POLICY_CLASS = "repair-policy-v1"
QUALITY_POLICY_CLASS = "quality-policy-v1"
FALLBACK_POLICY_CLASS = "fallback-policy-v1"
GENERATION_POLICY_CLASSES = frozenset(
    {
        EXECUTION_POLICY_CLASS,
        REPAIR_POLICY_CLASS,
        QUALITY_POLICY_CLASS,
        FALLBACK_POLICY_CLASS,
    }
)

_EXECUTION_DOMAIN = b"sniper-execution-policy-v1\0"
_FALLBACK_DOMAIN = b"sniper-fallback-policy-v1\0"
_EFFECT_CLASS = "SECTION_MARKER_ACCENT_V1"


class GenerationPolicyDocumentError(RuntimeError):
    """A generation policy document is malformed, stale, or misbound."""


class _DuplicateKey(ValueError):
    pass


@dataclass(frozen=True)
class ExecutionPolicyV1:
    """Exact current code-agent-to-private-MP4 execution authority."""

    document_json: bytes
    policy_id: str

    def decoded_document(self) -> dict:
        """Return a disposable copy of the authoritative policy bytes."""
        return json.loads(self.document_json)


@dataclass(frozen=True)
class FallbackPolicyV1:
    """Exact prohibition on fallback, alternates, and publication."""

    document_json: bytes
    policy_id: str

    def decoded_document(self) -> dict:
        """Return a disposable copy of the authoritative policy bytes."""
        return json.loads(self.document_json)


@dataclass(frozen=True)
class GenerationPolicyDocumentsV1:
    """The four current immutable policies cross-bound to a commit."""

    execution: ExecutionPolicyV1
    repair: AccentRepairPolicy
    quality: DeterministicQualityPolicyV1
    fallback: FallbackPolicyV1


def _canonical(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise GenerationPolicyDocumentError(
            "policy JSON cannot be canonicalized"
        ) from exc
    return encoded.encode("ascii")


def _pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(key)
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON value: {value}")


def _decode_exact(raw: object, label: str) -> dict:
    if type(raw) is not bytes:
        raise GenerationPolicyDocumentError(f"{label} must be immutable bytes")
    try:
        decoded = json.loads(
            raw, object_pairs_hook=_pairs, parse_constant=_reject_constant
        )
    except _DuplicateKey as exc:
        raise GenerationPolicyDocumentError(f"{label} has duplicate JSON keys") from exc
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise GenerationPolicyDocumentError(f"{label} is invalid JSON") from exc
    if type(decoded) is not dict or _canonical(decoded) != raw:
        raise GenerationPolicyDocumentError(f"{label} is not exact canonical JSON")
    return decoded


def _execution_document() -> dict:
    return {
        "schemaVersion": 1,
        "executionPath": {
            "kind": "code-agent-only",
            "guiAllowed": False,
            "palmierAllowed": False,
        },
        "realization": {
            "kind": "deterministic-mp4",
            "fallbackPolicy": "none",
            "writerRebuildAllowed": False,
            "baseRebuildAllowed": False,
        },
        "compositor": {
            "kind": "prebound-compositor",
            "eofAction": "pass",
            "audioDisposition": "copy",
            "proxyDisposition": "omitted-by-policy",
        },
        "publication": {
            "allowed": False,
            "candidateDisposition": "private-counterfactual",
        },
    }


def _fallback_document() -> dict:
    return {
        "schemaVersion": 1,
        "fallbackPolicy": "none",
        "alternateRealizationAllowed": False,
        "publicationAllowed": False,
    }


@lru_cache(maxsize=1)
def current_execution_policy() -> ExecutionPolicyV1:
    """Return the process-stable sole R0 execution policy."""
    raw = _canonical(_execution_document())
    policy_id = hashlib.sha256(_EXECUTION_DOMAIN + raw).hexdigest()
    return ExecutionPolicyV1(raw, policy_id)


@lru_cache(maxsize=1)
def current_fallback_policy() -> FallbackPolicyV1:
    """Return the process-stable sole R0 fallback policy."""
    raw = _canonical(_fallback_document())
    policy_id = hashlib.sha256(_FALLBACK_DOMAIN + raw).hexdigest()
    return FallbackPolicyV1(raw, policy_id)


def decode_execution_policy(raw: object) -> ExecutionPolicyV1:
    """Decode exact canonical bytes and require the current execution policy."""
    _decode_exact(raw, "execution policy")
    current = current_execution_policy()
    if raw != current.document_json:
        raise GenerationPolicyDocumentError("execution policy is not current")
    return current


def decode_fallback_policy(raw: object) -> FallbackPolicyV1:
    """Decode exact canonical bytes and require the current fallback policy."""
    _decode_exact(raw, "fallback policy")
    current = current_fallback_policy()
    if raw != current.document_json:
        raise GenerationPolicyDocumentError("fallback policy is not current")
    return current


def _decode_repair_policy(raw: object) -> AccentRepairPolicy:
    document = _decode_exact(raw, "repair policy")
    current = current_accent_policy()
    expected = {
        "schemaVersion": 1,
        "effectClass": _EFFECT_CLASS,
        "allowedValues": list(current.allowed_values),
    }
    if raw != _canonical(expected):
        raise GenerationPolicyDocumentError("repair policy is not current")
    derived = accent_policy(tuple(document["allowedValues"]))
    if not same_wire_value(derived, current):
        raise GenerationPolicyDocumentError("repair policy derivation is invalid")
    return derived


def _decode_quality_policy(raw: object) -> DeterministicQualityPolicyV1:
    _decode_exact(raw, "quality policy")
    try:
        policy = decode_deterministic_quality_policy(raw)
    except RuntimeError as exc:
        raise GenerationPolicyDocumentError("quality policy is invalid") from exc
    if not same_wire_value(policy, current_deterministic_quality_policy()):
        raise GenerationPolicyDocumentError("quality policy is not current")
    return policy


def _validate_commit(commit: object) -> GenerationCommitV1:
    if type(commit) is not GenerationCommitV1:
        raise GenerationPolicyDocumentError("commit must use the V1 wire type")
    try:
        parsed = parse_generation_commit(commit.document_json)
    except RuntimeError as exc:
        raise GenerationPolicyDocumentError("commit wire identity is invalid") from exc
    if not same_wire_value(commit, parsed):
        raise GenerationPolicyDocumentError("commit wire identity is invalid")
    return parsed


def _snapshot_artifacts(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise GenerationPolicyDocumentError("policy artifacts must be a mapping")
    try:
        snapshot = dict(value)
    except (TypeError, ValueError) as exc:
        raise GenerationPolicyDocumentError("policy artifacts are invalid") from exc
    if set(snapshot) != GENERATION_POLICY_CLASSES:
        raise GenerationPolicyDocumentError("policy artifact closure is invalid")
    return snapshot


def validate_generation_policy_documents(
    commit: GenerationCommitV1,
    artifact_bytes_mapping: Mapping[str, bytes],
) -> GenerationPolicyDocumentsV1:
    """Validate the exact four current policy bytes and their commit IDs."""
    parsed = _validate_commit(commit)
    artifacts = _snapshot_artifacts(artifact_bytes_mapping)
    execution = decode_execution_policy(artifacts[EXECUTION_POLICY_CLASS])
    repair = _decode_repair_policy(artifacts[REPAIR_POLICY_CLASS])
    quality = _decode_quality_policy(artifacts[QUALITY_POLICY_CLASS])
    fallback = decode_fallback_policy(artifacts[FALLBACK_POLICY_CLASS])
    actual = (
        execution.policy_id,
        repair.policy_id,
        quality.policy_id,
        fallback.policy_id,
    )
    expected = (
        parsed.execution_policy_id,
        parsed.repair_policy_id,
        parsed.quality_policy_id,
        parsed.fallback_policy_id,
    )
    if actual != expected:
        raise GenerationPolicyDocumentError("policy IDs do not match commit")
    return GenerationPolicyDocumentsV1(execution, repair, quality, fallback)
