"""Types for one work-disabled, fence-bound V3 admission transaction."""

from __future__ import annotations

from dataclasses import dataclass, field

from .active_fence_types import ActiveFenceOperationResultV1
from .cross_ledger_order_types import DurableCrossLedgerOrderedAdmissionV1
from .fence_admission_reservation_types import (
    DurableFenceAdmissionReservationV1,
)
from .fence_order_start_types import DurableFenceOrderStartV1
from .operation_admission_store_types import OperationAdmissionStoreRequestV3
from .unit_enrollment_schema import ProspectiveUnitEnrollmentV1
from .unit_enrollment_store_types import DurableUnitEnrollmentV1

FENCE_BOUND_ORDERED_ADMISSION_STATUS = (
    "FENCE_BOUND_ORDERED_ADMISSION_V1_WORK_DISABLED_NOT_AUTHORIZED"
)


class FenceBoundOrderedAdmissionError(RuntimeError):
    """The exact enrollment, reservation, fence, and admission do not agree."""


@dataclass(frozen=True)
class FenceBoundOrderedAdmissionRequestV1:
    """Prospective enrollment plus the exact V3 admission store request."""

    enrollment: ProspectiveUnitEnrollmentV1
    admission: OperationAdmissionStoreRequestV3


@dataclass(frozen=True)
class WorkDisabledFenceBoundOrderedAdmissionV1:
    """Durable admission evidence which deliberately cannot start work."""

    status: str
    enrollment: DurableUnitEnrollmentV1
    reservation: DurableFenceAdmissionReservationV1
    fence: ActiveFenceOperationResultV1
    start_intent: DurableFenceOrderStartV1
    ordered_admission: DurableCrossLedgerOrderedAdmissionV1
    enrollment_created: bool
    exact_reservation_reobserved: bool
    exact_start_intent_reobserved: bool
    admission_fence_reserved_before_order: bool
    publisher_mutex_held_during_order_resolution: bool
    order_created_under_publisher_mutex: bool
    fence_state_reobserved_after_order: bool
    work_disabled: bool = field(default=True, init=False)
    operation_runtime_verified: bool = field(default=False, init=False)
    fence_rechecked: bool = field(default=False, init=False)
    execution_authorized: bool = field(default=False, init=False)
    publication_authorized: bool = field(default=False, init=False)
    release_authorized: bool = field(default=False, init=False)
    work_launched: bool = field(default=False, init=False)
    current_advanced: bool = field(default=False, init=False)
