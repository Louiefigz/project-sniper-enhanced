"""Integrated causal-order and crash-replay tests for fenced admission."""

from __future__ import annotations

import os
import unittest
from collections.abc import Callable
from unittest.mock import patch

from _common import pl  # noqa: F401
from _fence_bound_ordered_admission_fixture import (
    FenceBoundOrderedAdmissionFixture,
)
from headless.fence_bound_ordered_admission import (
    admit_fence_bound_ordered_work_disabled_v1,
)
from headless.fence_bound_ordered_admission_types import (
    FenceBoundOrderedAdmissionError,
)
import headless.fence_bound_ordered_admission_transaction as transaction

_TX = "headless.fence_bound_ordered_admission_transaction"


class FenceBoundOrderedAdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = FenceBoundOrderedAdmissionFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def _crash_after(self, function_name: str) -> object:
        original = getattr(transaction, function_name)

        def crash(*args: object, **kwargs: object) -> object:
            original(*args, **kwargs)
            raise OSError("simulated crash boundary")

        with patch(f"{_TX}.{function_name}", side_effect=crash):
            with self.assertRaises(FenceBoundOrderedAdmissionError):
                admit_fence_bound_ordered_work_disabled_v1(
                    self.fixture.request()
                )
        return admit_fence_bound_ordered_work_disabled_v1(
            self.fixture.request()
        )

    def test_nominal_and_exact_replay_are_work_disabled(self) -> None:
        created = admit_fence_bound_ordered_work_disabled_v1(
            self.fixture.request()
        )
        replayed = admit_fence_bound_ordered_work_disabled_v1(
            self.fixture.request()
        )
        self.assertEqual(created.ordered_admission.state, "committed")
        self.assertEqual(replayed.ordered_admission.state, "replay")
        self.assertTrue(created.start_intent.created)
        self.assertFalse(replayed.start_intent.created)
        self.assertEqual(created.start_intent.intent, replayed.start_intent.intent)
        positive = (
            created.exact_reservation_reobserved,
            created.exact_start_intent_reobserved,
            created.admission_fence_reserved_before_order,
            created.publisher_mutex_held_during_order_resolution,
            created.order_created_under_publisher_mutex,
            created.fence_state_reobserved_after_order,
        )
        denied = (
            created.operation_runtime_verified,
            created.fence_rechecked,
            created.execution_authorized,
            created.publication_authorized,
            created.release_authorized,
            created.work_launched,
            created.current_advanced,
        )
        self.assertEqual(positive, (True,) * 6)
        self.assertEqual(denied, (False,) * 7)
        self.assertFalse(os.path.exists(self.fixture.path("CURRENT")))
        self.assertFalse(replayed.order_created_under_publisher_mutex)

    def test_binding_crash_replays_without_changing_identity(self) -> None:
        result = self._crash_after(
            "persist_or_replay_fence_admission_reservation_v1"
        )
        self.assertEqual(result.ordered_admission.state, "committed")
        self.assertFalse(result.reservation.created)

    def test_fence_crash_replays_before_start_and_order(self) -> None:
        result = self._crash_after(
            "reserve_active_generation_fence_under_lock_v1"
        )
        self.assertTrue(result.fence.replayed)
        self.assertEqual(result.ordered_admission.state, "committed")

    def test_start_crash_replays_before_prepared(self) -> None:
        result = self._crash_after(
            "persist_or_replay_fence_order_start_v1"
        )
        self.assertFalse(result.start_intent.created)
        self.assertEqual(result.ordered_admission.state, "committed")

    def test_committed_order_crash_replays_without_healing_edge(self) -> None:
        result = self._crash_after(
            "persist_or_replay_cross_ledger_ordered_admission_under_lock_v1"
        )
        self.assertEqual(result.ordered_admission.state, "replay")
        self.assertFalse(result.start_intent.created)

    def test_observed_call_order_places_start_before_order(self) -> None:
        names = (
            "persist_or_replay_fence_admission_reservation_v1",
            "reserve_active_generation_fence_under_lock_v1",
            "persist_or_replay_fence_order_start_v1",
            "persist_or_replay_cross_ledger_ordered_admission_under_lock_v1",
        )
        events: list[str] = []
        stack = []
        for name in names:
            original = getattr(transaction, name)
            wrapper = self._recording_wrapper(events, name, original)
            stack.append(patch(f"{_TX}.{name}", side_effect=wrapper))
        with stack[0], stack[1], stack[2], stack[3]:
            admit_fence_bound_ordered_work_disabled_v1(
                self.fixture.request()
            )
        self.assertEqual(events, list(names))

    @staticmethod
    def _recording_wrapper(
        events: list[str], name: str, function: Callable[..., object]
    ) -> Callable[..., object]:
        def wrapped(*args: object, **kwargs: object) -> object:
            events.append(name)
            return function(*args, **kwargs)

        return wrapped


if __name__ == "__main__":
    unittest.main(verbosity=2)
