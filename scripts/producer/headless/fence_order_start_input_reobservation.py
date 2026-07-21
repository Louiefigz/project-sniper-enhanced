"""Pinned reobservation of the inputs to one order-start intent."""

from __future__ import annotations

import os

from .active_fence_protocol import (
    reobserve_exact_active_generation_fence_under_lock_v1,
)
from .cross_ledger_order_lock import (
    validate_publish_cross_ledger_lock_pair_v1,
)
from .fence_admission_reservation_records import (
    STORE_NAME as RESERVATION_STORE_NAME,
    open_existing_fence_admission_reservation_store_v1,
    pinned_fence_admission_reservation_v1,
)
from .fence_admission_reservation_validation import (
    validate_durable_fence_admission_reservation_v1,
)
from .fence_order_start_types import (
    FenceOrderStartError,
    FenceOrderStartRequestV1,
    PublishCrossLedgerLockPairV1,
)
from .record_durability import assert_named_private_directory_identity
from .wire_identity import same_wire_value


def validate_fence_order_start_lock_pair_v1(value: object) -> None:
    """Require the exact typed parent and descended cross-lock witnesses."""
    if type(value) is not PublishCrossLedgerLockPairV1:
        raise FenceOrderStartError("publish-cross lock pair is invalid")
    validate_publish_cross_ledger_lock_pair_v1(
        value.publish_lock, value.cross_lock
    )


def _reobserve_reservation(request: FenceOrderStartRequestV1) -> None:
    locks = request.locks
    expected = request.reservation
    validate_durable_fence_admission_reservation_v1(expected)
    store_fd = open_existing_fence_admission_reservation_store_v1(
        locks.publish_lock
    )
    try:
        with pinned_fence_admission_reservation_v1(
            store_fd, expected.record_name
        ) as observed:
            exact = (
                observed.raw == expected.reservation.document_json
                and same_wire_value(observed.reservation, expected.reservation)
            )
            if not exact:
                raise FenceOrderStartError("start reservation bytes changed")
        assert_named_private_directory_identity(
            locks.publish_lock.root_fd,
            RESERVATION_STORE_NAME,
            store_fd,
        )
    finally:
        os.close(store_fd)


def require_exact_fence_order_start_inputs_v1(value: object) -> None:
    """Reobserve the reservation and active fence under both live locks."""
    if type(value) is not FenceOrderStartRequestV1:
        raise FenceOrderStartError("fence order start request is invalid")
    validate_fence_order_start_lock_pair_v1(value.locks)
    _reobserve_reservation(value)
    validate_fence_order_start_lock_pair_v1(value.locks)
    reobserve_exact_active_generation_fence_under_lock_v1(
        value.locks.publish_lock, value.fence
    )
    validate_fence_order_start_lock_pair_v1(value.locks)
