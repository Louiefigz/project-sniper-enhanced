"""Work-disabled enrollment through one fence-bound ordered V3 admission."""

from __future__ import annotations

from .active_fence_lock import (
    ActiveFenceLockError,
    ActiveFenceLockV1,
    locked_existing_publish_mutex_v1,
)
from .active_fence_types import ActiveFenceError
from .cross_ledger_order_lock import (
    CrossLedgerOrderLockError,
    locked_cross_ledger_order_under_publish_mutex_v1,
)
from .cross_ledger_order_types import (
    CrossLedgerOrderError,
    CrossLedgerOrderRequestV1,
)
from .fence_admission_reservation_types import FenceAdmissionReservationError
from .fence_bound_ordered_admission_transaction import (
    FenceBoundAdmissionEvidenceV1,
    admit_fence_bound_ordered_under_locks_v1,
)
from .fence_bound_ordered_admission_types import (
    FENCE_BOUND_ORDERED_ADMISSION_STATUS,
    FenceBoundOrderedAdmissionError,
    FenceBoundOrderedAdmissionRequestV1,
    WorkDisabledFenceBoundOrderedAdmissionV1,
)
from .fence_bound_ordered_admission_validation import (
    FenceBoundOrderedAdmissionValidationError,
    validate_fence_bound_ordered_admission_v1,
)
from .fence_order_start_types import FenceOrderStartError
from .operation_admission_store_types import OperationAdmissionStoreRequestV3
from .unit_enrollment_admission_binding import (
    UnitEnrollmentAdmissionBindingError,
    require_prospective_enrollment_matches_admission_v1,
)
from .unit_enrollment_schema import ProspectiveUnitEnrollmentV1
from .unit_enrollment_store import (
    UnitEnrollmentStoreError,
    persist_or_replay_prospective_unit_enrollment_v1,
)
from .unit_enrollment_store_types import UnitEnrollmentStoreRequestV1
from .unit_enrollment_store_types import DurableUnitEnrollmentV1

_INTERNAL_ERRORS = (
    ActiveFenceError,
    ActiveFenceLockError,
    CrossLedgerOrderError,
    CrossLedgerOrderLockError,
    FenceAdmissionReservationError,
    FenceBoundOrderedAdmissionValidationError,
    FenceOrderStartError,
    UnitEnrollmentAdmissionBindingError,
    UnitEnrollmentStoreError,
)


def _checked_request(
    value: object,
) -> FenceBoundOrderedAdmissionRequestV1:
    if type(value) is not FenceBoundOrderedAdmissionRequestV1:
        raise FenceBoundOrderedAdmissionError(
            "fence-bound admission request is invalid"
        )
    if type(value.enrollment) is not ProspectiveUnitEnrollmentV1:
        raise FenceBoundOrderedAdmissionError(
            "fence-bound enrollment is invalid"
        )
    if type(value.admission) is not OperationAdmissionStoreRequestV3:
        raise FenceBoundOrderedAdmissionError(
            "fence-bound V3 admission request is invalid"
        )
    try:
        require_prospective_enrollment_matches_admission_v1(
            value.enrollment,
            value.admission.operation,
            value.admission.admission,
        )
    except UnitEnrollmentAdmissionBindingError as exc:
        raise FenceBoundOrderedAdmissionError(str(exc)) from exc
    return value


def _persist_enrollment(
    request: FenceBoundOrderedAdmissionRequestV1,
) -> DurableUnitEnrollmentV1:
    return persist_or_replay_prospective_unit_enrollment_v1(
        UnitEnrollmentStoreRequestV1(
            request.admission.authority_root, request.enrollment
        )
    )


def _compose(
    request: FenceBoundOrderedAdmissionRequestV1,
) -> tuple[DurableUnitEnrollmentV1, FenceBoundAdmissionEvidenceV1]:
    root = request.admission.authority_root
    enrollment = _persist_enrollment(request)
    cross_request = CrossLedgerOrderRequestV1(
        root, enrollment, request.admission
    )
    with locked_existing_publish_mutex_v1(root) as publish_lock:
        with locked_cross_ledger_order_under_publish_mutex_v1(
            publish_lock
        ) as cross_lock:
            values = admit_fence_bound_ordered_under_locks_v1(
                publish_lock, cross_lock, cross_request
            )
    return enrollment, values


def _result(
    enrollment: DurableUnitEnrollmentV1,
    evidence: FenceBoundAdmissionEvidenceV1,
) -> WorkDisabledFenceBoundOrderedAdmissionV1:
    result = WorkDisabledFenceBoundOrderedAdmissionV1(
        FENCE_BOUND_ORDERED_ADMISSION_STATUS,
        enrollment,
        evidence.reservation,
        evidence.fence,
        evidence.start_intent,
        evidence.ordered,
        enrollment.created,
        True,
        True,
        True,
        True,
        evidence.ordered.order_created,
        True,
    )
    validate_fence_bound_ordered_admission_v1(result)
    return result


def admit_fence_bound_ordered_work_disabled_v1(
    value: object,
) -> WorkDisabledFenceBoundOrderedAdmissionV1:
    """Persist exact admission under one fence; never launch or publish."""
    request = _checked_request(value)
    try:
        enrollment, evidence = _compose(request)
        result = _result(enrollment, evidence)
    except FenceBoundOrderedAdmissionError:
        raise
    except _INTERNAL_ERRORS as exc:
        raise FenceBoundOrderedAdmissionError(str(exc)) from exc
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        raise FenceBoundOrderedAdmissionError(
            "fence-bound ordered admission failed"
        ) from exc
    return result


def require_fence_bound_ordered_execution_authorized(value: object) -> None:
    """Reject this deliberately work-disabled structural result."""
    raise FenceBoundOrderedAdmissionError(
        "fence-bound ordered admission is not execution authority"
    )
