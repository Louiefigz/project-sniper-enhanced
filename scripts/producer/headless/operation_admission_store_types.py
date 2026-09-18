"""Non-authorizing results from the durable V3 operation-admission store."""

from __future__ import annotations

from dataclasses import dataclass

from .operation_admission_types import (
    CLOSED_OPERATION_ADMISSION_REQUIREMENTS,
    UNRESOLVED_OPERATION_ADMISSION_AUTHORITY,
    OperationAdmissionBindingV3,
    OperationAdmissionProposalV3,
    OperationAdmissionRequirementV3,
)
from .operation_contract import HeadlessMp4OperationV1
from .operation_admission_schema import OperationAdmissionV3

DURABLE_OPERATION_ADMISSION_STATUS = (
    "DURABLE_OPERATION_ADMISSION_V3_REOBSERVED_NOT_EXECUTION_AUTHORIZED"
)


@dataclass(frozen=True)
class OperationAdmissionStoreRequestV3:
    """Exact values submitted under one authority-owned durable lock."""

    authority_root: str
    operation: HeadlessMp4OperationV1
    admission: OperationAdmissionV3
    proposal: OperationAdmissionProposalV3


@dataclass(frozen=True)
class DurableOperationAdmissionV3:
    """Reobserved durable admission; never a render-start capability."""

    status: str
    created: bool
    record_id: str
    structural_binding: OperationAdmissionBindingV3
    closed_requirements: tuple[str, ...]
    unresolved_authority: tuple[OperationAdmissionRequirementV3, ...]
    durable_admission_bytes_reobserved: bool
    durable_operation_bytes_reobserved: bool
    replay_arbitrated: bool
    unit_enrollment_verified: bool
    runtime_verified: bool
    execution_authorized: bool
    publication_authorized: bool


STORE_CLOSED_REQUIREMENTS = CLOSED_OPERATION_ADMISSION_REQUIREMENTS + (
    "DURABLE_STORE_AND_REPLAY_ARBITRATION",
    "OPERATION_ARTIFACT_STORE_REOBSERVATION",
)


STORE_UNRESOLVED_AUTHORITY = tuple(
    requirement
    for requirement in UNRESOLVED_OPERATION_ADMISSION_AUTHORITY
    if requirement.code
    not in {
        "DURABLE_STORE_AND_REPLAY_ARBITRATION",
        "OPERATION_ARTIFACT_STORE_REOBSERVATION",
    }
)
