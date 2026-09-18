"""Inputs and non-authorizing results for fenced order-start intents."""

from __future__ import annotations

from dataclasses import dataclass

from .active_fence_lock import ActiveFenceLockV1
from .active_fence_types import ActiveFenceStateV1
from .cross_ledger_order_lock import CrossLedgerOrderLockV1
from .cross_ledger_order_schema import CrossLedgerOrderIdentityV1
from .fence_admission_reservation_types import (
    DurableFenceAdmissionReservationV1,
)

FENCE_ORDER_START_STATUS = "DURABLE_FENCE_ORDER_START_V1_NOT_AUTHORIZED"
FENCE_ORDER_START_STORE_NAME = "fence-order-start-intents-v1"
MAX_FENCE_ORDER_START_RECORDS = 4096
MAX_FENCE_ORDER_START_BYTES = 16_384


class FenceOrderStartError(RuntimeError):
    """The fence-before-order causal edge cannot be durably proven."""


class FenceOrderStartConflictV1(FenceOrderStartError):
    """An attempt is already bound to another start identity."""


@dataclass(frozen=True)
class PublishCrossLedgerLockPairV1:
    """Exact live publisher parent and its descended cross-ledger lock."""

    publish_lock: ActiveFenceLockV1
    cross_lock: CrossLedgerOrderLockV1


@dataclass(frozen=True)
class FenceOrderStartIntentV1:
    """Canonical evidence that an exact active fence preceded order start."""

    authority_id: str
    attempt_id: str
    reservation_digest: str
    order_identity_digest: str
    fence_revision: int
    fence_token: str
    active_attempt_id: str
    document_json: bytes
    start_digest: str


@dataclass(frozen=True)
class FenceOrderStartRequestV1:
    """One exact start identity submitted under both required live locks."""

    locks: PublishCrossLedgerLockPairV1
    reservation: DurableFenceAdmissionReservationV1
    fence: ActiveFenceStateV1
    order_identity: CrossLedgerOrderIdentityV1


@dataclass(frozen=True)
class DurableFenceOrderStartV1:
    """Reobserved causal marker which grants no work authority."""

    status: str
    created: bool
    record_name: str
    intent: FenceOrderStartIntentV1
    reservation_bytes_reobserved: bool
    active_fence_reobserved: bool
    publish_cross_lock_pair_verified: bool
    intent_bytes_reobserved: bool
    replay_arbitrated: bool
    execution_authorized: bool
    publication_authorized: bool
