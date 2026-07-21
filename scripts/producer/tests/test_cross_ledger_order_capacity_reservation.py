"""Logical V3 capacity reservation tests across PREPARED crashes."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from _common import pl  # noqa: F401
from _cross_ledger_order_fixture import CrossLedgerOrderFixture
from headless import operation_admission_transaction as transaction_module
from headless.cross_ledger_order_types import CrossLedgerOrderError
from headless.operation_admission_store import (
    OperationAdmissionStoreError,
    persist_or_replay_operation_admission_v3,
)


class CrossLedgerOrderCapacityReservationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CrossLedgerOrderFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def _leave_prepared(self) -> None:
        target = (
            "headless.cross_ledger_order_protocol."
            "persist_or_replay_operation_admission_v3_in_transaction"
        )
        with patch(target, side_effect=RuntimeError("crash after PREPARED")):
            with self.assertRaises(CrossLedgerOrderError):
                self.fixture.persist()

    def test_full_v3_store_fails_before_prepared_is_written(self) -> None:
        first = self.fixture.request(second=True).admission
        with patch.object(transaction_module, "_MAX_RECORDS", 1):
            persist_or_replay_operation_admission_v3(first)
            with self.assertRaises(CrossLedgerOrderError):
                self.fixture.persist()
        order_store = os.path.join(self.fixture.root, "cross-ledger-orders-v1")
        self.assertFalse(os.path.exists(order_store))

    def test_prepared_slot_cannot_be_consumed_by_an_unrelated_writer(
        self,
    ) -> None:
        second = self.fixture.request(second=True).admission
        with patch.object(transaction_module, "_MAX_RECORDS", 1):
            self._leave_prepared()
            with self.assertRaisesRegex(
                OperationAdmissionStoreError, "capacity"
            ):
                persist_or_replay_operation_admission_v3(second)
            recovered = self.fixture.persist()
        self.assertEqual(recovered.state, "committed")
        self.assertTrue(recovered.admission_created)
        admissions = os.path.join(self.fixture.root, "operation-admissions-v3")
        self.assertEqual(len(os.listdir(admissions)), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
