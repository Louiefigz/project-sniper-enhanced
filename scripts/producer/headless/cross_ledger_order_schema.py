"""Canonical, timestamp-free bytes for prospective cross-ledger ordering."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from . import quality_receipt_json as wire
from .operation_wire import canonical
from .wire_identity import same_wire_value

_ORDER_DOMAIN = b"sniper-cross-ledger-order-identity-v1\0"
_INTENT_DOMAIN = b"sniper-cross-ledger-order-intent-v1\0"
_RECEIPT_DOMAIN = b"sniper-cross-ledger-order-receipt-v1\0"
_REJECTION_DOMAIN = b"sniper-cross-ledger-order-rejection-v1\0"
_ENROLLMENT_RECORD_DOMAIN = b"sniper-unit-enrollment-record-v1\0"
_ADMISSION_RECORD_DOMAIN = b"sniper-operation-admission-record-v3\0"
_BASE_KEYS = frozenset(
    "admissionDigest admissionRecordId attemptId authorityId "
    "enrollmentDigest enrollmentKey enrollmentRecordId idempotencyKey "
    "intendedChildGenerationId orderIdentityDigest realizationKind "
    "schemaVersion state unitId".split()
)
_INTENT_KEYS = _BASE_KEYS | {"authorityKind"}
_RECEIPT_KEYS = _INTENT_KEYS | {"intentDigest"}
_REJECTION_KEYS = _INTENT_KEYS | {"reason"}
_IDENTITY_KEYS = frozenset(
    "admissionDigest admissionRecordId attemptId authorityId "
    "enrollmentDigest enrollmentKey enrollmentRecordId idempotencyKey "
    "intendedChildGenerationId unitId".split()
)
_REJECTION_REASONS = {
    "PREEXISTING_ADMISSION_WITHOUT_PRIOR_INTENT",
    "ADMISSION_REPLAYED_AFTER_FRESH_INTENT",
    "ADMISSION_UNIQUENESS_STOLEN_AFTER_PREPARED",
}


class CrossLedgerOrderSchemaError(RuntimeError):
    """Cross-ledger order bytes are noncanonical or internally inconsistent."""


@dataclass(frozen=True)
class CrossLedgerOrderIdentityV1:
    """Exact authority, unit, enrollment, and admission identities."""

    authority_id: str
    unit_id: str
    enrollment_key: str
    enrollment_record_id: str
    enrollment_digest: str
    idempotency_key: str
    attempt_id: str
    intended_child_generation_id: str
    admission_record_id: str
    admission_digest: str
    order_identity_digest: str


@dataclass(frozen=True)
class CrossLedgerOrderDocumentV1:
    """Parsed intent, receipt, or permanent-rejection document."""

    kind: str
    state: str
    identity: CrossLedgerOrderIdentityV1
    intent_digest: str | None
    reason: str | None
    document_json: bytes
    document_digest: str


def _projection(identity: CrossLedgerOrderIdentityV1, state: str) -> dict:
    return {
        "schemaVersion": 1,
        "realizationKind": "deterministic-mp4",
        "state": state,
        "authorityId": identity.authority_id,
        "unitId": identity.unit_id,
        "enrollmentKey": identity.enrollment_key,
        "enrollmentRecordId": identity.enrollment_record_id,
        "enrollmentDigest": identity.enrollment_digest,
        "idempotencyKey": identity.idempotency_key,
        "attemptId": identity.attempt_id,
        "intendedChildGenerationId": identity.intended_child_generation_id,
        "admissionRecordId": identity.admission_record_id,
        "admissionDigest": identity.admission_digest,
    }


def _record_id(domain: bytes, key: str) -> str:
    return hashlib.sha256(domain + key.encode("ascii")).hexdigest()


def _identity(row: dict) -> CrossLedgerOrderIdentityV1:
    projection = {key: row[key] for key in _IDENTITY_KEYS}
    expected = hashlib.sha256(
        _ORDER_DOMAIN + canonical(projection)
    ).hexdigest()
    actual = wire.digest(row["orderIdentityDigest"], "order identity digest")
    if actual != expected:
        raise CrossLedgerOrderSchemaError(
            "cross-ledger order identity is stale"
        )
    identity = CrossLedgerOrderIdentityV1(
        wire.authority(row["authorityId"]),
        wire.canonical_uuid(row["unitId"], "order unit ID"),
        wire.canonical_uuid(row["enrollmentKey"], "order enrollment key"),
        wire.digest(row["enrollmentRecordId"], "enrollment record ID"),
        wire.digest(row["enrollmentDigest"], "order enrollment digest"),
        wire.canonical_uuid(row["idempotencyKey"], "order idempotency key"),
        wire.canonical_uuid(row["attemptId"], "order attempt ID"),
        wire.canonical_uuid(
            row["intendedChildGenerationId"], "order child generation ID"
        ),
        wire.digest(row["admissionRecordId"], "admission record ID"),
        wire.digest(row["admissionDigest"], "order admission digest"),
        actual,
    )
    roles = {
        identity.unit_id,
        identity.enrollment_key,
        identity.idempotency_key,
    }
    records = identity.enrollment_record_id == _record_id(
        _ENROLLMENT_RECORD_DOMAIN, identity.enrollment_key
    ) and identity.admission_record_id == _record_id(
        _ADMISSION_RECORD_DOMAIN, identity.idempotency_key
    )
    if len(roles) != 3 or not records:
        raise CrossLedgerOrderSchemaError(
            "cross-ledger record identities are inconsistent"
        )
    return identity


def build_cross_ledger_order_identity_v1(
    values: tuple[str, ...],
) -> CrossLedgerOrderIdentityV1:
    """Build one identity from ten exact ordered string values."""
    if type(values) is not tuple or len(values) != 10:
        raise CrossLedgerOrderSchemaError("order identity values are invalid")
    provisional = CrossLedgerOrderIdentityV1(*values, "")
    row = _projection(provisional, "prepared")
    projected = {key: row[key] for key in _IDENTITY_KEYS}
    digest = hashlib.sha256(_ORDER_DOMAIN + canonical(projected)).hexdigest()
    return _identity({**row, "orderIdentityDigest": digest})


def _document(
    kind: str,
    state: str,
    identity: CrossLedgerOrderIdentityV1,
    extra: dict,
) -> bytes:
    row = _projection(identity, state)
    row.update(
        {
            "authorityKind": kind,
            "orderIdentityDigest": identity.order_identity_digest,
            **extra,
        }
    )
    return canonical(row)


def build_cross_ledger_order_intent_v1(
    identity: CrossLedgerOrderIdentityV1,
) -> bytes:
    """Encode the durable PREPARED marker written before admission."""
    return _document(
        "cross-ledger-prospective-order-intent-v1",
        "prepared",
        identity,
        {},
    )


def build_cross_ledger_order_receipt_v1(
    identity: CrossLedgerOrderIdentityV1, intent_digest: str
) -> bytes:
    """Encode the durable COMMITTED marker written after exact admission."""
    return _document(
        "cross-ledger-prospective-order-receipt-v1",
        "committed",
        identity,
        {"intentDigest": wire.digest(intent_digest, "order intent digest")},
    )


def build_cross_ledger_order_rejection_v1(
    identity: CrossLedgerOrderIdentityV1,
    reason: str = "PREEXISTING_ADMISSION_WITHOUT_PRIOR_INTENT",
) -> bytes:
    """Encode a permanent tombstone for an admission predating any intent."""
    if reason not in _REJECTION_REASONS:
        raise CrossLedgerOrderSchemaError("order rejection reason is invalid")
    return _document(
        "cross-ledger-prospective-order-rejection-v1",
        "rejected",
        identity,
        {"reason": reason},
    )


def _envelope(row: dict) -> tuple[str, str, frozenset[str]]:
    kind, state = row.get("authorityKind"), row.get("state")
    modes = {
        ("cross-ledger-prospective-order-intent-v1", "prepared"): _INTENT_KEYS,
        (
            "cross-ledger-prospective-order-receipt-v1",
            "committed",
        ): _RECEIPT_KEYS,
        (
            "cross-ledger-prospective-order-rejection-v1",
            "rejected",
        ): _REJECTION_KEYS,
    }
    expected = modes.get((kind, state))
    envelope = (type(row.get("schemaVersion")), row.get("schemaVersion"))
    if expected is None or envelope != (int, 1):
        raise CrossLedgerOrderSchemaError(
            "cross-ledger order envelope is invalid"
        )
    return kind, state, expected


def parse_cross_ledger_order_document_v1(
    raw: object,
) -> CrossLedgerOrderDocumentV1:
    """Parse one exact intent, receipt, or rejection document."""
    try:
        row = wire.canonical_document(raw, "cross-ledger order document")
        kind, state, keys = _envelope(row)
        wire.exact(row, frozenset(keys), "cross-ledger order document")
        identity = _identity(row)
        intent = row.get("intentDigest")
        reason = row.get("reason")
        if intent is not None:
            intent = wire.digest(intent, "order intent digest")
        if reason is not None and reason not in _REJECTION_REASONS:
            raise CrossLedgerOrderSchemaError(
                "order rejection reason is invalid"
            )
        domains = {
            "prepared": _INTENT_DOMAIN,
            "committed": _RECEIPT_DOMAIN,
            "rejected": _REJECTION_DOMAIN,
        }
        return CrossLedgerOrderDocumentV1(
            kind,
            state,
            identity,
            intent,
            reason,
            raw,
            hashlib.sha256(domains[state] + raw).hexdigest(),
        )
    except CrossLedgerOrderSchemaError:
        raise
    except (RuntimeError, TypeError, ValueError) as exc:
        raise CrossLedgerOrderSchemaError(
            "cross-ledger order document is invalid"
        ) from exc


def require_same_cross_ledger_identity_v1(
    actual: object, expected: CrossLedgerOrderIdentityV1
) -> None:
    """Reject role substitution and attacker-defined equality."""
    if not same_wire_value(actual, expected):
        raise CrossLedgerOrderSchemaError(
            "cross-ledger order identity conflicts"
        )
