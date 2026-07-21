"""Exact canonical contract for prospective headless MP4 unit enrollment."""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from dataclasses import dataclass

from . import quality_receipt_json as wire
from .operation_wire import canonical

UnitEnrollmentSchemaError = wire.QualityReceiptSchemaError

_ENROLLMENT_DOMAIN = b"sniper-prospective-unit-enrollment-v1\0"
_IDENTITY_DOMAIN = b"sniper-unit-enrollment-identity-v1\0"
_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")
_LANE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}")
_TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z"
)
_TOP_KEYS = frozenset(
    "authorityId authorityKind enrollmentClock enrollmentIdentityDigest "
    "enrollmentKey enrollmentPolicyDigest operationEligibility projectIdentity "
    "realizationKind schemaVersion unitId".split()
)
_CLOCK_KEYS = frozenset("clockId observedAt sequence".split())
_PROJECT_KEYS = frozenset(
    "experimentIdentityDigest projectIdentityDigest projectLineageDigest".split()
)
_ELIGIBILITY_KEYS = frozenset(
    "buildId executionPolicyId operation releaseId scope".split()
)
_SCOPE_KEYS = frozenset("allowedLanes scopeKind".split())


@dataclass(frozen=True)
class EnrollmentClockV1:
    """Externally assigned clock position captured before controller submission."""

    clock_id: str
    sequence: int
    observed_at: str


@dataclass(frozen=True)
class EnrollmentProjectIdentityV1:
    """Opaque immutable project, lineage, and experiment identities."""

    project_identity_digest: str
    project_lineage_digest: str
    experiment_identity_digest: str


@dataclass(frozen=True)
class EnrollmentOperationEligibilityV1:
    """One declared operation route and its pre-feedback project scope."""

    operation: str
    scope_kind: str
    allowed_lanes: tuple[str, ...]
    release_id: str
    build_id: str
    execution_policy_id: str


@dataclass(frozen=True)
class ProspectiveUnitEnrollmentV1:
    """Immutable enrollment bytes; never feedback, outcome, or render authority."""

    authority_id: str
    enrollment_key: str
    unit_id: str
    clock: EnrollmentClockV1
    project: EnrollmentProjectIdentityV1
    eligibility: EnrollmentOperationEligibilityV1
    enrollment_policy_digest: str
    enrollment_identity_digest: str
    document_json: bytes
    enrollment_digest: str


def _identity(value: object, label: str) -> str:
    if type(value) is not str or not _IDENTITY.fullmatch(value):
        raise UnitEnrollmentSchemaError(f"{label} is invalid")
    return value


def _timestamp(value: object) -> str:
    if type(value) is not str or not _TIMESTAMP.fullmatch(value):
        raise UnitEnrollmentSchemaError(
            "enrollment clock is not canonical UTC"
        )
    try:
        parsed = dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise UnitEnrollmentSchemaError(
            "enrollment clock is not canonical UTC"
        ) from exc
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise UnitEnrollmentSchemaError(
            "enrollment clock is not canonical UTC"
        )
    return value


def _clock(value: object) -> EnrollmentClockV1:
    row = wire.exact(value, _CLOCK_KEYS, "unit enrollment clock")
    sequence = row["sequence"]
    if type(sequence) is not int or sequence < 0:
        raise UnitEnrollmentSchemaError("enrollment clock sequence is invalid")
    return EnrollmentClockV1(
        _identity(row["clockId"], "enrollment clock ID"),
        sequence,
        _timestamp(row["observedAt"]),
    )


def _project(value: object) -> EnrollmentProjectIdentityV1:
    row = wire.exact(value, _PROJECT_KEYS, "unit enrollment project identity")
    return EnrollmentProjectIdentityV1(
        wire.digest(row["projectIdentityDigest"], "project identity digest"),
        wire.digest(row["projectLineageDigest"], "project lineage digest"),
        wire.digest(
            row["experimentIdentityDigest"], "experiment identity digest"
        ),
    )


def _lanes(value: object) -> tuple[str, ...]:
    if type(value) is not list or len(value) > 16:
        raise UnitEnrollmentSchemaError(
            "declared enrollment lanes are invalid"
        )
    lanes = tuple(value)
    valid = (
        all(
            type(lane) is str and bool(_LANE.fullmatch(lane)) for lane in lanes
        )
        and tuple(sorted(lanes)) == lanes
        and len(set(lanes)) == len(lanes)
    )
    if not valid:
        raise UnitEnrollmentSchemaError(
            "declared enrollment lanes are invalid"
        )
    return lanes


def _eligibility(value: object) -> EnrollmentOperationEligibilityV1:
    row = wire.exact(value, _ELIGIBILITY_KEYS, "unit enrollment eligibility")
    scope = wire.exact(row["scope"], _SCOPE_KEYS, "unit enrollment scope")
    operation, scope_kind = row["operation"], scope["scopeKind"]
    lanes = _lanes(scope["allowedLanes"])
    mode = (operation, scope_kind, lanes)
    valid = mode == ("initialize", "initialization-snapshot-v1", ()) or (
        operation == "quality-pass"
        and scope_kind == "declared-lanes-v1"
        and bool(lanes)
    )
    if not valid:
        raise UnitEnrollmentSchemaError(
            "unit enrollment scope is inconsistent"
        )
    return EnrollmentOperationEligibilityV1(
        operation,
        scope_kind,
        lanes,
        _identity(row["releaseId"], "enrollment release ID"),
        _identity(row["buildId"], "enrollment build ID"),
        wire.digest(
            row["executionPolicyId"], "enrollment execution policy ID"
        ),
    )


def _identity_digest(document: dict) -> str:
    projection = {
        key: document[key] for key in _TOP_KEYS - {"enrollmentIdentityDigest"}
    }
    return hashlib.sha256(_IDENTITY_DOMAIN + canonical(projection)).hexdigest()


def _parse(document: dict, raw: bytes) -> ProspectiveUnitEnrollmentV1:
    wire.exact(document, _TOP_KEYS, "prospective unit enrollment V1")
    envelope = (
        type(document["schemaVersion"]),
        document["schemaVersion"],
        document["authorityKind"],
        document["realizationKind"],
    )
    if envelope != (
        int,
        1,
        "prospective-unit-enrollment-v1",
        "deterministic-mp4",
    ):
        raise UnitEnrollmentSchemaError("unit enrollment envelope is invalid")
    expected = _identity_digest(document)
    actual = wire.digest(
        document["enrollmentIdentityDigest"], "enrollment identity digest"
    )
    if actual != expected:
        raise UnitEnrollmentSchemaError("unit enrollment identity is stale")
    enrollment_key = wire.canonical_uuid(
        document["enrollmentKey"], "enrollment key"
    )
    unit_id = wire.canonical_uuid(document["unitId"], "enrollment unit ID")
    if enrollment_key == unit_id:
        raise UnitEnrollmentSchemaError("enrollment key aliases unit ID")
    return ProspectiveUnitEnrollmentV1(
        wire.authority(document["authorityId"]),
        enrollment_key,
        unit_id,
        _clock(document["enrollmentClock"]),
        _project(document["projectIdentity"]),
        _eligibility(document["operationEligibility"]),
        wire.digest(
            document["enrollmentPolicyDigest"], "enrollment policy digest"
        ),
        actual,
        raw,
        hashlib.sha256(_ENROLLMENT_DOMAIN + raw).hexdigest(),
    )


def parse_prospective_unit_enrollment_v1(
    raw: object,
) -> ProspectiveUnitEnrollmentV1:
    """Parse exact canonical enrollment bytes with no feedback or outcome fields."""
    document = wire.canonical_document(raw, "prospective unit enrollment V1")
    return _parse(document, raw)


def validate_prospective_unit_enrollment_v1(value: object) -> None:
    """Reject direct construction, mutation, and attacker-defined equality."""
    if type(value) is not ProspectiveUnitEnrollmentV1:
        raise UnitEnrollmentSchemaError("unit enrollment instance is invalid")
    if type(value.document_json) is not bytes:
        raise UnitEnrollmentSchemaError("unit enrollment bytes are invalid")
    parsed = parse_prospective_unit_enrollment_v1(value.document_json)
    if not wire.same_typed_value(value, parsed):
        raise UnitEnrollmentSchemaError("unit enrollment identity is invalid")


def enrollment_identity_digest_v1(document: dict) -> str:
    """Derive the exact closed enrollment identity before adding its digest."""
    wire.exact(
        document,
        _TOP_KEYS - {"enrollmentIdentityDigest"},
        "unit enrollment proposal",
    )
    return _identity_digest(document)
