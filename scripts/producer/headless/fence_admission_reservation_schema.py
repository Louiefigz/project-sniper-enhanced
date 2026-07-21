"""Canonical non-authorizing binding for one fenced V3 admission."""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass

from . import quality_receipt_json as wire
from .cross_ledger_order_schema import (
    CrossLedgerOrderIdentityV1,
    build_cross_ledger_order_identity_v1,
    require_same_cross_ledger_identity_v1,
)
from .operation_admission_schema import (
    OperationAdmissionV3,
    validate_operation_admission_v3,
)
from .operation_admission_store_reader import (
    operation_admission_record_name_v3,
)
from .operation_wire import canonical
from .unit_enrollment_durable_validation import (
    validate_durable_unit_enrollment_v1,
)
from .unit_enrollment_store_types import DurableUnitEnrollmentV1
from .wire_identity import same_wire_value

_RESERVATION_DOMAIN = b"sniper-fence-admission-reservation-v1\0"
_KEYS = frozenset(
    "admissionDigest attemptId authorityId authorityKind enrollmentDigest "
    "enrollmentKey idempotencyKey intendedChildGenerationId "
    "orderIdentityDigest "
    "realizationKind requestIdentityDigest reservationDigest schemaVersion "
    "unitId".split()
)


class FenceAdmissionReservationSchemaError(RuntimeError):
    """The reservation is malformed or its exact identities disagree."""


@dataclass(frozen=True)
class FenceAdmissionReservationV1:
    """Immutable request binding; never execution or publication authority."""

    authority_id: str
    attempt_id: str
    idempotency_key: str
    enrollment_key: str
    request_identity_digest: str
    admission_digest: str
    unit_id: str
    intended_child_generation_id: str
    enrollment_digest: str
    order_identity_digest: str
    document_json: bytes
    reservation_digest: str


def _projection(
    identity: CrossLedgerOrderIdentityV1,
    admission: OperationAdmissionV3,
    enrollment_digest: str,
) -> dict:
    return {
        "schemaVersion": 1,
        "authorityKind": "fence-admission-reservation-v1",
        "realizationKind": "deterministic-mp4",
        "authorityId": identity.authority_id,
        "attemptId": identity.attempt_id,
        "idempotencyKey": identity.idempotency_key,
        "enrollmentKey": identity.enrollment_key,
        "requestIdentityDigest": admission.request_identity_digest,
        "admissionDigest": identity.admission_digest,
        "unitId": identity.unit_id,
        "intendedChildGenerationId": (identity.intended_child_generation_id),
        "enrollmentDigest": enrollment_digest,
        "orderIdentityDigest": identity.order_identity_digest,
    }


def _expected_identity(
    admission: OperationAdmissionV3,
    enrollment: DurableUnitEnrollmentV1,
) -> CrossLedgerOrderIdentityV1:
    retained = enrollment.structural_binding.enrollment
    values = (
        retained.authority_id,
        retained.unit_id,
        retained.enrollment_key,
        enrollment.record_id,
        retained.enrollment_digest,
        admission.idempotency_key,
        admission.attempt_id,
        admission.intended_child_generation_id,
        operation_admission_record_name_v3(admission.idempotency_key),
        admission.admission_digest,
    )
    return build_cross_ledger_order_identity_v1(values)


def _require_distinct_roles(
    identity: CrossLedgerOrderIdentityV1,
) -> None:
    roles = (
        identity.enrollment_key,
        identity.unit_id,
        identity.idempotency_key,
        identity.attempt_id,
        identity.intended_child_generation_id,
    )
    if len(set(roles)) != len(roles):
        raise FenceAdmissionReservationSchemaError(
            "fence reservation UUID roles alias"
        )


def _require_route(
    admission: OperationAdmissionV3,
    enrollment: DurableUnitEnrollmentV1,
) -> None:
    retained = enrollment.structural_binding.enrollment
    eligibility = retained.eligibility
    route = (
        retained.authority_id == admission.authority_id
        and retained.unit_id == admission.unit_id
        and eligibility.operation == admission.operation.kind
        and eligibility.release_id == admission.release_id
        and eligibility.build_id == admission.build_id
        and eligibility.execution_policy_id == admission.execution_policy_id
    )
    enrolled = dt.datetime.strptime(
        retained.clock.observed_at, "%Y-%m-%dT%H:%M:%SZ"
    )
    submitted = dt.datetime.strptime(
        admission.first_submitted_at, "%Y-%m-%dT%H:%M:%SZ"
    )
    if not route or enrolled > submitted:
        raise FenceAdmissionReservationSchemaError(
            "fence reservation admission route conflicts with enrollment"
        )


def build_fence_admission_reservation_v1(
    identity: object,
    admission: object,
    enrollment: object,
) -> FenceAdmissionReservationV1:
    """Build exact bytes from reparsed admission and durable enrollment."""
    try:
        validate_operation_admission_v3(admission)
        validate_durable_unit_enrollment_v1(enrollment)
        expected = _expected_identity(admission, enrollment)
        require_same_cross_ledger_identity_v1(identity, expected)
        _require_distinct_roles(expected)
        _require_route(admission, enrollment)
        retained = enrollment.structural_binding.enrollment
        row = _projection(expected, admission, retained.enrollment_digest)
        digest = hashlib.sha256(
            _RESERVATION_DOMAIN + canonical(row)
        ).hexdigest()
        return parse_fence_admission_reservation_v1(
            canonical({**row, "reservationDigest": digest})
        )
    except FenceAdmissionReservationSchemaError:
        raise
    except (RuntimeError, AttributeError, TypeError, ValueError) as exc:
        raise FenceAdmissionReservationSchemaError(
            "fence reservation identities are invalid"
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
        "fence-admission-reservation-v1",
        "deterministic-mp4",
    )
    if envelope != expected:
        raise FenceAdmissionReservationSchemaError(
            "fence reservation envelope is invalid"
        )


def _reservation_digest(row: dict) -> str:
    projection = {key: row[key] for key in _KEYS - {"reservationDigest"}}
    expected = hashlib.sha256(
        _RESERVATION_DOMAIN + canonical(projection)
    ).hexdigest()
    actual = wire.digest(row["reservationDigest"], "fence reservation digest")
    if actual != expected:
        raise FenceAdmissionReservationSchemaError(
            "fence reservation digest is stale"
        )
    return actual


def _reservation_identifiers(row: dict) -> tuple[str, ...]:
    identifiers = (
        wire.canonical_uuid(row["attemptId"], "reservation attempt ID"),
        wire.canonical_uuid(
            row["idempotencyKey"], "reservation idempotency key"
        ),
        wire.canonical_uuid(
            row["enrollmentKey"], "reservation enrollment key"
        ),
        wire.canonical_uuid(row["unitId"], "reservation unit ID"),
        wire.canonical_uuid(
            row["intendedChildGenerationId"],
            "reservation child generation ID",
        ),
    )
    if len(set(identifiers)) != len(identifiers):
        raise FenceAdmissionReservationSchemaError(
            "fence reservation UUID roles alias"
        )
    return identifiers


def _parsed_reservation(row: dict, raw: bytes) -> FenceAdmissionReservationV1:
    identifiers = _reservation_identifiers(row)
    digest = _reservation_digest(row)
    return FenceAdmissionReservationV1(
        wire.authority(row["authorityId"]),
        identifiers[0],
        identifiers[1],
        identifiers[2],
        wire.digest(
            row["requestIdentityDigest"], "reservation request digest"
        ),
        wire.digest(row["admissionDigest"], "reservation admission digest"),
        identifiers[3],
        identifiers[4],
        wire.digest(row["enrollmentDigest"], "reservation enrollment digest"),
        wire.digest(row["orderIdentityDigest"], "reservation order digest"),
        raw,
        digest,
    )


def parse_fence_admission_reservation_v1(
    raw: object,
) -> FenceAdmissionReservationV1:
    """Parse canonical closed reservation bytes and verify their digest."""
    try:
        row = wire.canonical_document(raw, "fence admission reservation")
        wire.exact(row, _KEYS, "fence admission reservation")
        _require_envelope(row)
        return _parsed_reservation(row, raw)
    except FenceAdmissionReservationSchemaError:
        raise
    except (RuntimeError, KeyError, TypeError, ValueError) as exc:
        raise FenceAdmissionReservationSchemaError(
            "fence admission reservation is invalid"
        ) from exc


def validate_fence_admission_reservation_v1(value: object) -> None:
    """Reject mutation, direct construction, and custom equality objects."""
    if type(value) is not FenceAdmissionReservationV1:
        raise FenceAdmissionReservationSchemaError(
            "fence admission reservation instance is invalid"
        )
    if type(value.document_json) is not bytes:
        raise FenceAdmissionReservationSchemaError(
            "fence admission reservation bytes are invalid"
        )
    parsed = parse_fence_admission_reservation_v1(value.document_json)
    if not same_wire_value(value, parsed):
        raise FenceAdmissionReservationSchemaError(
            "fence admission reservation identity is invalid"
        )
