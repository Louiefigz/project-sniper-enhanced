"""Enroll, durably admit, and inspect one headless quality-pass unit."""

from __future__ import annotations

from .admitted_quality_pass_composition import (
    inspect_durable_admitted_quality_pass_composition,
)
from .admitted_quality_pass_composition_types import (
    AdmittedQualityPassCompositionRequestV1,
    NonAuthorizingAdmittedQualityPassCompositionV1,
)
from .enrolled_admitted_quality_pass_types import (
    ENROLLED_ADMITTED_COMPOSITION_STATUS,
    EnrolledAdmittedQualityPassCompositionError,
    EnrolledAdmittedQualityPassCompositionRequestV1,
    NonAuthorizingEnrolledAdmittedQualityPassCompositionV1,
)
from .enrolled_admitted_quality_pass_promotion import (
    promote_enrolled_admitted_composition,
)
from .cross_ledger_order_protocol import (
    persist_or_replay_cross_ledger_ordered_admission_v1,
)
from .cross_ledger_order_types import (
    CrossLedgerOrderError,
    CrossLedgerOrderRequestV1,
    DurableCrossLedgerOrderedAdmissionV1,
)
from .operation_admission_binding import (
    OperationAdmissionBindingError,
    bind_operation_admission_v3,
)
from .operation_admission_store_types import OperationAdmissionStoreRequestV3
from .operation_contract import (
    QualityPassOperationV1,
    parse_headless_mp4_operation_v1,
)
from .unit_enrollment_admission_binding import (
    UnitEnrollmentAdmissionBindingError,
    bind_reobserved_unit_enrollment_to_admission_v1,
    require_prospective_enrollment_matches_admission_v1,
)
from .unit_enrollment_admission_types import (
    CROSS_LEDGER_PROSPECTIVE_ORDER,
    UNIT_ENROLLMENT_AUTHORITY,
    ReobservedUnitEnrollmentAdmissionBindingV1,
)
from .unit_enrollment_schema import ProspectiveUnitEnrollmentV1
from .unit_enrollment_order_promotion import (
    UnitEnrollmentOrderPromotionError,
    promote_unit_enrollment_with_order_receipt_v1,
)
from .unit_enrollment_store import (
    UnitEnrollmentStoreError,
    persist_or_replay_prospective_unit_enrollment_v1,
)
from .unit_enrollment_store_types import (
    DurableUnitEnrollmentV1,
    UnitEnrollmentStoreRequestV1,
)


def _checked_request(
    value: object,
) -> EnrolledAdmittedQualityPassCompositionRequestV1:
    if type(value) is not EnrolledAdmittedQualityPassCompositionRequestV1:
        raise EnrolledAdmittedQualityPassCompositionError(
            "enrolled admitted request is invalid"
        )
    valid = (
        type(value.enrollment) is ProspectiveUnitEnrollmentV1
        and type(value.admitted) is AdmittedQualityPassCompositionRequestV1
    )
    if not valid:
        raise EnrolledAdmittedQualityPassCompositionError(
            "enrolled admitted inputs are invalid"
        )
    return value


def _operation(
    request: EnrolledAdmittedQualityPassCompositionRequestV1,
) -> QualityPassOperationV1:
    try:
        operation = parse_headless_mp4_operation_v1(
            request.admitted.inspection.operation_json
        )
    except RuntimeError as exc:
        raise EnrolledAdmittedQualityPassCompositionError(
            "enrolled operation bytes are invalid"
        ) from exc
    if type(operation) is not QualityPassOperationV1:
        raise EnrolledAdmittedQualityPassCompositionError(
            "enrolled operation is not quality-pass"
        )
    return operation


def _persist_enrollment(
    request: EnrolledAdmittedQualityPassCompositionRequestV1,
) -> tuple[bool, DurableUnitEnrollmentV1]:
    root = request.admitted.inspection.authority_root
    try:
        durable = persist_or_replay_prospective_unit_enrollment_v1(
            UnitEnrollmentStoreRequestV1(root, request.enrollment)
        )
        return durable.created, durable
    except UnitEnrollmentStoreError as exc:
        raise EnrolledAdmittedQualityPassCompositionError(str(exc)) from exc


def _persist_ordered_admission(
    request: EnrolledAdmittedQualityPassCompositionRequestV1,
    operation: QualityPassOperationV1,
    enrolled: DurableUnitEnrollmentV1,
) -> DurableCrossLedgerOrderedAdmissionV1:
    admitted = request.admitted
    store_request = OperationAdmissionStoreRequestV3(
        admitted.inspection.authority_root,
        operation,
        admitted.admission,
        admitted.proposal,
    )
    try:
        return persist_or_replay_cross_ledger_ordered_admission_v1(
            CrossLedgerOrderRequestV1(
                admitted.inspection.authority_root,
                enrolled,
                store_request,
            )
        )
    except CrossLedgerOrderError as exc:
        raise EnrolledAdmittedQualityPassCompositionError(str(exc)) from exc


def _precheck(
    request: EnrolledAdmittedQualityPassCompositionRequestV1,
    operation: QualityPassOperationV1,
) -> None:
    try:
        bind_operation_admission_v3(
            operation, request.admitted.admission, request.admitted.proposal
        )
        require_prospective_enrollment_matches_admission_v1(
            request.enrollment, operation, request.admitted.admission
        )
    except (
        OperationAdmissionBindingError,
        UnitEnrollmentAdmissionBindingError,
    ) as exc:
        raise EnrolledAdmittedQualityPassCompositionError(str(exc)) from exc


def _bind(
    enrolled: DurableUnitEnrollmentV1,
    ordered: DurableCrossLedgerOrderedAdmissionV1,
) -> ReobservedUnitEnrollmentAdmissionBindingV1:
    try:
        binding = bind_reobserved_unit_enrollment_to_admission_v1(
            enrolled, ordered.admission
        )
        return promote_unit_enrollment_with_order_receipt_v1(binding, ordered)
    except (
        UnitEnrollmentAdmissionBindingError,
        UnitEnrollmentOrderPromotionError,
    ) as exc:
        raise EnrolledAdmittedQualityPassCompositionError(str(exc)) from exc


def _result(
    binding: ReobservedUnitEnrollmentAdmissionBindingV1,
    enrollment_created: bool,
    admission_created: bool,
    admitted: NonAuthorizingAdmittedQualityPassCompositionV1,
) -> NonAuthorizingEnrolledAdmittedQualityPassCompositionV1:
    return NonAuthorizingEnrolledAdmittedQualityPassCompositionV1(
        ENROLLED_ADMITTED_COMPOSITION_STATUS,
        binding.unit_id,
        binding.enrollment_digest,
        binding.enrollment_policy_digest,
        binding.project_identity_digest,
        binding.experiment_identity_digest,
        binding.admission_digest,
        admitted.request_identity_digest,
        admitted.intended_child_generation_id,
        enrollment_created,
        admission_created,
        (UNIT_ENROLLMENT_AUTHORITY, CROSS_LEDGER_PROSPECTIVE_ORDER),
        admitted.unresolved_authority,
        admitted,
        True,
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


def inspect_enrolled_admitted_quality_pass_composition(
    value: object,
) -> NonAuthorizingEnrolledAdmittedQualityPassCompositionV1:
    """Persist enrollment before admission, reobserve both, then inspect."""
    request = _checked_request(value)
    operation = _operation(request)
    _precheck(request, operation)
    enrollment_created, enrolled = _persist_enrollment(request)
    ordered = _persist_ordered_admission(request, operation, enrolled)
    binding = _bind(enrolled, ordered)
    try:
        inspected = inspect_durable_admitted_quality_pass_composition(
            request.admitted, ordered.admission
        )
    except RuntimeError as exc:
        raise EnrolledAdmittedQualityPassCompositionError(str(exc)) from exc
    promoted = promote_enrolled_admitted_composition(inspected, binding)
    return _result(
        binding,
        enrollment_created,
        ordered.admission_created,
        promoted,
    )


def require_enrolled_admitted_render_start_authorized(value: object) -> None:
    """Reject enrolled diagnostics, including forged authorization flags."""
    raise EnrolledAdmittedQualityPassCompositionError(
        "enrolled admitted composition is not render-start authority"
    )
