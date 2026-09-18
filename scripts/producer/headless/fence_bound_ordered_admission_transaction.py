"""Exact FENCE-before-PREPARED transaction under caller-held locks."""

from __future__ import annotations

from dataclasses import dataclass

from .active_fence_lock import ActiveFenceLockV1
from .active_fence_protocol import (
    reobserve_active_generation_fence_under_lock_v1,
    reobserve_exact_active_generation_fence_under_lock_v1,
    reserve_active_generation_fence_under_lock_v1,
)
from .active_fence_types import (
    ActiveFenceOperationResultV1,
    ActiveFenceStateV1,
)
from .active_fence_validation import (
    validate_active_fence_operation_result_v1,
)
from .cross_ledger_order_lock import CrossLedgerOrderLockV1
from .cross_ledger_order_lock import (
    CrossLedgerOrderLockError,
    validate_publish_cross_ledger_lock_pair_v1,
)
from .cross_ledger_order_protocol import (
    build_cross_ledger_order_request_identity_v1,
    persist_or_replay_cross_ledger_ordered_admission_under_lock_v1,
    preflight_cross_ledger_ordered_admission_under_lock_v1,
)
from .cross_ledger_order_types import (
    CrossLedgerOrderRequestV1,
    CrossLedgerOrderStateV1,
    DurableCrossLedgerOrderedAdmissionV1,
)
from .cross_ledger_order_validation import (
    validate_durable_cross_ledger_ordered_admission_v1,
)
from .cross_ledger_order_schema import CrossLedgerOrderIdentityV1
from .fence_admission_reservation_store import (
    persist_or_replay_fence_admission_reservation_v1,
    reobserve_fence_admission_reservation_v1,
)
from .fence_admission_reservation_types import (
    DurableFenceAdmissionReservationV1,
    FenceAdmissionReservationRequestV1,
)
from .fence_admission_reservation_validation import (
    validate_durable_fence_admission_reservation_v1,
)
from .fence_bound_ordered_admission_reobservation import (
    reobserve_exact_ordered_admission_under_locks_v1,
)
from .fence_bound_ordered_admission_types import (
    FenceBoundOrderedAdmissionError,
)
from .fence_order_start_store import (
    persist_or_replay_fence_order_start_v1,
    reobserve_fence_order_start_v1,
)
from .fence_order_start_types import (
    DurableFenceOrderStartV1,
    FenceOrderStartRequestV1,
    PublishCrossLedgerLockPairV1,
)
from .fence_order_start_validation import (
    validate_durable_fence_order_start_v1,
)
from .wire_identity import same_wire_value


@dataclass(frozen=True)
class FenceBoundAdmissionEvidenceV1:
    """Exact non-authorizing evidence retained by one transaction."""

    reservation: DurableFenceAdmissionReservationV1
    fence: ActiveFenceOperationResultV1
    start_intent: DurableFenceOrderStartV1
    ordered: DurableCrossLedgerOrderedAdmissionV1


@dataclass(frozen=True)
class _CausalStartEvidenceV1:
    reservation_request: FenceAdmissionReservationRequestV1
    reservation: DurableFenceAdmissionReservationV1
    fence: ActiveFenceOperationResultV1
    start_request: FenceOrderStartRequestV1
    start: DurableFenceOrderStartV1


def _require_lock_scope(
    publish_lock: ActiveFenceLockV1,
    cross_lock: CrossLedgerOrderLockV1,
    request: object,
) -> CrossLedgerOrderRequestV1:
    try:
        validate_publish_cross_ledger_lock_pair_v1(
            publish_lock, cross_lock
        )
    except (CrossLedgerOrderLockError, RuntimeError) as exc:
        raise FenceBoundOrderedAdmissionError(
            "fence-bound lock lineage is invalid"
        ) from exc
    if type(request) is not CrossLedgerOrderRequestV1:
        raise FenceBoundOrderedAdmissionError(
            "fence-bound cross-ledger request is invalid"
        )
    if request.authority_root != publish_lock.authority_root:
        raise FenceBoundOrderedAdmissionError(
            "fence-bound request crosses authority roots"
        )
    return request


def _validate_evidence(value: object, kind: str) -> None:
    validators = {
        "reservation": validate_durable_fence_admission_reservation_v1,
        "fence": validate_active_fence_operation_result_v1,
        "start": validate_durable_fence_order_start_v1,
        "order": validate_durable_cross_ledger_ordered_admission_v1,
    }
    try:
        validators[kind](value)
    except (AttributeError, KeyError, RuntimeError, TypeError, ValueError) as exc:
        raise FenceBoundOrderedAdmissionError(
            f"fence-bound {kind} evidence is invalid"
        ) from exc


def _fence_mode(
    state: ActiveFenceStateV1, authority_id: str, attempt_id: str
) -> str:
    if state.authority_id != authority_id:
        raise FenceBoundOrderedAdmissionError(
            "active fence crosses admission authority"
        )
    if state.active_attempt_id is None:
        return "fresh"
    if state.active_attempt_id == attempt_id:
        return "replay"
    raise FenceBoundOrderedAdmissionError(
        "another attempt holds the active fence"
    )


def _require_preflight_state(
    state: CrossLedgerOrderStateV1, mode: str
) -> None:
    if mode == "fresh" and state.state != "absent":
        raise FenceBoundOrderedAdmissionError(
            "preexisting order cannot acquire a retrospective fence"
        )


def _reservation_request(
    publish_lock: ActiveFenceLockV1,
    cross_request: CrossLedgerOrderRequestV1,
    identity: CrossLedgerOrderIdentityV1,
) -> FenceAdmissionReservationRequestV1:
    admission = cross_request.admission.admission
    return FenceAdmissionReservationRequestV1(
        publish_lock, identity, admission, cross_request.enrollment
    )


def _bind_reservation(
    request: FenceAdmissionReservationRequestV1, mode: str
) -> DurableFenceAdmissionReservationV1:
    if mode == "replay":
        return reobserve_fence_admission_reservation_v1(request)
    return persist_or_replay_fence_admission_reservation_v1(request)


def _start_request(
    locks: PublishCrossLedgerLockPairV1,
    reservation: DurableFenceAdmissionReservationV1,
    fence: ActiveFenceOperationResultV1,
    identity: CrossLedgerOrderIdentityV1,
) -> FenceOrderStartRequestV1:
    return FenceOrderStartRequestV1(
        locks,
        reservation,
        fence.state,
        identity,
    )


def _bind_start(
    request: FenceOrderStartRequestV1, state: CrossLedgerOrderStateV1
) -> DurableFenceOrderStartV1:
    if state.state == "absent":
        return persist_or_replay_fence_order_start_v1(request)
    return reobserve_fence_order_start_v1(request)


def _require_same(
    initial: object, observed: object, message: str
) -> None:
    if not same_wire_value(initial, observed):
        raise FenceBoundOrderedAdmissionError(message)


def _prepare_causal_start(
    publish_lock: ActiveFenceLockV1,
    cross_lock: CrossLedgerOrderLockV1,
    request: CrossLedgerOrderRequestV1,
) -> _CausalStartEvidenceV1:
    admission = request.admission.admission
    identity = build_cross_ledger_order_request_identity_v1(request)
    initial = preflight_cross_ledger_ordered_admission_under_lock_v1(
        request, cross_lock
    )
    state = reobserve_active_generation_fence_under_lock_v1(publish_lock)
    mode = _fence_mode(state, admission.authority_id, admission.attempt_id)
    _require_preflight_state(initial, mode)
    reservation_request = _reservation_request(
        publish_lock, request, identity
    )
    reservation = _bind_reservation(reservation_request, mode)
    _validate_evidence(reservation, "reservation")
    fence = reserve_active_generation_fence_under_lock_v1(
        publish_lock, admission.authority_id, admission.attempt_id
    )
    _validate_evidence(fence, "fence")
    if fence.operation != "RESERVE" or fence.state.active_attempt_id != (
        admission.attempt_id
    ):
        raise FenceBoundOrderedAdmissionError(
            "active fence result does not bind the requested attempt"
        )
    locks = PublishCrossLedgerLockPairV1(publish_lock, cross_lock)
    start_request = _start_request(locks, reservation, fence, identity)
    start = _bind_start(start_request, initial)
    _validate_evidence(start, "start")
    return _CausalStartEvidenceV1(
        reservation_request, reservation, fence, start_request, start
    )


def _persist_and_reobserve_order(
    publish_lock: ActiveFenceLockV1,
    cross_lock: CrossLedgerOrderLockV1,
    request: CrossLedgerOrderRequestV1,
    causal: _CausalStartEvidenceV1,
) -> DurableCrossLedgerOrderedAdmissionV1:
    ordered = persist_or_replay_cross_ledger_ordered_admission_under_lock_v1(
        request, cross_lock
    )
    _validate_evidence(ordered, "order")
    reobserve_exact_ordered_admission_under_locks_v1(
        publish_lock, cross_lock, request, ordered
    )
    observed_reservation = reobserve_fence_admission_reservation_v1(
        causal.reservation_request
    )
    _validate_evidence(observed_reservation, "reservation")
    _require_same(
        causal.reservation.reservation,
        observed_reservation.reservation,
        "fence admission reservation changed during order",
    )
    observed_start = reobserve_fence_order_start_v1(causal.start_request)
    _validate_evidence(observed_start, "start")
    _require_same(
        causal.start.intent,
        observed_start.intent,
        "fence order start intent changed during order",
    )
    reobserve_exact_active_generation_fence_under_lock_v1(
        publish_lock, causal.fence.state
    )
    return ordered


def admit_fence_bound_ordered_under_locks_v1(
    publish_lock: ActiveFenceLockV1,
    cross_lock: CrossLedgerOrderLockV1,
    request: CrossLedgerOrderRequestV1,
) -> FenceBoundAdmissionEvidenceV1:
    """Bind request, FENCE, start edge, and order without authorizing work."""
    request = _require_lock_scope(publish_lock, cross_lock, request)
    causal = _prepare_causal_start(publish_lock, cross_lock, request)
    ordered = _persist_and_reobserve_order(
        publish_lock, cross_lock, request, causal
    )
    return FenceBoundAdmissionEvidenceV1(
        causal.reservation, causal.fence, causal.start, ordered
    )
