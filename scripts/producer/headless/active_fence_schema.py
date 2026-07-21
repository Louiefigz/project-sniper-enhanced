"""Canonical five-field materialized active-fence documents."""

from __future__ import annotations

from . import quality_receipt_json as wire
from .active_fence_types import ActiveFenceStateV1
from .operation_wire import canonical

_FENCE_KEYS = frozenset(
    "activeAttemptId authorityId fenceRevision fenceToken schemaVersion".split()
)


class ActiveFenceSchemaError(RuntimeError):
    """Fence bytes or transition semantics violate the closed schema."""


def validate_active_fence_attempt_id_v1(value: object) -> str:
    """Require one canonical attempt UUID."""
    try:
        return wire.canonical_uuid(value, "active-fence attempt ID")
    except wire.QualityReceiptSchemaError as exc:
        raise ActiveFenceSchemaError(str(exc)) from exc


def validate_active_fence_token_v1(value: object) -> str:
    """Require one canonical random fence-token UUID."""
    try:
        return wire.canonical_uuid(value, "active-fence token")
    except wire.QualityReceiptSchemaError as exc:
        raise ActiveFenceSchemaError(str(exc)) from exc


def validate_active_fence_authority_v1(value: object) -> str:
    """Require the shared closed authority identifier syntax."""
    try:
        return wire.authority(value)
    except wire.QualityReceiptSchemaError as exc:
        raise ActiveFenceSchemaError(str(exc)) from exc


def build_active_fence_state_v1(
    authority_id: str,
    revision: int,
    fence_token: str,
    active_attempt_id: str | None,
) -> ActiveFenceStateV1:
    """Build exact canonical state from already-intended values."""
    authority = validate_active_fence_authority_v1(authority_id)
    if type(revision) is not int or revision < 0:
        raise ActiveFenceSchemaError("fence revision is invalid")
    token = validate_active_fence_token_v1(fence_token)
    active = active_attempt_id
    if active is not None:
        active = validate_active_fence_attempt_id_v1(active)
    document = canonical(
        {
            "schemaVersion": 1,
            "authorityId": authority,
            "fenceRevision": revision,
            "fenceToken": token,
            "activeAttemptId": active,
        }
    )
    return ActiveFenceStateV1(authority, revision, token, active, document)


def parse_active_fence_document_v1(raw: object) -> ActiveFenceStateV1:
    """Parse exact canonical five-field materialized FENCE bytes."""
    try:
        row = wire.canonical_document(raw, "active-fence document")
        wire.exact(row, _FENCE_KEYS, "active-fence document")
    except wire.QualityReceiptSchemaError as exc:
        raise ActiveFenceSchemaError(str(exc)) from exc
    if (type(row["schemaVersion"]), row["schemaVersion"]) != (int, 1):
        raise ActiveFenceSchemaError("fence schema version is invalid")
    result = build_active_fence_state_v1(
        row["authorityId"],
        row["fenceRevision"],
        row["fenceToken"],
        row["activeAttemptId"],
    )
    if result.document_json != raw:
        raise ActiveFenceSchemaError("active-fence bytes are not canonical")
    return result
