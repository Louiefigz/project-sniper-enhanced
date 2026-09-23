"""Durably admit, then inspect, one exact headless quality-pass request."""

from __future__ import annotations

import dataclasses

from .admitted_quality_pass_composition_types import (
    ADMISSION_BINDING_REQUIREMENT,
    ADMITTED_COMPOSITION_STATUS,
    AdmittedQualityPassCompositionError,
    AdmittedQualityPassCompositionRequestV1,
    NonAuthorizingAdmittedQualityPassCompositionV1,
)
from .approved_parent_assembly_types import (
    RECURSIVE_LINEAGE_AND_GENESIS_ORIGIN,
)
from .operation_admission_binding import (
    OperationAdmissionBindingError,
    bind_operation_admission_v3,
)
from .operation_admission_schema import OperationAdmissionV3
from .operation_admission_store import (
    OperationAdmissionStoreError,
    persist_or_replay_operation_admission_v3,
)
from .operation_admission_store_types import (
    DurableOperationAdmissionV3,
    OperationAdmissionStoreRequestV3,
)
from .operation_admission_types import OperationAdmissionProposalV3
from .operation_contract import (
    QualityPassOperationV1,
    parse_headless_mp4_operation_v1,
)
from .quality_pass_composition_inspection import (
    inspect_quality_pass_composition,
)
from .quality_pass_composition_types import (
    CompositionAuthorityRequirementV1,
    NonAuthorizingQualityPassCompositionV1,
    QualityPassCompositionInspectionError,
    QualityPassCompositionInspectionRequestV1,
)
from .quality_receipt_json import same_typed_value

__all__ = (
    "ADMISSION_BINDING_REQUIREMENT",
    "ADMITTED_COMPOSITION_STATUS",
    "AdmittedQualityPassCompositionError",
    "AdmittedQualityPassCompositionRequestV1",
    "NonAuthorizingAdmittedQualityPassCompositionV1",
    "inspect_admitted_quality_pass_composition",
    "inspect_durable_admitted_quality_pass_composition",
    "require_admitted_render_start_authorized",
)

_ALWAYS_OPEN = (
    CompositionAuthorityRequirementV1(
        RECURSIVE_LINEAGE_AND_GENESIS_ORIGIN,
        "bind every selected assembly edge and the versioned genesis origin",
    ),
    CompositionAuthorityRequirementV1(
        "OPERATION_RUNTIME_EXECUTION_AND_CHILD_SEAL",
        "attest this operation's runtime execution and seal exact child bytes",
    ),
    CompositionAuthorityRequirementV1(
        "ACTIVE_FENCE_RECHECK",
        "recheck the durable attempt fence immediately before execution and publish",
    ),
    CompositionAuthorityRequirementV1(
        "FENCED_PUBLICATION_AND_TERMINAL_SEAL",
        "publish under the expected-parent fence and durably seal the outcome",
    ),
)


def _checked_request(
    value: object,
) -> AdmittedQualityPassCompositionRequestV1:
    if type(value) is not AdmittedQualityPassCompositionRequestV1:
        raise AdmittedQualityPassCompositionError(
            "admitted inspection is invalid"
        )
    valid = (
        type(value.inspection) is QualityPassCompositionInspectionRequestV1
        and type(value.admission) is OperationAdmissionV3
        and type(value.proposal) is OperationAdmissionProposalV3
    )
    if not valid:
        raise AdmittedQualityPassCompositionError(
            "admitted inputs are invalid"
        )
    return value


def _operation(
    request: AdmittedQualityPassCompositionRequestV1,
) -> QualityPassOperationV1:
    try:
        operation = parse_headless_mp4_operation_v1(
            request.inspection.operation_json
        )
    except RuntimeError as exc:
        raise AdmittedQualityPassCompositionError(
            "operation bytes are invalid"
        ) from exc
    if type(operation) is not QualityPassOperationV1:
        raise AdmittedQualityPassCompositionError(
            "operation is not quality-pass"
        )
    return operation


def _persist(
    request: AdmittedQualityPassCompositionRequestV1,
    operation: QualityPassOperationV1,
) -> DurableOperationAdmissionV3:
    try:
        bind_operation_admission_v3(
            operation, request.admission, request.proposal
        )
        store_request = OperationAdmissionStoreRequestV3(
            request.inspection.authority_root,
            operation,
            request.admission,
            request.proposal,
        )
        return persist_or_replay_operation_admission_v3(store_request)
    except (
        OperationAdmissionBindingError,
        OperationAdmissionStoreError,
    ) as exc:
        raise AdmittedQualityPassCompositionError(str(exc)) from exc


def _require_durable_match(
    durable: DurableOperationAdmissionV3,
    operation: QualityPassOperationV1,
    request: AdmittedQualityPassCompositionRequestV1,
) -> None:
    if type(durable) is not DurableOperationAdmissionV3:
        raise AdmittedQualityPassCompositionError(
            "durable admission type is invalid"
        )
    binding = durable.structural_binding
    matches = (
        durable.durable_admission_bytes_reobserved
        and durable.durable_operation_bytes_reobserved
        and durable.replay_arbitrated
        and same_typed_value(binding.operation, operation)
        and same_typed_value(binding.admission, request.admission)
        and binding.proposed_child_generation_id
        == request.proposal.intended_child_generation_id
        and not durable.unit_enrollment_verified
        and not durable.runtime_verified
        and not durable.execution_authorized
        and not durable.publication_authorized
    )
    if not matches:
        raise AdmittedQualityPassCompositionError(
            "durable admission recheck failed"
        )


def _requirements(
    composition: NonAuthorizingQualityPassCompositionV1,
) -> tuple[CompositionAuthorityRequirementV1, ...]:
    rows = (
        tuple(
            row
            for row in composition.unresolved_authority
            if row.code != ADMISSION_BINDING_REQUIREMENT
        )
        + _ALWAYS_OPEN
    )
    unique: dict[str, CompositionAuthorityRequirementV1] = {}
    for row in rows:
        unique.setdefault(row.code, row)
    return tuple(unique.values())


def _promote_diagnostics(
    composition: NonAuthorizingQualityPassCompositionV1,
    operation: QualityPassOperationV1,
) -> NonAuthorizingQualityPassCompositionV1:
    valid = (
        type(composition) is NonAuthorizingQualityPassCompositionV1
        and composition.operation_digest == operation.operation_digest
        and composition.unit_id == operation.unit_id
        and same_typed_value(
            composition.expected_parent, operation.expected_parent
        )
        and not composition.durable_admission_bound
        and not composition.parent_quality_runtime_reobserved
        and not composition.recursive_assembly_verified
        and not composition.genesis_origin_verified
        and not composition.operation_runtime_verified
        and not composition.fence_rechecked
        and not composition.execution_authorized
        and not composition.publication_authorized
    )
    if not valid:
        raise AdmittedQualityPassCompositionError(
            "composition diagnostics are invalid"
        )
    closed = composition.closed_checks + (ADMISSION_BINDING_REQUIREMENT,)
    return dataclasses.replace(
        composition,
        closed_checks=closed,
        unresolved_authority=_requirements(composition),
        durable_admission_bound=True,
    )


def _result(
    request: AdmittedQualityPassCompositionRequestV1,
    durable: DurableOperationAdmissionV3,
    composition: NonAuthorizingQualityPassCompositionV1,
) -> NonAuthorizingAdmittedQualityPassCompositionV1:
    return NonAuthorizingAdmittedQualityPassCompositionV1(
        status=ADMITTED_COMPOSITION_STATUS,
        operation_digest=composition.operation_digest,
        admission_digest=request.admission.admission_digest,
        request_identity_digest=request.admission.request_identity_digest,
        intended_child_generation_id=request.proposal.intended_child_generation_id,
        admission_created=durable.created,
        newly_closed_checks=(ADMISSION_BINDING_REQUIREMENT,),
        unresolved_authority=composition.unresolved_authority,
        composition=composition,
        exact_operation_bytes_admitted=True,
        durable_admission_bytes_reobserved=True,
        durable_operation_bytes_reobserved=True,
        proposed_child_bound=True,
        unit_enrollment_verified=False,
        recursive_assembly_verified=False,
        genesis_origin_verified=False,
        operation_runtime_verified=False,
        fence_rechecked=False,
        execution_authorized=False,
        publication_authorized=False,
    )


def _inspect_durable(
    request: AdmittedQualityPassCompositionRequestV1,
    operation: QualityPassOperationV1,
    durable: DurableOperationAdmissionV3,
) -> NonAuthorizingAdmittedQualityPassCompositionV1:
    _require_durable_match(durable, operation, request)
    try:
        inspected = inspect_quality_pass_composition(request.inspection)
    except QualityPassCompositionInspectionError as exc:
        raise AdmittedQualityPassCompositionError(str(exc)) from exc
    composition = _promote_diagnostics(inspected, operation)
    return _result(request, durable, composition)


def inspect_durable_admitted_quality_pass_composition(
    value: object, durable: object
) -> NonAuthorizingAdmittedQualityPassCompositionV1:
    """Inspect from an exact already-reobserved durable V3 admission."""
    request = _checked_request(value)
    operation = _operation(request)
    if type(durable) is not DurableOperationAdmissionV3:
        raise AdmittedQualityPassCompositionError(
            "durable admission type is invalid"
        )
    return _inspect_durable(request, operation, durable)


def inspect_admitted_quality_pass_composition(
    value: object,
) -> NonAuthorizingAdmittedQualityPassCompositionV1:
    """Check current sources before persistence, then reobserve diagnostics."""
    request = _checked_request(value)
    operation = _operation(request)
    require_current_composition(request)
    return _inspect_durable(request, operation, _persist(request, operation))


def require_current_composition(request: AdmittedQualityPassCompositionRequestV1) -> None:
    """Refuse invalid or retired parent sources before durable admission writes."""
    try:
        inspect_quality_pass_composition(request.inspection)
    except (RuntimeError, ValueError) as exc:
        raise AdmittedQualityPassCompositionError(str(exc)) from exc


def require_admitted_render_start_authorized(value: object) -> None:
    """Reject all admitted diagnostics, including forged authorization flags."""
    raise AdmittedQualityPassCompositionError(
        "admitted quality-pass composition is not render-start authority"
    )
