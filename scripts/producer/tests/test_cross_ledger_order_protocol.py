"""Crash, replay, and exact-identity tests for cross-ledger ordering."""

from __future__ import annotations

import dataclasses
import os
import tempfile
import unittest
from unittest.mock import patch

from _common import pl  # noqa: F401
from _cross_ledger_order_fixture import CrossLedgerOrderFixture
from _operation_admission_fixture import admission
from headless.cross_ledger_order_protocol import (
    persist_or_replay_cross_ledger_ordered_admission_v1,
    require_cross_ledger_order_execution_authorized,
)
from headless.cross_ledger_order_reader import (
    reobserve_cross_ledger_order_state_v1,
)
from headless.cross_ledger_order_types import (
    CROSS_LEDGER_ORDER_COMMITTED_STATUS,
    CROSS_LEDGER_ORDER_REPLAY_STATUS,
    CrossLedgerOrderConflictV1,
    CrossLedgerOrderError,
    CrossLedgerOrderPermanentRejectionV1,
    CrossLedgerOrderRequestV1,
)
from headless.cross_ledger_order_validation import (
    CrossLedgerOrderValidationError,
    validate_durable_cross_ledger_ordered_admission_v1,
)
from headless.operation_admission_store import (
    persist_or_replay_operation_admission_v3,
)
from headless.operation_admission_store_types import (
    OperationAdmissionStoreRequestV3,
)


class CrossLedgerOrderProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CrossLedgerOrderFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_commit_then_exact_replay_is_path_free_and_non_authorizing(
        self,
    ) -> None:
        request = self.fixture.request()
        created = self.fixture.persist()
        replayed = self.fixture.persist()
        validate_durable_cross_ledger_ordered_admission_v1(created)
        validate_durable_cross_ledger_ordered_admission_v1(replayed)
        self.assertEqual(created.status, CROSS_LEDGER_ORDER_COMMITTED_STATUS)
        self.assertEqual(replayed.status, CROSS_LEDGER_ORDER_REPLAY_STATUS)
        self.assertTrue(created.order_created)
        self.assertTrue(created.admission_created)
        self.assertFalse(replayed.order_created)
        self.assertFalse(replayed.admission_created)
        observed = reobserve_cross_ledger_order_state_v1(
            self.fixture.root, created.intent.identity
        )
        self.assertEqual(observed.state, "committed")
        self.assertEqual(observed.receipt, created.receipt)
        for value in (created, replayed):
            self.assertFalse(value.runtime_verified)
            self.assertFalse(value.execution_authorized)
            self.assertFalse(value.publication_authorized)
            with self.assertRaises(CrossLedgerOrderError):
                require_cross_ledger_order_execution_authorized(value)
        self.assertEqual(
            request.admission.admission.admission_digest,
            created.intent.identity.admission_digest,
        )

    def test_two_distinct_admissions_for_same_unit_each_receive_receipt(
        self,
    ) -> None:
        first = self.fixture.persist()
        second = self.fixture.persist(second=True)
        self.assertEqual(
            first.intent.identity.unit_id, second.intent.identity.unit_id
        )
        self.assertNotEqual(
            first.intent.identity.idempotency_key,
            second.intent.identity.idempotency_key,
        )
        self.assertTrue(second.order_created)
        self.assertTrue(second.admission_created)
        store = os.path.join(self.fixture.root, "cross-ledger-orders-v1")
        self.assertEqual(len(os.listdir(store)), 2)

    def test_crash_after_prepared_intent_recovers_exact_admission(
        self,
    ) -> None:
        target = (
            "headless.cross_ledger_order_protocol."
            "persist_or_replay_operation_admission_v3_in_transaction"
        )
        with patch(target, side_effect=RuntimeError("crash after intent")):
            with self.assertRaises(CrossLedgerOrderError):
                self.fixture.persist()
        store = os.path.join(self.fixture.root, "cross-ledger-orders-v1")
        record = os.listdir(store)[0]
        self.assertEqual(
            os.listdir(os.path.join(store, record)), ["intent.json"]
        )
        recovered = self.fixture.persist()
        self.assertFalse(recovered.order_created)
        self.assertTrue(recovered.admission_created)
        self.assertEqual(recovered.state, "committed")

    def test_crash_after_admission_before_receipt_recovers_exact_bytes(
        self,
    ) -> None:
        target = (
            "headless.cross_ledger_order_protocol."
            "persist_cross_ledger_order_committed_v1"
        )
        with patch(target, side_effect=RuntimeError("crash after admission")):
            with self.assertRaises(CrossLedgerOrderError):
                self.fixture.persist()
        recovered = self.fixture.persist()
        self.assertFalse(recovered.order_created)
        self.assertFalse(recovered.admission_created)
        self.assertEqual(recovered.state, "committed")

    def test_exact_pending_receipt_is_deterministically_recovered(
        self,
    ) -> None:
        target = "headless.cross_ledger_order_store_write.os.rename"
        original = os.rename
        failed = False

        def interrupt(src: str, dst: str, **kwargs: object) -> None:
            nonlocal failed
            if src == ".receipt.pending" and not failed:
                failed = True
                raise OSError("crash before receipt rename")
            original(src, dst, **kwargs)

        with patch(target, side_effect=interrupt):
            with self.assertRaises(CrossLedgerOrderError):
                self.fixture.persist()
        recovered = self.fixture.persist()
        self.assertEqual(recovered.state, "committed")
        self.assertFalse(recovered.admission_created)

    def test_preexisting_admission_creates_permanent_rejection(self) -> None:
        request = self.fixture.request()
        persist_or_replay_operation_admission_v3(request.admission)
        for _ in range(2):
            with self.assertRaises(CrossLedgerOrderPermanentRejectionV1):
                persist_or_replay_cross_ledger_ordered_admission_v1(request)
        store = os.path.join(self.fixture.root, "cross-ledger-orders-v1")
        record = os.listdir(store)[0]
        self.assertEqual(
            os.listdir(os.path.join(store, record)), ["rejection.json"]
        )

    def test_missed_legacy_race_is_poisoned_not_blessed_on_replay(
        self,
    ) -> None:
        request = self.fixture.request()
        persist_or_replay_operation_admission_v3(request.admission)
        target = "headless.cross_ledger_order_protocol._reject_preexisting"
        with patch(target, return_value=None), self.assertRaises(
            CrossLedgerOrderPermanentRejectionV1
        ):
            persist_or_replay_cross_ledger_ordered_admission_v1(request)
        store = os.path.join(self.fixture.root, "cross-ledger-orders-v1")
        record = os.listdir(store)[0]
        self.assertEqual(
            set(os.listdir(os.path.join(store, record))),
            {"intent.json", "rejection.json"},
        )
        with self.assertRaises(CrossLedgerOrderPermanentRejectionV1):
            persist_or_replay_cross_ledger_ordered_admission_v1(request)

    def test_same_idempotency_with_different_admission_conflicts(self) -> None:
        request = self.fixture.request()
        self.fixture.persist()
        proposed = dataclasses.replace(
            request.admission.proposal,
            attempt_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            intended_child_generation_id=(
                "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
            ),
        )
        changed = OperationAdmissionStoreRequestV3(
            self.fixture.root,
            self.fixture.operation,
            admission(self.fixture.operation, proposed),
            proposed,
        )
        attempted = CrossLedgerOrderRequestV1(
            self.fixture.root, self.fixture.durable_enrollment, changed
        )
        with self.assertRaises(CrossLedgerOrderConflictV1):
            persist_or_replay_cross_ledger_ordered_admission_v1(attempted)

    def test_noncreating_read_does_not_install_missing_lock_or_store(
        self,
    ) -> None:
        identity = self.fixture.persist().intent.identity
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = os.path.realpath(temporary.name)
        os.chmod(root, 0o700)
        before = os.listdir(root)
        with self.assertRaises(CrossLedgerOrderError):
            reobserve_cross_ledger_order_state_v1(root, identity)
        self.assertEqual(os.listdir(root), before)

    def test_forged_receipt_diagnostics_never_close_order(self) -> None:
        value = self.fixture.persist()
        cases = (
            dataclasses.replace(value, state="replay"),
            dataclasses.replace(value, order_created=1),
            dataclasses.replace(value, admission_created=False),
            dataclasses.replace(
                value, cross_ledger_order_receipt_verified=False
            ),
            dataclasses.replace(value, execution_authorized=True),
            dataclasses.replace(
                value,
                intent=dataclasses.replace(value.intent, state="committed"),
            ),
            dataclasses.replace(
                value,
                receipt=dataclasses.replace(
                    value.receipt, intent_digest="0" * 64
                ),
            ),
        )
        for forged in cases:
            with self.subTest(forged=forged), self.assertRaises(
                CrossLedgerOrderValidationError
            ):
                validate_durable_cross_ledger_ordered_admission_v1(forged)


if __name__ == "__main__":
    unittest.main(verbosity=2)
