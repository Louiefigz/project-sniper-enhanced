"""Canonical fence-before-cross-ledger order-start intent schema."""

from __future__ import annotations

import hashlib

from . import quality_receipt_json as wire
from .active_fence_schema import parse_active_fence_document_v1
from .active_fence_types import ActiveFenceStateV1
from .cross_ledger_order_schema import (
    CrossLedgerOrderIdentityV1,
    build_cross_ledger_order_identity_v1,
    require_same_cross_ledger_identity_v1,
)
from .fence_admission_reservation_types import (
    DurableFenceAdmissionReservationV1,
)
from .fence_admission_reservation_validation import (
    validate_durable_fence_admission_reservation_v1,
)
from .fence_order_start_types import FenceOrderStartIntentV1
from .operation_wire import canonical
from .wire_identity import same_wire_value

_START_DOMAIN = b"sniper-fence-order-start-intent-v1\0"
_KEYS = frozenset(
    "activeAttemptId attemptId authorityId authorityKind fenceRevision "
    "fenceToken orderIdentityDigest realizationKind reservationDigest "
    "schemaVersion startDigest".split()
)


class FenceOrderStartSchemaError(RuntimeError):
    """Start-intent bytes or their exact input identities disagree."""


def _validated_identity(value: object) -> CrossLedgerOrderIdentityV1:
    if type(value) is not CrossLedgerOrderIdentityV1:
        raise FenceOrderStartSchemaError("order identity is invalid")
    expected = build_cross_ledger_order_identity_v1(
        (
            value.authority_id,
            value.unit_id,
            value.enrollment_key,
            value.enrollment_record_id,
            value.enrollment_digest,
            value.idempotency_key,
            value.attempt_id,
            value.intended_child_generation_id,
            value.admission_record_id,
            value.admission_digest,
        )
    )
    require_same_cross_ledger_identity_v1(value, expected)
    return expected


def _validated_fence(value: object) -> ActiveFenceStateV1:
    if type(value) is not ActiveFenceStateV1:
        raise FenceOrderStartSchemaError("active fence state is invalid")
    if type(value.document_json) is not bytes:
        raise FenceOrderStartSchemaError("active fence bytes are invalid")
    parsed = parse_active_fence_document_v1(value.document_json)
    if not same_wire_value(value, parsed):
        raise FenceOrderStartSchemaError("active fence identity is invalid")
    return parsed


def _require_binding(
    reservation: DurableFenceAdmissionReservationV1,
    fence: ActiveFenceStateV1,
    identity: CrossLedgerOrderIdentityV1,
) -> None:
    retained = reservation.reservation
    exact = (
        retained.authority_id == identity.authority_id == fence.authority_id
        and retained.attempt_id == identity.attempt_id
        and fence.active_attempt_id == identity.attempt_id
        and retained.order_identity_digest == identity.order_identity_digest
        and retained.enrollment_key == identity.enrollment_key
        and retained.enrollment_digest == identity.enrollment_digest
        and retained.idempotency_key == identity.idempotency_key
        and retained.admission_digest == identity.admission_digest
        and retained.unit_id == identity.unit_id
        and retained.intended_child_generation_id
        == identity.intended_child_generation_id
        and fence.fence_revision > 0
    )
    if not exact:
        raise FenceOrderStartSchemaError(
            "reservation, active fence, and order identity conflict"
        )


def _projection(
    reservation: DurableFenceAdmissionReservationV1,
    fence: ActiveFenceStateV1,
    identity: CrossLedgerOrderIdentityV1,
) -> dict:
    return {
        "schemaVersion": 1,
        "authorityKind": "fence-order-start-intent-v1",
        "realizationKind": "deterministic-mp4",
        "authorityId": identity.authority_id,
        "attemptId": identity.attempt_id,
        "reservationDigest": reservation.reservation.reservation_digest,
        "orderIdentityDigest": identity.order_identity_digest,
        "fenceRevision": fence.fence_revision,
        "fenceToken": fence.fence_token,
        "activeAttemptId": fence.active_attempt_id,
    }


def build_fence_order_start_intent_v1(
    reservation: object,
    fence: object,
    identity: object,
) -> FenceOrderStartIntentV1:
    """Build exact start bytes from validated non-authorizing evidence."""
    try:
        validate_durable_fence_admission_reservation_v1(reservation)
        retained_fence = _validated_fence(fence)
        retained_identity = _validated_identity(identity)
        _require_binding(reservation, retained_fence, retained_identity)
        row = _projection(reservation, retained_fence, retained_identity)
        digest = hashlib.sha256(_START_DOMAIN + canonical(row)).hexdigest()
        return parse_fence_order_start_intent_v1(
            canonical({**row, "startDigest": digest})
        )
    except FenceOrderStartSchemaError:
        raise
    except (RuntimeError, AttributeError, TypeError, ValueError) as exc:
        raise FenceOrderStartSchemaError(
            "fence order start inputs are invalid"
        ) from exc


def _require_envelope(row: dict) -> None:
    envelope = (
        type(row["schemaVersion"]),
        row["schemaVersion"],
        row["authorityKind"],
        row["realizationKind"],
    )
    expected = (
        int,
        1,
        "fence-order-start-intent-v1",
        "deterministic-mp4",
    )
    if envelope != expected:
        raise FenceOrderStartSchemaError(
            "fence order start envelope is invalid"
        )


def _start_digest(row: dict) -> str:
    projection = {key: row[key] for key in _KEYS - {"startDigest"}}
    expected = hashlib.sha256(
        _START_DOMAIN + canonical(projection)
    ).hexdigest()
    actual = wire.digest(row["startDigest"], "fence order start digest")
    if actual != expected:
        raise FenceOrderStartSchemaError("fence order start digest is stale")
    return actual


def _parsed(row: dict, raw: bytes) -> FenceOrderStartIntentV1:
    revision = row["fenceRevision"]
    if type(revision) is not int or revision <= 0:
        raise FenceOrderStartSchemaError("fence revision is invalid")
    attempt = wire.canonical_uuid(row["attemptId"], "start attempt ID")
    active = wire.canonical_uuid(
        row["activeAttemptId"], "start active attempt ID"
    )
    if attempt != active:
        raise FenceOrderStartSchemaError("start active attempt conflicts")
    return FenceOrderStartIntentV1(
        wire.authority(row["authorityId"]),
        attempt,
        wire.digest(row["reservationDigest"], "reservation digest"),
        wire.digest(row["orderIdentityDigest"], "order identity digest"),
        revision,
        wire.canonical_uuid(row["fenceToken"], "start fence token"),
        active,
        raw,
        _start_digest(row),
    )


def parse_fence_order_start_intent_v1(
    raw: object,
) -> FenceOrderStartIntentV1:
    """Parse canonical closed start-intent bytes and verify their digest."""
    try:
        row = wire.canonical_document(raw, "fence order start intent")
        wire.exact(row, _KEYS, "fence order start intent")
        _require_envelope(row)
        return _parsed(row, raw)
    except FenceOrderStartSchemaError:
        raise
    except (RuntimeError, KeyError, TypeError, ValueError) as exc:
        raise FenceOrderStartSchemaError(
            "fence order start intent is invalid"
        ) from exc


def validate_fence_order_start_intent_v1(value: object) -> None:
    """Reject direct construction, mutation, and custom equality values."""
    if type(value) is not FenceOrderStartIntentV1:
        raise FenceOrderStartSchemaError("start intent instance is invalid")
    if type(value.document_json) is not bytes:
        raise FenceOrderStartSchemaError("start intent bytes are invalid")
    parsed = parse_fence_order_start_intent_v1(value.document_json)
    if not same_wire_value(value, parsed):
        raise FenceOrderStartSchemaError("start intent identity is invalid")
