"""Nominal, noncreating, and exact-identity order-start tests."""

from __future__ import annotations

import dataclasses
import os
import unittest

from _common import pl  # noqa: F401
from _fence_order_start_fixture import FenceOrderStartFixture
from headless.active_fence_schema import build_active_fence_state_v1
from headless.cross_ledger_order_store import (
    persist_cross_ledger_order_prepared_v1,
)
from headless.cross_ledger_order_protocol import (
    persist_or_replay_cross_ledger_ordered_admission_under_lock_v1,
)
from headless.fence_order_start_store import (
    FenceOrderStartError,
    reobserve_fence_order_start_v1,
)
from headless.fence_order_start_validation import (
    DurableFenceOrderStartValidationError,
    validate_durable_fence_order_start_v1,
)

OTHER_ATTEMPT = "abababab-abab-4bab-8bab-abababababab"
OTHER_TOKEN = "acacacac-acac-4cac-8cac-acacacacacac"


class FenceOrderStartStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = FenceOrderStartFixture()
        self.addCleanup(self.fixture.close)

    def test_create_replay_and_read_bind_fence_before_prepared(self) -> None:
        self.assertFalse(
            os.path.exists(
                os.path.join(self.fixture.root, "cross-ledger-orders-v1")
            )
        )
        created = self.fixture.persist()
        replayed = self.fixture.persist()
        observed = self.fixture.reobserve()
        self.assertTrue(created.created)
        self.assertFalse(replayed.created)
        self.assertFalse(observed.created)
        self.assertEqual(created.intent, observed.intent)
        self.assertEqual(
            created.intent.fence_revision, self.fixture.fence.fence_revision
        )
        self.assertEqual(
            created.intent.fence_token, self.fixture.fence.fence_token
        )
        self.assertEqual(
            created.intent.reservation_digest,
            self.fixture.reservation.reservation.reservation_digest,
        )
        self.assertEqual(
            created.intent.order_identity_digest,
            self.fixture.identity.order_identity_digest,
        )
        for result in (created, replayed, observed):
            validate_durable_fence_order_start_v1(result)
            self.assertTrue(result.reservation_bytes_reobserved)
            self.assertTrue(result.active_fence_reobserved)
            self.assertTrue(result.publish_cross_lock_pair_verified)
            self.assertTrue(result.intent_bytes_reobserved)
            self.assertTrue(result.replay_arbitrated)
            self.assertFalse(result.execution_authorized)
            self.assertFalse(result.publication_authorized)
        self.assertFalse(
            os.path.exists(
                os.path.join(self.fixture.root, "cross-ledger-orders-v1")
            )
        )
        self.assertFalse(
            os.path.exists(os.path.join(self.fixture.root, "CURRENT"))
        )

    def test_missing_read_does_not_create_or_heal_start_store(self) -> None:
        self.assertFalse(self.fixture.start_store_exists())
        with self.fixture.locked_request() as request:
            with self.assertRaises(FenceOrderStartError):
                reobserve_fence_order_start_v1(request)
        self.assertFalse(self.fixture.start_store_exists())

    def test_prepared_order_cannot_be_healed_with_retroactive_start(
        self,
    ) -> None:
        with self.fixture.locked_request() as request:
            state = persist_cross_ledger_order_prepared_v1(
                request.locks.cross_lock, self.fixture.identity
            )
        self.assertEqual(state.state, "prepared")
        self.assertFalse(self.fixture.start_store_exists())
        with self.assertRaises(FenceOrderStartError):
            self.fixture.persist()
        self.assertFalse(self.fixture.start_store_exists())

    def test_existing_start_replays_after_order_becomes_prepared(self) -> None:
        created = self.fixture.persist()
        with self.fixture.locked_request() as request:
            state = persist_cross_ledger_order_prepared_v1(
                request.locks.cross_lock, self.fixture.identity
            )
        replayed = self.fixture.persist()
        self.assertEqual(state.state, "prepared")
        self.assertTrue(created.created)
        self.assertFalse(replayed.created)
        self.assertEqual(created.intent, replayed.intent)

    def test_existing_start_replays_after_order_commits(self) -> None:
        created = self.fixture.persist()
        with self.fixture.locked_request() as request:
            ordered = (
                persist_or_replay_cross_ledger_ordered_admission_under_lock_v1(
                    self.fixture.cross_request, request.locks.cross_lock
                )
            )
        replayed = self.fixture.persist()
        self.assertEqual(ordered.state, "committed")
        self.assertTrue(created.created)
        self.assertFalse(replayed.created)
        self.assertEqual(created.intent, replayed.intent)

    def test_mismatched_fence_token_revision_and_attempt_fail(self) -> None:
        fence = self.fixture.fence
        cases = (
            build_active_fence_state_v1(
                fence.authority_id,
                fence.fence_revision,
                OTHER_TOKEN,
                fence.active_attempt_id,
            ),
            build_active_fence_state_v1(
                fence.authority_id,
                fence.fence_revision + 1,
                fence.fence_token,
                fence.active_attempt_id,
            ),
            build_active_fence_state_v1(
                fence.authority_id,
                fence.fence_revision,
                fence.fence_token,
                OTHER_ATTEMPT,
            ),
        )
        for changed in cases:
            with self.subTest(changed=changed):
                with self.fixture.locked_request(fence=changed) as request:
                    with self.assertRaises(FenceOrderStartError):
                        reobserve_fence_order_start_v1(request)

    def test_forged_reservation_and_order_identity_fail(self) -> None:
        reservation = dataclasses.replace(
            self.fixture.reservation,
            reservation=dataclasses.replace(
                self.fixture.reservation.reservation,
                reservation_digest="0" * 64,
            ),
        )
        identity = dataclasses.replace(
            self.fixture.identity, order_identity_digest="0" * 64
        )
        for values in ((reservation, None), (None, identity)):
            with self.subTest(values=values):
                with self.fixture.locked_request(
                    reservation=values[0], identity=values[1]
                ) as request:
                    with self.assertRaises(FenceOrderStartError):
                        reobserve_fence_order_start_v1(request)

    def test_forged_results_never_gain_authority(self) -> None:
        created = self.fixture.persist()
        cases = (
            dataclasses.replace(created, created=1),
            dataclasses.replace(created, execution_authorized=True),
            dataclasses.replace(
                created,
                intent=dataclasses.replace(
                    created.intent, start_digest="0" * 64
                ),
            ),
        )
        for forged in cases:
            with self.subTest(forged=forged), self.assertRaises(
                DurableFenceOrderStartValidationError
            ):
                validate_durable_fence_order_start_v1(forged)


if __name__ == "__main__":
    unittest.main(verbosity=2)
