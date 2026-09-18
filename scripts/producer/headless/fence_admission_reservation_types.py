"""Inputs and non-authorizing results for fence-admission reservations."""

from __future__ import annotations

from dataclasses import dataclass

from .active_fence_lock import ActiveFenceLockV1
from .cross_ledger_order_schema import CrossLedgerOrderIdentityV1
from .fence_admission_reservation_schema import FenceAdmissionReservationV1
from .operation_admission_schema import OperationAdmissionV3
from .unit_enrollment_store_types import DurableUnitEnrollmentV1

FENCE_ADMISSION_RESERVATION_STATUS = (
    "DURABLE_FENCE_ADMISSION_RESERVATION_V1_NOT_AUTHORIZED"
)
FENCE_ADMISSION_RESERVATION_STORE_NAME = "fence-admission-reservations-v1"
MAX_FENCE_ADMISSION_RESERVATION_RECORDS = 4096
MAX_FENCE_ADMISSION_RESERVATION_BYTES = 16_384


class FenceAdmissionReservationError(RuntimeError):
    """The exact fence-admission reservation cannot be proven durable."""


class FenceAdmissionReservationConflictV1(FenceAdmissionReservationError):
    """An attempt or UUID role is already bound to another reservation."""


@dataclass(frozen=True)
class FenceAdmissionReservationRequestV1:
    """Exact inputs plus the live outer publisher-lock capability."""

    lock: ActiveFenceLockV1
    identity: CrossLedgerOrderIdentityV1
    admission: OperationAdmissionV3
    enrollment: DurableUnitEnrollmentV1


@dataclass(frozen=True)
class DurableFenceAdmissionReservationV1:
    """Reobserved immutable binding which grants no work authority."""

    status: str
    created: bool
    record_name: str
    reservation: FenceAdmissionReservationV1
    reservation_bytes_reobserved: bool
    replay_arbitrated: bool
    execution_authorized: bool
    publication_authorized: bool
