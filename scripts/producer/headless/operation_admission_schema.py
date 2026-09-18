"""Exact V3 wire authority for one code-agent MP4 operation admission."""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from dataclasses import dataclass

from . import quality_receipt_json as wire
from .artifact_contract import ArtifactRefV1
from .operation_wire import canonical, parse_parent
from .repair_intent import ParentRefV1

OperationAdmissionSchemaError = wire.QualityReceiptSchemaError

_ADMISSION_DOMAIN = b"sniper-headless-mp4-operation-admission-v3\0"
_REQUEST_IDENTITY_DOMAIN = b"sniper-headless-mp4-admission-request-v3\0"
_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")
_TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z"
)
_TOP_KEYS = frozenset(
    "attemptId authorityId authorityKind buildId executionPolicyId expectedParent "
    "firstSubmittedAt idempotencyKey intendedChildGenerationId operation "
    "qualityRequest realizationKind releaseId requestIdentityDigest schemaVersion "
    "unitId".split()
)
_OPERATION_KEYS = frozenset("artifact kind operationDigest".split())
_QUALITY_KEYS = frozenset("repairRequestId requestDigest".split())
_REQUEST_IDENTITY_KEYS = frozenset(
    "authorityId authorityKind buildId executionPolicyId expectedParent operation "
    "qualityRequest realizationKind releaseId schemaVersion unitId".split()
)


@dataclass(frozen=True)
class OperationArtifactAuthorityV3:
    """Exact operation file bytes plus their domain-separated operation identity."""

    kind: str
    artifact: ArtifactRefV1
    operation_digest: str


@dataclass(frozen=True)
class QualityRequestIdentityV3:
    """Nested quality request identity available only for a quality pass."""

    request_digest: str
    repair_request_id: str


@dataclass(frozen=True)
class OperationAdmissionV3:
    """Immutable admission bytes; not an execution or publication capability."""

    authority_id: str
    idempotency_key: str
    attempt_id: str
    intended_child_generation_id: str
    unit_id: str
    first_submitted_at: str
    release_id: str
    build_id: str
    execution_policy_id: str
    expected_parent: ParentRefV1 | None
    operation: OperationArtifactAuthorityV3
    quality_request: QualityRequestIdentityV3 | None
    request_identity_digest: str
    document_json: bytes
    admission_digest: str


def _identity(value: object, label: str) -> str:
    if type(value) is not str or not _IDENTITY.fullmatch(value):
        raise OperationAdmissionSchemaError(f"{label} is invalid")
    return value


def _timestamp(value: object) -> str:
    if type(value) is not str or not _TIMESTAMP.fullmatch(value):
        raise OperationAdmissionSchemaError(
            "firstSubmittedAt is not canonical UTC"
        )
    try:
        parsed = dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise OperationAdmissionSchemaError(
            "firstSubmittedAt is not canonical UTC"
        ) from exc
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise OperationAdmissionSchemaError(
            "firstSubmittedAt is not canonical UTC"
        )
    return value


def _operation(value: object) -> OperationArtifactAuthorityV3:
    row = wire.exact(value, _OPERATION_KEYS, "operation admission operation")
    if type(row["kind"]) is not str or row["kind"] not in {
        "initialize",
        "quality-pass",
    }:
        raise OperationAdmissionSchemaError(
            "admitted operation kind is invalid"
        )
    return OperationArtifactAuthorityV3(
        row["kind"],
        wire.artifact(row["artifact"]),
        wire.digest(row["operationDigest"], "admitted operation digest"),
    )


def _quality(value: object) -> QualityRequestIdentityV3:
    row = wire.exact(value, _QUALITY_KEYS, "admitted quality request")
    return QualityRequestIdentityV3(
        wire.digest(row["requestDigest"], "quality request digest"),
        wire.canonical_uuid(row["repairRequestId"], "repair request ID"),
    )


def _request_identity(document: dict) -> str:
    projection = {key: document[key] for key in _REQUEST_IDENTITY_KEYS}
    return hashlib.sha256(
        _REQUEST_IDENTITY_DOMAIN + canonical(projection)
    ).hexdigest()


def _mode_values(document: dict) -> tuple[ParentRefV1 | None, object]:
    operation = document["operation"]
    kind = operation.get("kind") if type(operation) is dict else None
    parent_value, quality_value = (
        document["expectedParent"],
        document["qualityRequest"],
    )
    if kind == "initialize" and parent_value is None and quality_value is None:
        return None, None
    if (
        kind == "quality-pass"
        and parent_value is not None
        and quality_value is not None
    ):
        return parse_parent(parent_value), _quality(quality_value)
    raise OperationAdmissionSchemaError(
        "admission operation mode is inconsistent"
    )


def _no_role_aliases(identities: tuple[str, ...], quality: object) -> None:
    if len(set(identities)) != len(identities):
        raise OperationAdmissionSchemaError("admission UUID roles alias")
    if type(quality) is QualityRequestIdentityV3:
        if quality.repair_request_id in identities:
            raise OperationAdmissionSchemaError(
                "quality request UUID role aliases"
            )


def _validate_envelope(document: dict) -> None:
    envelope = (
        type(document["schemaVersion"]),
        document["schemaVersion"],
        document["authorityKind"],
        document["realizationKind"],
    )
    if envelope != (int, 3, "operation-admission-v3", "deterministic-mp4"):
        raise OperationAdmissionSchemaError(
            "operation admission envelope is invalid"
        )


def _parse(document: dict, raw: bytes) -> OperationAdmissionV3:
    wire.exact(document, _TOP_KEYS, "operation admission V3")
    _validate_envelope(document)
    operation = _operation(document["operation"])
    parent, quality = _mode_values(document)
    authority = wire.authority(document["authorityId"])
    if parent is not None and parent.authority_id != authority:
        raise OperationAdmissionSchemaError(
            "admission parent crosses authority"
        )
    idempotency = wire.canonical_uuid(
        document["idempotencyKey"], "idempotency key"
    )
    attempt = wire.canonical_uuid(document["attemptId"], "attempt ID")
    child = wire.canonical_uuid(
        document["intendedChildGenerationId"], "intended child generation ID"
    )
    unit = wire.canonical_uuid(document["unitId"], "admission unit ID")
    if parent is not None and parent.generation_id == child:
        raise OperationAdmissionSchemaError(
            "intended child aliases its parent"
        )
    expected_identity = _request_identity(document)
    actual_identity = wire.digest(
        document["requestIdentityDigest"], "admission request identity digest"
    )
    if actual_identity != expected_identity:
        raise OperationAdmissionSchemaError(
            "admission request identity is stale"
        )
    _no_role_aliases((idempotency, attempt, child, unit), quality)
    return OperationAdmissionV3(
        authority,
        idempotency,
        attempt,
        child,
        unit,
        _timestamp(document["firstSubmittedAt"]),
        _identity(document["releaseId"], "release ID"),
        _identity(document["buildId"], "build ID"),
        wire.digest(document["executionPolicyId"], "execution policy ID"),
        parent,
        operation,
        quality,
        actual_identity,
        raw,
        hashlib.sha256(_ADMISSION_DOMAIN + raw).hexdigest(),
    )


def parse_operation_admission_v3(raw: object) -> OperationAdmissionV3:
    """Parse exact canonical V3 bytes with a typed parent and closed key set."""
    document = wire.canonical_document(raw, "operation admission V3")
    return _parse(document, raw)


def validate_operation_admission_v3(value: object) -> None:
    """Reject mutation, direct construction, and attacker-defined equality."""
    if type(value) is not OperationAdmissionV3:
        raise OperationAdmissionSchemaError(
            "operation admission instance is invalid"
        )
    if type(value.document_json) is not bytes:
        raise OperationAdmissionSchemaError(
            "operation admission bytes are invalid"
        )
    parsed = parse_operation_admission_v3(value.document_json)
    if not wire.same_typed_value(value, parsed):
        raise OperationAdmissionSchemaError(
            "operation admission identity is invalid"
        )


def request_identity_digest_v3(document: dict) -> str:
    """Derive stable request identity, excluding admission-created replay fields."""
    wire.exact(
        document, _TOP_KEYS - {"requestIdentityDigest"}, "admission request"
    )
    projection = {key: document[key] for key in _REQUEST_IDENTITY_KEYS}
    return hashlib.sha256(
        _REQUEST_IDENTITY_DOMAIN + canonical(projection)
    ).hexdigest()
