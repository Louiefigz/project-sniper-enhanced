"""Concurrency, lock-capability, capacity, and hostile-filesystem attacks."""

from __future__ import annotations

import dataclasses
import multiprocessing
import os
import unittest
from unittest.mock import patch

from _common import pl  # noqa: F401
from _cross_ledger_order_fixture import CrossLedgerOrderFixture
from headless.cross_ledger_order_lock import (
    CrossLedgerOrderLockError,
    locked_cross_ledger_order_root_v1,
    validate_cross_ledger_order_lock_v1,
)
from headless.cross_ledger_order_protocol import (
    persist_or_replay_cross_ledger_ordered_admission_v1,
)
from headless.cross_ledger_order_reader import (
    reobserve_cross_ledger_order_state_v1,
)
from headless.cross_ledger_order_types import CrossLedgerOrderError
from headless.operation_admission_store import (
    OperationAdmissionStoreError,
    persist_or_replay_operation_admission_v3,
)


def _fork_validate(lock: object, output: object) -> None:
    try:
        validate_cross_ledger_order_lock_v1(lock)
    except CrossLedgerOrderLockError:
        output.send("rejected")
    else:
        output.send("accepted")
    output.close()


def _direct_worker(
    request: object, acquired: object, release: object, output: object
) -> None:
    from headless import operation_admission_transaction as module

    original = module.require_cross_ledger_order_allows_admission_v1

    def pause(lock: object, admission: object) -> tuple[str, ...]:
        acquired.set()
        if not release.wait(5):
            raise RuntimeError("race release timed out")
        return original(lock, admission)

    try:
        with patch.object(
            module,
            "require_cross_ledger_order_allows_admission_v1",
            side_effect=pause,
        ):
            result = persist_or_replay_operation_admission_v3(
                request.admission
            )
        output.put(("direct", result.created))
    except Exception as exc:  # pragma: no cover - asserted in parent
        output.put(("direct-error", type(exc).__name__))


def _ordered_worker(request: object, done: object, output: object) -> None:
    try:
        result = persist_or_replay_cross_ledger_ordered_admission_v1(request)
        output.put(("ordered", result.state))
    except CrossLedgerOrderError:
        output.put(("ordered-rejected", True))
    finally:
        done.set()


class CrossLedgerOrderAdversarialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CrossLedgerOrderFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_forged_stale_and_fork_inherited_lock_witnesses_fail(self) -> None:
        stale = None
        context = multiprocessing.get_context("fork")
        with locked_cross_ledger_order_root_v1(self.fixture.root) as lock:
            forged = dataclasses.replace(lock)
            with self.assertRaises(CrossLedgerOrderLockError):
                validate_cross_ledger_order_lock_v1(forged)
            receiver, sender = context.Pipe(duplex=False)
            process = context.Process(
                target=_fork_validate, args=(lock, sender)
            )
            process.start()
            self.assertEqual(receiver.recv(), "rejected")
            process.join(5)
            self.assertEqual(process.exitcode, 0)
            stale = lock
        with self.assertRaises(CrossLedgerOrderLockError):
            validate_cross_ledger_order_lock_v1(stale)

    def test_direct_admission_holds_outer_lock_across_absence_window(
        self,
    ) -> None:
        context = multiprocessing.get_context("fork")
        request = self.fixture.request()
        acquired, release, ordered_done = (
            context.Event(),
            context.Event(),
            context.Event(),
        )
        output = context.Queue()
        direct = context.Process(
            target=_direct_worker,
            args=(request, acquired, release, output),
        )
        direct.start()
        self.assertTrue(acquired.wait(5))
        ordered = context.Process(
            target=_ordered_worker,
            args=(request, ordered_done, output),
        )
        ordered.start()
        self.assertFalse(ordered_done.wait(0.3))
        release.set()
        direct.join(5)
        ordered.join(5)
        self.assertEqual(direct.exitcode, 0)
        self.assertEqual(ordered.exitcode, 0)
        results = {output.get(timeout=2)[0] for _ in range(2)}
        self.assertEqual(results, {"direct", "ordered-rejected"})

    def test_protocol_does_not_self_deadlock_on_outer_lock(self) -> None:
        context = multiprocessing.get_context("fork")
        done, output = context.Event(), context.Queue()
        process = context.Process(
            target=_ordered_worker,
            args=(self.fixture.request(), done, output),
        )
        process.start()
        self.assertTrue(done.wait(5))
        process.join(5)
        self.assertEqual(process.exitcode, 0)
        self.assertEqual(output.get(timeout=2)[0], "ordered")

    def test_concurrent_exact_protocol_calls_commit_then_replay(self) -> None:
        context = multiprocessing.get_context("fork")
        output = context.Queue()
        processes = []
        for _ in range(2):
            done = context.Event()
            process = context.Process(
                target=_ordered_worker,
                args=(self.fixture.request(), done, output),
            )
            process.start()
            processes.append(process)
        for process in processes:
            process.join(5)
            self.assertEqual(process.exitcode, 0)
        states = {output.get(timeout=2)[1] for _ in processes}
        self.assertEqual(states, {"committed", "replay"})

    def test_symlink_fifo_and_torn_receipt_bytes_fail_closed(self) -> None:
        result = self.fixture.persist()
        store = os.path.join(self.fixture.root, "cross-ledger-orders-v1")
        record = os.listdir(store)[0]
        receipt = os.path.join(store, record, "receipt.json")
        for kind in ("symlink", "fifo"):
            with self.subTest(kind=kind):
                os.unlink(receipt)
                if kind == "symlink":
                    os.symlink("intent.json", receipt)
                else:
                    os.mkfifo(receipt, 0o600)
                with self.assertRaises(CrossLedgerOrderError):
                    reobserve_cross_ledger_order_state_v1(
                        self.fixture.root, result.intent.identity
                    )
                os.unlink(receipt)
                receipt_raw = result.receipt.document_json
                with open(receipt, "wb") as output:
                    output.write(receipt_raw)
                os.chmod(receipt, 0o600)
        os.unlink(receipt)
        pending = os.path.join(store, record, ".receipt.pending")
        with open(pending, "wb") as output:
            output.write(b"{}\n")
        os.chmod(pending, 0o600)
        with self.assertRaises(CrossLedgerOrderError):
            self.fixture.persist()

    def test_torn_pending_record_fails_without_admission_residue(self) -> None:
        store = os.path.join(self.fixture.root, "cross-ledger-orders-v1")
        os.mkdir(store, 0o700)
        os.mkdir(os.path.join(store, ".pending-hostile"), 0o700)
        with self.assertRaises(CrossLedgerOrderError):
            self.fixture.persist()
        self.assertFalse(
            os.path.exists(
                os.path.join(self.fixture.root, "operation-admissions-v3")
            )
        )

    def test_late_mutation_of_earlier_record_fails_second_pass(self) -> None:
        from headless import cross_ledger_order_store as store_module

        first = self.fixture.persist()
        self.fixture.persist(second=True)
        store = os.path.join(self.fixture.root, "cross-ledger-orders-v1")
        first_name = store_module.cross_ledger_order_record_name_v1(
            first.intent.identity.idempotency_key
        )
        receipt = os.path.join(store, first_name, "receipt.json")
        original = store_module.load_cross_ledger_order_record_v1
        calls = 0

        def mutate_after_first_pass(store_fd: int, name: str):
            nonlocal calls
            observed = original(store_fd, name)
            calls += 1
            if calls == 2:
                with open(receipt, "wb") as output:
                    output.write(b"{}\n")
            return observed

        with patch.object(
            store_module,
            "load_cross_ledger_order_record_v1",
            side_effect=mutate_after_first_pass,
        ), self.assertRaises(CrossLedgerOrderError):
            self.fixture.persist()

    def test_cross_order_capacity_fails_before_second_record_creation(
        self,
    ) -> None:
        from headless import cross_ledger_order_store as store_module

        with patch.object(store_module, "_MAX_RECORDS", 1):
            self.fixture.persist()
            with self.assertRaises(CrossLedgerOrderError):
                self.fixture.persist(second=True)
        store = os.path.join(self.fixture.root, "cross-ledger-orders-v1")
        self.assertEqual(len(os.listdir(store)), 1)

    def test_operation_capacity_fails_before_second_admission_creation(
        self,
    ) -> None:
        from headless import operation_admission_transaction as store_module

        first = self.fixture.request().admission
        second = self.fixture.request(second=True).admission
        with patch.object(store_module, "_MAX_RECORDS", 1):
            persist_or_replay_operation_admission_v3(first)
            with self.assertRaises(OperationAdmissionStoreError):
                persist_or_replay_operation_admission_v3(second)
        store = os.path.join(self.fixture.root, "operation-admissions-v3")
        self.assertEqual(len(os.listdir(store)), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
