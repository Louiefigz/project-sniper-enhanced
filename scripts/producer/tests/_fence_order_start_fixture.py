"""Exact live-lock fixture for fence-before-order start intents."""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator

from _cross_ledger_order_fixture import CrossLedgerOrderFixture
from headless.active_fence_lock import locked_existing_publish_mutex_v1
from headless.active_fence_protocol import (
    bootstrap_active_generation_fence_v1,
    reserve_active_generation_fence_under_lock_v1,
)
from headless.cross_ledger_order_lock import (
    locked_cross_ledger_order_under_publish_mutex_v1,
)
from headless.cross_ledger_order_protocol import (
    build_cross_ledger_order_request_identity_v1,
)
from headless.fence_admission_reservation_store import (
    persist_or_replay_fence_admission_reservation_v1,
)
from headless.fence_admission_reservation_types import (
    FenceAdmissionReservationRequestV1,
)
from headless.fence_order_start_store import (
    persist_or_replay_fence_order_start_v1,
    reobserve_fence_order_start_v1,
)
from headless.fence_order_start_types import (
    FenceOrderStartRequestV1,
    PublishCrossLedgerLockPairV1,
)


class FenceOrderStartFixture:
    """One exact reservation and active fence, with no order PREPARED yet."""

    def __init__(self) -> None:
        self.cross = CrossLedgerOrderFixture()
        self.root = self.cross.root
        self.cross_request = self.cross.request()
        self.identity = build_cross_ledger_order_request_identity_v1(
            self.cross_request
        )
        admission = self.cross_request.admission.admission
        bootstrap_active_generation_fence_v1(self.root, admission.authority_id)
        with locked_existing_publish_mutex_v1(self.root) as publish:
            with locked_cross_ledger_order_under_publish_mutex_v1(publish):
                reservation_request = FenceAdmissionReservationRequestV1(
                    publish,
                    self.identity,
                    admission,
                    self.cross_request.enrollment,
                )
                self.reservation = (
                    persist_or_replay_fence_admission_reservation_v1(
                        reservation_request
                    )
                )
                fence = reserve_active_generation_fence_under_lock_v1(
                    publish, admission.authority_id, admission.attempt_id
                )
                self.fence = fence.state

    def close(self) -> None:
        """Remove the temporary authority root."""
        self.cross.close()

    @contextlib.contextmanager
    def locked_request(
        self,
        reservation: object | None = None,
        fence: object | None = None,
        identity: object | None = None,
    ) -> Iterator[FenceOrderStartRequestV1]:
        """Yield one request with exact live publisher/cross lineage."""
        with locked_existing_publish_mutex_v1(self.root) as publish:
            with locked_cross_ledger_order_under_publish_mutex_v1(
                publish
            ) as cross:
                yield FenceOrderStartRequestV1(
                    PublishCrossLedgerLockPairV1(publish, cross),
                    reservation or self.reservation,
                    fence or self.fence,
                    identity or self.identity,
                )

    def persist(self):
        """Persist or replay the exact start intent."""
        with self.locked_request() as request:
            return persist_or_replay_fence_order_start_v1(request)

    def reobserve(self):
        """Reobserve the existing exact start intent without creation."""
        with self.locked_request() as request:
            return reobserve_fence_order_start_v1(request)

    def start_store_exists(self) -> bool:
        """Return whether the start-intent store has been created."""
        return os.path.exists(
            os.path.join(self.root, "fence-order-start-intents-v1")
        )
