"""Typed result for durable-admission quality-pass composition inspection."""

from __future__ import annotations

from dataclasses import dataclass

from .operation_admission_schema import OperationAdmissionV3
from .operation_admission_types import OperationAdmissionProposalV3
from .quality_pass_composition_types import (
    CompositionAuthorityRequirementV1,
    NonAuthorizingQualityPassCompositionV1,
    QualityPassCompositionInspectionRequestV1,
)

ADMITTED_COMPOSITION_STATUS = (
    "DURABLE_ADMISSION_BOUND_COMPOSITION_INSPECTED_NOT_EXECUTION_AUTHORIZED"
)
ADMISSION_BINDING_REQUIREMENT = "OPERATION_DURABLE_ADMISSION_AND_CHILD_BINDING"


class AdmittedQualityPassCompositionError(RuntimeError):
    """Admission and composition inspection did not form one exact request."""


@dataclass(frozen=True)
class AdmittedQualityPassCompositionRequestV1:
    """Exact admission inputs and the lifetime-owning composition request."""

    inspection: QualityPassCompositionInspectionRequestV1
    admission: OperationAdmissionV3
    proposal: OperationAdmissionProposalV3


@dataclass(frozen=True)
class NonAuthorizingAdmittedQualityPassCompositionV1:
    """Capability-free diagnostics after exact durable admission and inspection."""

    status: str
    operation_digest: str
    admission_digest: str
    request_identity_digest: str
    intended_child_generation_id: str
    admission_created: bool
    newly_closed_checks: tuple[str, ...]
    unresolved_authority: tuple[CompositionAuthorityRequirementV1, ...]
    composition: NonAuthorizingQualityPassCompositionV1
    exact_operation_bytes_admitted: bool
    durable_admission_bytes_reobserved: bool
    durable_operation_bytes_reobserved: bool
    proposed_child_bound: bool
    unit_enrollment_verified: bool
    recursive_assembly_verified: bool
    genesis_origin_verified: bool
    operation_runtime_verified: bool
    fence_rechecked: bool
    execution_authorized: bool
    publication_authorized: bool
