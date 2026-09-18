"""Build and structurally bind exact prospective unit-enrollment bytes."""

from __future__ import annotations

import hashlib

from .operation_contract import (
    InitializeOperationV1,
    QualityPassOperationV1,
    validate_headless_mp4_operation_v1,
)
from .operation_wire import canonical, parent_document
from .unit_enrollment_schema import (
    EnrollmentClockV1,
    EnrollmentOperationEligibilityV1,
    EnrollmentProjectIdentityV1,
    ProspectiveUnitEnrollmentV1,
    enrollment_identity_digest_v1,
    parse_prospective_unit_enrollment_v1,
    validate_prospective_unit_enrollment_v1,
)
from .unit_enrollment_types import (
    CLOSED_UNIT_ENROLLMENT_REQUIREMENTS,
    UNIT_ENROLLMENT_STATUS,
    UNRESOLVED_UNIT_ENROLLMENT_AUTHORITY,
    UnitEnrollmentBindingV1,
    UnitEnrollmentProposalV1,
)
from .wire_identity import same_wire_value

_LINEAGE_DOMAIN = b"sniper-enrolled-project-lineage-v1\0"


class UnitEnrollmentBindingError(RuntimeError):
    """Proposed enrollment and its exact canonical bytes disagree."""


def project_lineage_digest_for_operation(operation: object) -> str:
    """Derive the enrolled lineage anchor from exact operation authority."""
    try:
        validate_headless_mp4_operation_v1(operation)
    except RuntimeError as exc:
        raise UnitEnrollmentBindingError(
            "enrollment operation is invalid"
        ) from exc
    if type(operation) is InitializeOperationV1:
        identity = {
            "lineageKind": "initialization-snapshot-v1",
            "snapshotId": operation.snapshot.snapshot_id,
        }
    elif type(operation) is QualityPassOperationV1:
        identity = {
            "lineageKind": "approved-parent-v1",
            "parent": parent_document(operation.expected_parent),
        }
    else:  # pragma: no cover - guarded by the exact operation validator
        raise UnitEnrollmentBindingError("enrollment operation is invalid")
    return hashlib.sha256(_LINEAGE_DOMAIN + canonical(identity)).hexdigest()


def _document(proposal: UnitEnrollmentProposalV1) -> dict:
    clock, project, eligibility = (
        proposal.clock,
        proposal.project,
        proposal.eligibility,
    )
    return {
        "schemaVersion": 1,
        "authorityKind": "prospective-unit-enrollment-v1",
        "realizationKind": "deterministic-mp4",
        "authorityId": proposal.authority_id,
        "enrollmentKey": proposal.enrollment_key,
        "unitId": proposal.unit_id,
        "enrollmentClock": {
            "clockId": clock.clock_id,
            "sequence": clock.sequence,
            "observedAt": clock.observed_at,
        },
        "projectIdentity": {
            "projectIdentityDigest": project.project_identity_digest,
            "projectLineageDigest": project.project_lineage_digest,
            "experimentIdentityDigest": project.experiment_identity_digest,
        },
        "operationEligibility": {
            "operation": eligibility.operation,
            "scope": {
                "scopeKind": eligibility.scope_kind,
                "allowedLanes": list(eligibility.allowed_lanes),
            },
            "releaseId": eligibility.release_id,
            "buildId": eligibility.build_id,
            "executionPolicyId": eligibility.execution_policy_id,
        },
        "enrollmentPolicyDigest": proposal.enrollment_policy_digest,
    }


def _retained_proposal(
    enrollment: ProspectiveUnitEnrollmentV1,
) -> UnitEnrollmentProposalV1:
    return UnitEnrollmentProposalV1(
        enrollment.authority_id,
        enrollment.enrollment_key,
        enrollment.unit_id,
        enrollment.clock,
        enrollment.project,
        enrollment.eligibility,
        enrollment.enrollment_policy_digest,
    )


def build_prospective_unit_enrollment_v1(
    proposal: object,
) -> ProspectiveUnitEnrollmentV1:
    """Create exact enrollment bytes from pre-feedback proposed identities."""
    if type(proposal) is not UnitEnrollmentProposalV1:
        raise UnitEnrollmentBindingError("unit enrollment proposal is invalid")
    nested = (
        type(proposal.clock),
        type(proposal.project),
        type(proposal.eligibility),
    )
    valid = nested == (
        EnrollmentClockV1,
        EnrollmentProjectIdentityV1,
        EnrollmentOperationEligibilityV1,
    )
    if not valid:
        raise UnitEnrollmentBindingError("unit enrollment proposal is invalid")
    try:
        document = _document(proposal)
        document["enrollmentIdentityDigest"] = enrollment_identity_digest_v1(
            document
        )
        enrollment = parse_prospective_unit_enrollment_v1(canonical(document))
        if not same_wire_value(proposal, _retained_proposal(enrollment)):
            raise UnitEnrollmentBindingError(
                "unit enrollment proposal changed type"
            )
    except (RuntimeError, AttributeError, TypeError, ValueError) as exc:
        raise UnitEnrollmentBindingError(
            "unit enrollment proposal is invalid"
        ) from exc
    return enrollment


def bind_prospective_unit_enrollment_v1(
    enrollment: object,
) -> UnitEnrollmentBindingV1:
    """Bind exact enrollment bytes without claiming storage or execution authority."""
    try:
        validate_prospective_unit_enrollment_v1(enrollment)
    except RuntimeError as exc:
        raise UnitEnrollmentBindingError("unit enrollment is invalid") from exc
    return UnitEnrollmentBindingV1(
        UNIT_ENROLLMENT_STATUS,
        enrollment,
        CLOSED_UNIT_ENROLLMENT_REQUIREMENTS,
        UNRESOLVED_UNIT_ENROLLMENT_AUTHORITY,
        True,
        True,
        True,
        True,
        True,
        True,
        False,
        False,
        False,
        False,
    )


def require_unit_enrollment_execution_authorized(value: object) -> None:
    """Never treat structural enrollment as render-start authority."""
    if type(value) is not UnitEnrollmentBindingV1:
        raise UnitEnrollmentBindingError("unit enrollment binding is invalid")
    raise UnitEnrollmentBindingError(UNIT_ENROLLMENT_STATUS)
