"""Dependency-result and final named-disk provenance attacks."""

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
)
from headless.cross_ledger_order_lock import (
    locked_cross_ledger_order_under_publish_mutex_v1,
)
from headless.cross_ledger_order_protocol import (
    persist_or_replay_cross_ledger_ordered_admission_v1,
)
from headless.cross_ledger_order_types import CrossLedgerOrderError
from headless.fence_bound_ordered_admission import (
    admit_fence_bound_ordered_work_disabled_v1,
)
from headless.fence_bound_ordered_admission_transaction import (
    admit_fence_bound_ordered_under_locks_v1,
)
from headless.fence_bound_ordered_admission_types import (
    FenceBoundOrderedAdmissionError,
)
from headless.fence_bound_ordered_admission_validation import (
    FenceBoundOrderedAdmissionValidationError,
    validate_fence_bound_ordered_admission_v1,
)
import headless.fence_bound_ordered_admission_transaction as transaction

_TX = "headless.fence_bound_ordered_admission_transaction"
_ORDER_CALL = "persist_or_replay_cross_ledger_ordered_admission_under_lock_v1"
_START_CALL = "persist_or_replay_fence_order_start_v1"
_RESERVATION_CALL = "persist_or_replay_fence_admission_reservation_v1"
_FENCE_CALL = "reserve_active_generation_fence_under_lock_v1"


class FenceBoundOrderedAdmissionProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = FenceBoundOrderedAdmissionFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_none_order_result_cannot_return_positive_claims(self) -> None:
        with patch(f"{_TX}.{_ORDER_CALL}", return_value=None):
            with self.assertRaises(FenceBoundOrderedAdmissionError):
                admit_fence_bound_ordered_work_disabled_v1(
                    self.fixture.request()
                )
        self.assertFalse(
            os.path.exists(self.fixture.path("cross-ledger-orders-v1"))
        )

    def test_composite_result_rejects_forged_diagnostic_claim(self) -> None:
        result = admit_fence_bound_ordered_work_disabled_v1(
            self.fixture.request()
        )
        validate_fence_bound_ordered_admission_v1(result)
        forged = dataclasses.replace(
            result, order_created_under_publisher_mutex=False
        )
        with self.assertRaises(FenceBoundOrderedAdmissionValidationError):
            validate_fence_bound_ordered_admission_v1(forged)

    def test_forged_order_authority_flag_is_rejected(self) -> None:
        original = getattr(transaction, _ORDER_CALL)

        def forged(*args: object) -> object:
            result = original(*args)
            return dataclasses.replace(result, execution_authorized=True)

        with patch(f"{_TX}.{_ORDER_CALL}", side_effect=forged):
            with self.assertRaises(FenceBoundOrderedAdmissionError):
                admit_fence_bound_ordered_work_disabled_v1(
                    self.fixture.request()
                )

    def test_forged_start_authority_flag_is_rejected(self) -> None:
        original = getattr(transaction, _START_CALL)

        def forged(*args: object) -> object:
            result = original(*args)
            return dataclasses.replace(result, execution_authorized=True)

        with patch(f"{_TX}.{_START_CALL}", side_effect=forged):
            with self.assertRaises(FenceBoundOrderedAdmissionError):
                admit_fence_bound_ordered_work_disabled_v1(
                    self.fixture.request()
                )
        self.assertFalse(
            os.path.exists(self.fixture.path("cross-ledger-orders-v1"))
        )

    def test_forged_reservation_authority_flag_is_rejected(self) -> None:
        original = getattr(transaction, _RESERVATION_CALL)

        def forged(*args: object) -> object:
            result = original(*args)
            return dataclasses.replace(result, publication_authorized=True)

        with patch(f"{_TX}.{_RESERVATION_CALL}", side_effect=forged):
            with self.assertRaises(FenceBoundOrderedAdmissionError):
                admit_fence_bound_ordered_work_disabled_v1(
                    self.fixture.request()
                )

    def test_forged_fence_authority_flag_is_rejected(self) -> None:
        original = getattr(transaction, _FENCE_CALL)

        def forged(*args: object) -> object:
            result = original(*args)
            object.__setattr__(result, "execution_authorized", True)
            return result

        with patch(f"{_TX}.{_FENCE_CALL}", side_effect=forged):
            with self.assertRaises(FenceBoundOrderedAdmissionError):
                admit_fence_bound_ordered_work_disabled_v1(
                    self.fixture.request()
                )
        self.assertFalse(
            os.path.exists(self.fixture.path("fence-order-start-intents-v1"))
        )

    def test_named_order_store_displacement_after_return_is_detected(
        self,
    ) -> None:
        original = getattr(transaction, _ORDER_CALL)

        def displaced(*args: object) -> object:
            result = original(*args)
            source = self.fixture.path("cross-ledger-orders-v1")
            os.rename(source, self.fixture.path("archived-orders"))
            return result

        with patch(f"{_TX}.{_ORDER_CALL}", side_effect=displaced):
            with self.assertRaises(FenceBoundOrderedAdmissionError):
                admit_fence_bound_ordered_work_disabled_v1(
                    self.fixture.request()
                )

    def test_named_admission_store_displacement_is_detected(self) -> None:
        original = getattr(transaction, _ORDER_CALL)

        def displaced(*args: object) -> object:
            result = original(*args)
            source = self.fixture.path("operation-admissions-v3")
            os.rename(source, self.fixture.path("archived-admissions"))
            return result

        with patch(f"{_TX}.{_ORDER_CALL}", side_effect=displaced):
            with self.assertRaises(FenceBoundOrderedAdmissionError):
                admit_fence_bound_ordered_work_disabled_v1(
                    self.fixture.request()
                )

    def test_replay_does_not_claim_historical_order_lock_coverage(self) -> None:
        with patch(
            f"{_TX}.{_ORDER_CALL}",
            side_effect=CrossLedgerOrderError("stop after start marker"),
        ):
            with self.assertRaises(FenceBoundOrderedAdmissionError):
                admit_fence_bound_ordered_work_disabled_v1(
                    self.fixture.request()
                )
        persist_or_replay_cross_ledger_ordered_admission_v1(
            self.fixture.cross_request()
        )
        replayed = admit_fence_bound_ordered_work_disabled_v1(
            self.fixture.request()
        )
        self.assertEqual(replayed.ordered_admission.state, "replay")
        self.assertTrue(
            replayed.publisher_mutex_held_during_order_resolution
        )
        self.assertFalse(replayed.order_created_under_publisher_mutex)

    def test_mixed_publish_and_cross_roots_fail_before_mutation(self) -> None:
        other = FenceBoundOrderedAdmissionFixture()
        self.addCleanup(other.close)
        cross_request = self.fixture.cross_request()
        other.cross_request()
        with locked_existing_publish_mutex_v1(other.root) as wrong_publish:
            with locked_existing_publish_mutex_v1(
                self.fixture.root
            ) as right_publish:
                with locked_cross_ledger_order_under_publish_mutex_v1(
                    right_publish
                ) as cross:
                    with self.assertRaises(FenceBoundOrderedAdmissionError):
                        admit_fence_bound_ordered_under_locks_v1(
                            wrong_publish, cross, cross_request
                        )
        self.assertFalse(
            os.path.exists(other.path("fence-admission-reservations-v1"))
        )
        with locked_existing_publish_mutex_v1(other.root) as lock:
            state = reobserve_active_generation_fence_under_lock_v1(lock)
        self.assertIsNone(state.active_attempt_id)
        self.assertFalse(
            os.path.exists(self.fixture.path("cross-ledger-orders-v1"))
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
