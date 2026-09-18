"""Bypass, retrofit, root-swap, and fail-closed controller attacks."""

from __future__ import annotations

import dataclasses
import os
import unittest
from unittest.mock import patch

from _common import pl  # noqa: F401
from _fence_bound_ordered_admission_fixture import (
    FenceBoundOrderedAdmissionFixture,
)
from headless.active_fence_lock import locked_existing_publish_mutex_v1
from headless.active_fence_protocol import (
    reobserve_active_generation_fence_under_lock_v1,
    reserve_active_generation_fence_under_lock_v1,
    reserve_active_generation_fence_v1,
)
from headless.cross_ledger_order_lock import (
    locked_cross_ledger_order_root_v1,
)
from headless.cross_ledger_order_protocol import (
    build_cross_ledger_order_request_identity_v1,
    persist_or_replay_cross_ledger_ordered_admission_v1,
)
from headless.cross_ledger_order_types import CrossLedgerOrderError
from headless.fence_admission_reservation_store import (
    persist_or_replay_fence_admission_reservation_v1,
)
from headless.fence_admission_reservation_types import (
    FenceAdmissionReservationRequestV1,
)
from headless.fence_bound_ordered_admission import (
    admit_fence_bound_ordered_work_disabled_v1,
)
from headless.fence_bound_ordered_admission_transaction import (
    admit_fence_bound_ordered_under_locks_v1,
)
from headless.fence_bound_ordered_admission_types import (
    FenceBoundOrderedAdmissionError,
)
import headless.fence_bound_ordered_admission_transaction as transaction

_TX = "headless.fence_bound_ordered_admission_transaction"
_RESERVATIONS = "fence-admission-reservations-v1"
_STARTS = "fence-order-start-intents-v1"
_ORDERS = "cross-ledger-orders-v1"


class FenceBoundOrderedAdmissionAdversarialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = FenceBoundOrderedAdmissionFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def _active(self) -> object:
        with locked_existing_publish_mutex_v1(self.fixture.root) as lock:
            return reobserve_active_generation_fence_under_lock_v1(lock)

    def _persist_binding_and_fence(self) -> object:
        cross_request = self.fixture.cross_request()
        identity = build_cross_ledger_order_request_identity_v1(cross_request)
        admitted = cross_request.admission.admission
        with locked_existing_publish_mutex_v1(self.fixture.root) as lock:
            reservation = FenceAdmissionReservationRequestV1(
                lock, identity, admitted, cross_request.enrollment
            )
            persist_or_replay_fence_admission_reservation_v1(reservation)
            reserve_active_generation_fence_under_lock_v1(
                lock, admitted.authority_id, admitted.attempt_id
            )
        return cross_request

    def _assert_absent(self, *names: str) -> None:
        for name in names:
            with self.subTest(name=name):
                self.assertFalse(os.path.exists(self.fixture.path(name)))

    def test_changed_request_cannot_reuse_fence_after_crash(self) -> None:
        original = transaction.reserve_active_generation_fence_under_lock_v1

        def crash(*args: object) -> object:
            original(*args)
            raise OSError("crash after durable FENCE")

        with patch(
            f"{_TX}.reserve_active_generation_fence_under_lock_v1",
            side_effect=crash,
        ):
            with self.assertRaises(FenceBoundOrderedAdmissionError):
                admit_fence_bound_ordered_work_disabled_v1(
                    self.fixture.request()
                )
        with self.assertRaises(FenceBoundOrderedAdmissionError):
            admit_fence_bound_ordered_work_disabled_v1(
                self.fixture.changed_child_request()
            )
        self.assertEqual(self._active().active_attempt_id, self.fixture.attempt_id)
        self._assert_absent(_STARTS, _ORDERS)

    def test_uuid_only_reserve_cannot_be_healed_by_controller(self) -> None:
        reserve_active_generation_fence_v1(
            self.fixture.root,
            self.fixture.admitted.authority_id,
            self.fixture.attempt_id,
        )
        with self.assertRaises(FenceBoundOrderedAdmissionError):
            admit_fence_bound_ordered_work_disabled_v1(
                self.fixture.request()
            )
        self._assert_absent(_RESERVATIONS, _STARTS, _ORDERS)

    def test_preexisting_order_cannot_receive_retrospective_fence(self) -> None:
        cross_request = self.fixture.cross_request()
        persist_or_replay_cross_ledger_ordered_admission_v1(cross_request)
        with self.assertRaises(FenceBoundOrderedAdmissionError):
            admit_fence_bound_ordered_work_disabled_v1(
                self.fixture.request()
            )
        self.assertIsNone(self._active().active_attempt_id)
        self._assert_absent(_RESERVATIONS, _STARTS)

    def test_preexisting_order_cannot_receive_missing_start_marker(self) -> None:
        cross_request = self._persist_binding_and_fence()
        persist_or_replay_cross_ledger_ordered_admission_v1(cross_request)
        with self.assertRaises(FenceBoundOrderedAdmissionError):
            admit_fence_bound_ordered_work_disabled_v1(
                self.fixture.request()
            )
        self._assert_absent(_STARTS)
        self.assertEqual(self._active().active_attempt_id, self.fixture.attempt_id)

    def test_second_attempt_is_rejected_while_first_fence_is_active(self) -> None:
        admit_fence_bound_ordered_work_disabled_v1(self.fixture.request())
        with self.assertRaises(FenceBoundOrderedAdmissionError):
            admit_fence_bound_ordered_work_disabled_v1(
                self.fixture.second_request()
            )
        self.assertEqual(self._active().active_attempt_id, self.fixture.attempt_id)
        self.assertEqual(len(os.listdir(self.fixture.path(_RESERVATIONS))), 1)
        self.assertEqual(len(os.listdir(self.fixture.path(_STARTS))), 1)
        self.assertEqual(len(os.listdir(self.fixture.path(_ORDERS))), 1)

    def test_order_failure_leaves_fence_active_and_never_cancels(self) -> None:
        target = (
            f"{_TX}."
            "persist_or_replay_cross_ledger_ordered_admission_under_lock_v1"
        )
        with patch(target, side_effect=CrossLedgerOrderError("injected")):
            with self.assertRaises(FenceBoundOrderedAdmissionError):
                admit_fence_bound_ordered_work_disabled_v1(
                    self.fixture.request()
                )
        self.assertEqual(self._active().active_attempt_id, self.fixture.attempt_id)
        self.assertTrue(os.path.isdir(self.fixture.path(_STARTS)))
        self._assert_absent(_ORDERS)

    def test_standalone_cross_lock_is_not_controller_lineage(self) -> None:
        cross_request = self.fixture.cross_request()
        with locked_existing_publish_mutex_v1(self.fixture.root) as publish:
            with locked_cross_ledger_order_root_v1(
                self.fixture.root
            ) as cross:
                with self.assertRaises(FenceBoundOrderedAdmissionError):
                    admit_fence_bound_ordered_under_locks_v1(
                        publish, cross, cross_request
                    )
        self.assertIsNone(self._active().active_attempt_id)
        self._assert_absent(_RESERVATIONS, _STARTS, _ORDERS)

    def test_root_swap_cannot_redirect_controller_writes(self) -> None:
        moved = f"{self.fixture.root}.retained"
        original = transaction.preflight_cross_ledger_ordered_admission_under_lock_v1

        def swap(*args: object) -> object:
            os.rename(self.fixture.root, moved)
            os.mkdir(self.fixture.root, 0o700)
            return original(*args)

        try:
            with patch(
                f"{_TX}.preflight_cross_ledger_ordered_admission_under_lock_v1",
                side_effect=swap,
            ):
                with self.assertRaises(FenceBoundOrderedAdmissionError):
                    admit_fence_bound_ordered_work_disabled_v1(
                        self.fixture.request()
                    )
            self.assertEqual(os.listdir(self.fixture.root), [])
            retained = set(os.listdir(moved))
            self.assertFalse({_RESERVATIONS, _STARTS, _ORDERS} & retained)
        finally:
            os.rmdir(self.fixture.root)
            os.rename(moved, self.fixture.root)

    def test_hostile_root_type_is_normalized(self) -> None:
        request = self.fixture.request()
        hostile_store = dataclasses.replace(
            request.admission, authority_root=[]  # type: ignore[arg-type]
        )
        hostile = dataclasses.replace(request, admission=hostile_store)
        with self.assertRaises(FenceBoundOrderedAdmissionError):
            admit_fence_bound_ordered_work_disabled_v1(hostile)


if __name__ == "__main__":
    unittest.main(verbosity=2)
