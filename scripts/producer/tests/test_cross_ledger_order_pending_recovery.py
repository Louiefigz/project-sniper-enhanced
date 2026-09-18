"""Crash recovery tests for pre-rename order and admission records."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from _common import pl  # noqa: F401
from _cross_ledger_order_fixture import CrossLedgerOrderFixture
from headless.cross_ledger_order_lock import (
    locked_cross_ledger_order_root_v1,
)
from headless.cross_ledger_order_protocol import (
    persist_or_replay_cross_ledger_ordered_admission_v1,
)
from headless.cross_ledger_order_schema import (
    parse_cross_ledger_order_document_v1,
)
from headless.cross_ledger_order_reader import (
    reobserve_cross_ledger_order_state_v1,
)
from headless.cross_ledger_order_types import CrossLedgerOrderError
from headless.operation_admission_order_bridge import (
    OperationAdmissionOrderBridgeError,
    operation_admission_exists_for_request_v3_under_order_lock,
)
from headless.operation_admission_pending import (
    OperationAdmissionPendingError,
    cleanup_abandoned_operation_admission_pending_v3,
)
from headless.operation_admission_store import (
    OperationAdmissionStoreError,
    persist_or_replay_operation_admission_v3,
)


def _fail_pending_rename(src: str, dst: str, **kwargs: object) -> None:
    if src.startswith(".pending-"):
        raise OSError("crash before record rename")
    os.rename(src, dst, **kwargs)


class CrossLedgerOrderPendingRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CrossLedgerOrderFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_order_writer_discards_complete_uncommitted_record(self) -> None:
        target = "headless.cross_ledger_order_store_write.os.rename"
        with patch(target, side_effect=_fail_pending_rename):
            with self.assertRaises(CrossLedgerOrderError):
                self.fixture.persist()
        store = os.path.join(self.fixture.root, "cross-ledger-orders-v1")
        self.assertTrue(os.listdir(store)[0].startswith(".pending-"))
        result = self.fixture.persist()
        self.assertEqual(result.state, "committed")
        self.assertFalse(
            any(name.startswith(".") for name in os.listdir(store))
        )

    def test_admission_writer_discards_complete_uncommitted_record(
        self,
    ) -> None:
        request = self.fixture.request().admission
        target = "headless.operation_admission_store_persistence.os.rename"
        with patch(target, side_effect=_fail_pending_rename):
            with self.assertRaises(OperationAdmissionStoreError):
                persist_or_replay_operation_admission_v3(request)
        store = os.path.join(self.fixture.root, "operation-admissions-v3")
        self.assertTrue(os.listdir(store)[0].startswith(".pending-"))
        result = persist_or_replay_operation_admission_v3(request)
        self.assertTrue(result.created)
        self.assertFalse(
            any(name.startswith(".") for name in os.listdir(store))
        )

    def test_ordered_writer_recovers_a_prior_v3_pending_record(self) -> None:
        request = self.fixture.request().admission
        target = "headless.operation_admission_store_persistence.os.rename"
        with patch(target, side_effect=_fail_pending_rename):
            with self.assertRaises(OperationAdmissionStoreError):
                persist_or_replay_operation_admission_v3(request)
        recovered = self.fixture.persist()
        self.assertEqual(recovered.state, "committed")
        self.assertTrue(recovered.admission_created)

    def test_order_read_does_not_clean_abandoned_record(self) -> None:
        target = "headless.cross_ledger_order_store_write.os.rename"
        with patch(target, side_effect=_fail_pending_rename):
            with self.assertRaises(CrossLedgerOrderError):
                self.fixture.persist()
        store = os.path.join(self.fixture.root, "cross-ledger-orders-v1")
        pending = os.listdir(store)[0]
        intent_path = os.path.join(store, pending, "intent.json")
        with open(intent_path, "rb") as source:
            identity = parse_cross_ledger_order_document_v1(
                source.read()
            ).identity
        with self.assertRaises(CrossLedgerOrderError):
            reobserve_cross_ledger_order_state_v1(self.fixture.root, identity)
        self.assertEqual(os.listdir(store), [pending])

    def test_admission_read_does_not_clean_abandoned_record(self) -> None:
        request = self.fixture.request().admission
        target = "headless.operation_admission_store_persistence.os.rename"
        with patch(target, side_effect=_fail_pending_rename):
            with self.assertRaises(OperationAdmissionStoreError):
                persist_or_replay_operation_admission_v3(request)
        store = os.path.join(self.fixture.root, "operation-admissions-v3")
        pending = os.listdir(store)[0]
        with locked_cross_ledger_order_root_v1(self.fixture.root) as lock:
            with self.assertRaises(OperationAdmissionOrderBridgeError):
                operation_admission_exists_for_request_v3_under_order_lock(
                    request, lock
                )
        self.assertEqual(os.listdir(store), [pending])

    def test_unsafe_pending_node_fails_closed(self) -> None:
        request = self.fixture.request()
        target = "headless.cross_ledger_order_store_write.os.rename"
        with patch(target, side_effect=_fail_pending_rename):
            with self.assertRaises(CrossLedgerOrderError):
                persist_or_replay_cross_ledger_ordered_admission_v1(request)
        store = os.path.join(self.fixture.root, "cross-ledger-orders-v1")
        pending = os.listdir(store)[0]
        intent = os.path.join(store, pending, "intent.json")
        os.unlink(intent)
        os.symlink("outside", intent)
        with self.assertRaises(CrossLedgerOrderError):
            persist_or_replay_cross_ledger_ordered_admission_v1(request)
        self.assertTrue(os.path.islink(intent))

    def test_order_pending_target_mismatch_is_not_deleted(self) -> None:
        target = "headless.cross_ledger_order_store_write.os.rename"
        with patch(target, side_effect=_fail_pending_rename):
            with self.assertRaises(CrossLedgerOrderError):
                self.fixture.persist()
        store = os.path.join(self.fixture.root, "cross-ledger-orders-v1")
        pending = os.listdir(store)[0]
        nonce = pending.rsplit("-", 1)[1]
        changed = f".pending-{'0' * 64}-{nonce}"
        os.rename(os.path.join(store, pending), os.path.join(store, changed))
        with self.assertRaises(CrossLedgerOrderError):
            self.fixture.persist()
        self.assertEqual(os.listdir(store), [changed])

    def test_v3_pending_target_mismatch_is_not_deleted(self) -> None:
        request = self.fixture.request().admission
        target = "headless.operation_admission_store_persistence.os.rename"
        with patch(target, side_effect=_fail_pending_rename):
            with self.assertRaises(OperationAdmissionStoreError):
                persist_or_replay_operation_admission_v3(request)
        store = os.path.join(self.fixture.root, "operation-admissions-v3")
        pending = os.listdir(store)[0]
        nonce = pending.rsplit("-", 1)[1]
        changed = f".pending-{'0' * 64}-{nonce}"
        os.rename(os.path.join(store, pending), os.path.join(store, changed))
        with self.assertRaises(OperationAdmissionStoreError):
            persist_or_replay_operation_admission_v3(request)
        self.assertEqual(os.listdir(store), [changed])

    def test_v3_cleanup_rejects_a_raw_store_descriptor(self) -> None:
        request = self.fixture.request().admission
        persist_or_replay_operation_admission_v3(request)
        store = os.path.join(self.fixture.root, "operation-admissions-v3")
        store_fd = os.open(store, os.O_RDONLY | os.O_DIRECTORY)
        try:
            with self.assertRaises(OperationAdmissionPendingError):
                cleanup_abandoned_operation_admission_pending_v3(store_fd)
        finally:
            os.close(store_fd)


if __name__ == "__main__":
    unittest.main(verbosity=2)
