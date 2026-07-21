"""Safety and cost bounds for targeted order durability recovery."""

from __future__ import annotations

import os
import shutil
import unittest
from collections.abc import Callable
from unittest.mock import patch

from _common import pl  # noqa: F401
from _cross_ledger_order_fixture import CrossLedgerOrderFixture
from headless import cross_ledger_order_barrier as barrier
from headless import cross_ledger_order_store_write as writer
from headless.cross_ledger_order_barrier import (
    load_writer_durable_cross_ledger_order_state_v1,
)
from headless.cross_ledger_order_fs import (
    cross_ledger_order_record_name_v1,
)
from headless.cross_ledger_order_lock import (
    locked_cross_ledger_order_root_v1,
)
from headless.cross_ledger_order_pending import (
    cleanup_abandoned_cross_ledger_order_pending_v1,
)
from headless.cross_ledger_order_protocol import _identity
from headless.cross_ledger_order_store import (
    persist_cross_ledger_order_prepared_v1,
    reject_prepared_cross_ledger_order_v1,
)
from headless.cross_ledger_order_types import (
    CrossLedgerOrderError,
    CrossLedgerOrderPermanentRejectionV1,
)
from headless.durable_files import open_private_file, write_all
from headless.operation_admission_store import (
    persist_or_replay_operation_admission_v3,
)


def _cross_paths(fixture: CrossLedgerOrderFixture) -> tuple[str, str]:
    store = os.path.join(fixture.root, writer.STORE_NAME)
    record = os.path.join(store, os.listdir(store)[0])
    return store, record


def _leave_partial_receipt(fixture: CrossLedgerOrderFixture) -> str:
    original = writer._write_file

    def interrupt(dir_fd: int, name: str, raw: bytes) -> None:
        if name != writer.RECEIPT_PENDING:
            original(dir_fd, name, raw)
            return
        fd = open_private_file(
            dir_fd, name, os.O_WRONLY | os.O_CREAT | os.O_EXCL
        )
        try:
            write_all(fd, raw[:17])
        finally:
            os.close(fd)
        raise OSError("simulated partial receipt write")

    with patch.object(writer, "_write_file", side_effect=interrupt):
        with unittest.TestCase().assertRaises(CrossLedgerOrderError):
            fixture.persist()
    _store, record = _cross_paths(fixture)
    return os.path.join(record, writer.RECEIPT_PENDING)


def _fsync_counts(
    paths: tuple[str, ...],
) -> tuple[dict[str, int], Callable[[int], None]]:
    original = os.fsync
    identities = {
        (os.stat(path).st_dev, os.stat(path).st_ino): path for path in paths
    }
    hits = {path: 0 for path in paths}

    def spy(fd: int) -> None:
        info = os.fstat(fd)
        path = identities.get((info.st_dev, info.st_ino))
        if path is not None:
            hits[path] += 1
        original(fd)

    return hits, spy


class CrossLedgerOrderRecoverySafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CrossLedgerOrderFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_replay_does_not_fsync_an_unrelated_final_record(self) -> None:
        self.fixture.persist()
        self.fixture.persist(second=True)
        first = self.fixture.request().admission.admission.idempotency_key
        second = self.fixture.request(True).admission.admission.idempotency_key
        store = os.path.join(self.fixture.root, writer.STORE_NAME)
        relevant = os.path.join(
            store, cross_ledger_order_record_name_v1(first)
        )
        unrelated = os.path.join(
            store, cross_ledger_order_record_name_v1(second)
        )
        unrelated_paths = (
            unrelated,
            os.path.join(unrelated, writer.INTENT_NAME),
            os.path.join(unrelated, writer.RECEIPT_NAME),
        )
        paths = (store, relevant, *unrelated_paths)
        hits, spy = _fsync_counts(paths)
        with patch.object(writer.os, "fsync", side_effect=spy):
            replay = self.fixture.persist()
        self.assertEqual(replay.state, "replay")
        self.assertGreater(hits[store], 0)
        self.assertGreater(hits[relevant], 0)
        self.assertTrue(all(hits[path] == 0 for path in unrelated_paths))

    def test_unsafe_pending_mode_is_preserved(self) -> None:
        pending = _leave_partial_receipt(self.fixture)
        os.chmod(pending, 0o644)
        with self.assertRaises(CrossLedgerOrderError):
            self.fixture.persist()
        self.assertEqual(os.stat(pending).st_mode & 0o777, 0o644)

    def test_hard_linked_pending_receipt_is_preserved(self) -> None:
        pending = _leave_partial_receipt(self.fixture)
        linked = os.path.join(self.fixture.root, "linked-receipt")
        os.link(pending, linked)
        with self.assertRaises(CrossLedgerOrderError):
            self.fixture.persist()
        self.assertEqual(os.stat(pending).st_nlink, 2)
        self.assertTrue(os.path.exists(linked))

    def test_unknown_record_closure_is_preserved(self) -> None:
        pending = _leave_partial_receipt(self.fixture)
        unknown = os.path.join(os.path.dirname(pending), "unknown.bin")
        with open(unknown, "wb") as output:
            output.write(b"unknown")
        os.chmod(unknown, 0o600)
        with self.assertRaises(CrossLedgerOrderError):
            self.fixture.persist()
        self.assertTrue(os.path.exists(pending))
        self.assertTrue(os.path.exists(unknown))

    def test_nonprefix_partial_receipt_is_preserved(self) -> None:
        pending = _leave_partial_receipt(self.fixture)
        with open(pending, "wb") as output:
            output.write(b"not-a-receipt-prefix")
        os.chmod(pending, 0o600)
        with self.assertRaises(CrossLedgerOrderError):
            self.fixture.persist()
        with open(pending, "rb") as source:
            self.assertEqual(source.read(), b"not-a-receipt-prefix")

    def test_named_record_swap_fails_the_targeted_barrier(self) -> None:
        self.fixture.persist()
        _store, record = _cross_paths(self.fixture)
        replacement = os.path.join(self.fixture.root, "replacement-record")
        displaced = os.path.join(self.fixture.root, "displaced-record")
        shutil.copytree(record, replacement)
        original = barrier._all_states
        calls = 0

        def swap(lock: object, authority_id: str) -> object:
            nonlocal calls
            calls += 1
            if calls == 2:
                os.rename(record, displaced)
                os.rename(replacement, record)
            return original(lock, authority_id)

        with patch.object(barrier, "_all_states", side_effect=swap):
            with self.assertRaises(CrossLedgerOrderError):
                self.fixture.persist()
        self.assertEqual(calls, 2)
        self.assertTrue(os.path.isdir(record))
        self.assertTrue(os.path.isdir(displaced))

    def test_visible_appended_rejection_is_reflushed(self) -> None:
        identity = _identity(self.fixture.request())
        with locked_cross_ledger_order_root_v1(self.fixture.root) as lock:
            cleanup_abandoned_cross_ledger_order_pending_v1(lock)
            persist_cross_ledger_order_prepared_v1(lock, identity)
        store, record = _cross_paths(self.fixture)
        record_identity = (
            os.stat(record).st_dev,
            os.stat(record).st_ino,
        )
        original, failed = os.fsync, False

        def fail_record_fsync(fd: int) -> None:
            nonlocal failed
            info = os.fstat(fd)
            current = (info.st_dev, info.st_ino)
            if current == record_identity and not failed:
                failed = True
                raise OSError("simulated rejection directory fsync failure")
            original(fd)

        with locked_cross_ledger_order_root_v1(self.fixture.root) as lock:
            with patch.object(
                writer.os, "fsync", side_effect=fail_record_fsync
            ):
                with self.assertRaises(CrossLedgerOrderError):
                    reject_prepared_cross_ledger_order_v1(lock, identity)
        self.assertTrue(failed)
        self.assertEqual(
            sorted(os.listdir(record)),
            [writer.INTENT_NAME, writer.REJECTION_NAME],
        )
        paths = (store, record)
        hits, spy = _fsync_counts(paths)
        with patch.object(writer.os, "fsync", side_effect=spy):
            with locked_cross_ledger_order_root_v1(self.fixture.root) as lock:
                cleanup_abandoned_cross_ledger_order_pending_v1(lock)
                with self.assertRaises(CrossLedgerOrderPermanentRejectionV1):
                    load_writer_durable_cross_ledger_order_state_v1(
                        lock, identity
                    )
        self.assertGreater(hits[store], 0)
        self.assertGreater(hits[record], 0)

    def test_direct_admission_guard_reflushes_visible_prepared(self) -> None:
        original_rename, original_fsync = os.rename, os.fsync
        renamed, failed = False, False

        def rename(src: str, dst: str, **kwargs: object) -> None:
            nonlocal renamed
            original_rename(src, dst, **kwargs)
            if src.startswith(".pending-"):
                renamed = True

        def fail_after_rename(fd: int) -> None:
            nonlocal failed
            if renamed and not failed:
                failed = True
                raise OSError("simulated prepared parent fsync failure")
            original_fsync(fd)

        with patch.object(
            writer.os, "rename", side_effect=rename
        ), patch.object(
            writer.os, "fsync", side_effect=fail_after_rename
        ), self.assertRaises(
            CrossLedgerOrderError
        ):
            self.fixture.persist()
        store, record = _cross_paths(self.fixture)
        paths = (store, record)
        hits, spy = _fsync_counts(paths)
        with patch.object(writer.os, "fsync", side_effect=spy):
            admitted = persist_or_replay_operation_admission_v3(
                self.fixture.request().admission
            )
        self.assertTrue(admitted.created)
        self.assertGreater(hits[store], 0)
        self.assertGreater(hits[record], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
