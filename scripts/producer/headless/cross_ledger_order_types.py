"""Non-authorizing inputs and results for durable cross-ledger ordering."""

from __future__ import annotations

from dataclasses import dataclass

from .cross_ledger_order_schema import CrossLedgerOrderDocumentV1
from .operation_admission_store_types import (
    DurableOperationAdmissionV3,
    OperationAdmissionStoreRequestV3,
)
from .unit_enrollment_store_types import DurableUnitEnrollmentV1

CROSS_LEDGER_ORDER_COMMITTED_STATUS = (
    "DURABLE_CROSS_LEDGER_PROSPECTIVE_ORDER_COMMITTED_NOT_EXECUTION_AUTHORIZED"
)
CROSS_LEDGER_ORDER_REPLAY_STATUS = (
    "DURABLE_CROSS_LEDGER_PROSPECTIVE_ORDER_REPLAYED_NOT_EXECUTION_AUTHORIZED"
)


class CrossLedgerOrderError(RuntimeError):
    """The enrollment-to-admission order cannot be durably proven."""


class CrossLedgerOrderPermanentRejectionV1(CrossLedgerOrderError):
    """This unit is tombstoned because admission existed before intent."""


class CrossLedgerOrderConflictV1(CrossLedgerOrderError):
    """A unit order key was reused with different exact identity."""


@dataclass(frozen=True)
class CrossLedgerOrderStateV1:
    """One safely reobserved order state under the shared outer lock."""

    state: str
    name: str
    intent: CrossLedgerOrderDocumentV1 | None
    receipt: CrossLedgerOrderDocumentV1 | None
    rejection: CrossLedgerOrderDocumentV1 | None


@dataclass(frozen=True)
class CrossLedgerOrderRequestV1:
    """Reobserved enrollment plus the exact V3 admission request."""

    authority_root: str
    enrollment: DurableUnitEnrollmentV1
    admission: OperationAdmissionStoreRequestV3


@dataclass(frozen=True)
class DurableCrossLedgerOrderedAdmissionV1:
    """Path-free exact order receipt plus non-authorizing durable admission."""

    status: str
    state: str
    order_created: bool
    admission_created: bool
    intent: CrossLedgerOrderDocumentV1
    receipt: CrossLedgerOrderDocumentV1
    enrollment: DurableUnitEnrollmentV1
    admission: DurableOperationAdmissionV3
    enrollment_bytes_reobserved: bool
    intent_committed_before_admission: bool
    exact_admission_reobserved_before_receipt: bool
    receipt_bytes_reobserved: bool
    replay_arbitrated: bool
    cross_ledger_order_receipt_verified: bool
    runtime_verified: bool
    fence_rechecked: bool
    execution_authorized: bool
    publication_authorized: bool
