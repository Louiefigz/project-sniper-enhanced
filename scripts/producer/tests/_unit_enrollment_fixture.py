"""Self-consistent prospective enrollment fixtures for headless operations."""

from __future__ import annotations

from headless.operation_contract import (
    InitializeOperationV1,
    QualityPassOperationV1,
)
from headless.unit_enrollment_binding import (
    build_prospective_unit_enrollment_v1,
    project_lineage_digest_for_operation,
)
from headless.unit_enrollment_schema import (
    EnrollmentClockV1,
    EnrollmentOperationEligibilityV1,
    EnrollmentProjectIdentityV1,
    ProspectiveUnitEnrollmentV1,
)
from headless.unit_enrollment_types import UnitEnrollmentProposalV1

ENROLLMENT_KEY = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
OTHER_ENROLLMENT_KEY = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
OTHER_UNIT = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
ENROLLED_AT = "2026-07-19T12:34:55Z"
PROJECT_IDENTITY = "1" * 64
EXPERIMENT_IDENTITY = "2" * 64
ENROLLMENT_POLICY = "3" * 64


def enrollment_proposal(
    operation: object,
    enrollment_key: str = ENROLLMENT_KEY,
    unit_id: str | None = None,
) -> UnitEnrollmentProposalV1:
    """Return exact prospective identities matching one operation route."""
    if type(operation) is InitializeOperationV1:
        scope_kind, lanes, operation_kind = (
            "initialization-snapshot-v1",
            (),
            "initialize",
        )
    elif type(operation) is QualityPassOperationV1:
        scope_kind, lanes, operation_kind = (
            "declared-lanes-v1",
            ("graphicsTrack",),
            "quality-pass",
        )
    else:
        raise TypeError("test operation type is unsupported")
    eligibility = EnrollmentOperationEligibilityV1(
        operation_kind,
        scope_kind,
        lanes,
        "release-headless-v3",
        "build-headless-v3",
        operation.execution_policy_id,
    )
    project = EnrollmentProjectIdentityV1(
        PROJECT_IDENTITY,
        project_lineage_digest_for_operation(operation),
        EXPERIMENT_IDENTITY,
    )
    return UnitEnrollmentProposalV1(
        "authority-mp4-v1",
        enrollment_key,
        unit_id or operation.unit_id,
        EnrollmentClockV1("external-enrollment-clock-v1", 42, ENROLLED_AT),
        project,
        eligibility,
        ENROLLMENT_POLICY,
    )


def enrollment(
    operation: object,
    proposed: UnitEnrollmentProposalV1 | None = None,
) -> ProspectiveUnitEnrollmentV1:
    """Build one exact prospective enrollment."""
    return build_prospective_unit_enrollment_v1(
        proposed or enrollment_proposal(operation)
    )
