"""Typed proposal and non-authorizing result for V3 operation admission."""

from __future__ import annotations

from dataclasses import dataclass

from .operation_admission_schema import OperationAdmissionV3
from .operation_contract import HeadlessMp4OperationV1
from .repair_intent import ParentRefV1

OPERATION_ADMISSION_STATUS = (
    "STRUCTURAL_OPERATION_ADMISSION_V3_BOUND_NOT_EXECUTION_AUTHORIZED"
)


@dataclass(frozen=True)
class OperationAdmissionProposalV3:
    """Controller-proposed identities that must equal the retained admission."""

    authority_id: str
    idempotency_key: str
    attempt_id: str
    intended_child_generation_id: str
    unit_id: str
    expected_parent: ParentRefV1 | None
    first_submitted_at: str
    release_id: str
    build_id: str
    execution_policy_id: str


@dataclass(frozen=True)
class OperationAdmissionRequirementV3:
    """One authority deliberately unavailable from structural binding."""

    code: str
    required_proof: str


@dataclass(frozen=True)
class OperationAdmissionBindingV3:
    """Exact structural binding with all execution/publication gates closed."""

    status: str
    operation: HeadlessMp4OperationV1
    admission: OperationAdmissionV3
    proposed_child_generation_id: str
    closed_requirements: tuple[str, ...]
    unresolved_authority: tuple[OperationAdmissionRequirementV3, ...]
    exact_admission_bytes_reparsed: bool
    operation_artifact_bytes_bound: bool
    operation_domain_identity_bound: bool
    unit_parent_and_quality_bound: bool
    replay_identities_bound: bool
    child_identity_bound: bool
    release_build_policy_bound: bool
    durable_store_reobserved: bool
    runtime_verified: bool
    execution_authorized: bool
    publication_authorized: bool


CLOSED_OPERATION_ADMISSION_REQUIREMENTS = (
    "EXACT_V3_ADMISSION_BYTES",
    "OPERATION_ARTIFACT_SHA_SIZE_AND_DOMAIN_DIGEST",
    "UNIT_PARENT_AND_NESTED_QUALITY_IDENTITY",
    "REPLAY_ATTEMPT_AND_INTENDED_CHILD_IDENTITY",
    "AUTHORITY_RELEASE_BUILD_AND_EXECUTION_POLICY",
)


UNRESOLVED_OPERATION_ADMISSION_AUTHORITY = (
    OperationAdmissionRequirementV3(
        "UNIT_ENROLLMENT_AUTHORITY",
        "resolve this unit through the durable pre-enrollment ledger",
    ),
    OperationAdmissionRequirementV3(
        "DURABLE_STORE_AND_REPLAY_ARBITRATION",
        "load exact bytes and original clock from an atomic authority-owned V3 store",
    ),
    OperationAdmissionRequirementV3(
        "OPERATION_ARTIFACT_STORE_REOBSERVATION",
        "open the retained operation artifact and reobserve its exact bytes",
    ),
    OperationAdmissionRequirementV3(
        "RUNTIME_EXECUTION_AND_CHILD_SEAL",
        "attest runtime execution and bind the sealed child before fenced publication",
    ),
)
