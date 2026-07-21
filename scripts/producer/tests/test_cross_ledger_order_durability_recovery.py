"""Power-loss barriers and deterministic receipt recovery tests."""

from __future__ import annotations

import os
import unittest
from collections.abc import Callable
from unittest.mock import patch

from _common import pl  # noqa: F401
from _cross_ledger_order_fixture import CrossLedgerOrderFixture
from headless import cross_ledger_order_store_write as writer
from headless.cross_ledger_order_schema import (
    build_cross_ledger_order_receipt_v1,
    parse_cross_ledger_order_document_v1,
)
from headless.cross_ledger_order_types import (
    CrossLedgerOrderError,
    CrossLedgerOrderPermanentRejectionV1,
)
from headless.durable_files import open_private_file, write_all
from headless.operation_admission_store import (
    persist_or_replay_operation_admission_v3,
)


def _record_paths(fixture: CrossLedgerOrderFixture) -> tuple[str, str]:
    store = os.path.join(fixture.root, "cross-ledger-orders-v1")
    record = os.path.join(store, os.listdir(store)[0])
    return store, record


def _receipt_write_crash(
    fixture: CrossLedgerOrderFixture, prefix: Callable[[bytes], bytes]
) -> None:
    original = writer._write_file
    tripped = False

    def interrupt(dir_fd: int, name: str, raw: bytes) -> None:
        nonlocal tripped
        if name != writer.RECEIPT_PENDING or tripped:
            original(dir_fd, name, raw)
            return
        tripped = True
        fd = open_private_file(
            dir_fd, name, os.O_WRONLY | os.O_CREAT | os.O_EXCL
        )
        try:
            write_all(fd, prefix(raw))
        finally:
            os.close(fd)
        raise OSError("simulated crash before receipt fsync")

    with patch.object(writer, "_write_file", side_effect=interrupt):
        with unittest.TestCase().assertRaises(CrossLedgerOrderError):
            fixture.persist()


def _inode(path: str) -> tuple[int, int]:
    info = os.stat(path, follow_symlinks=False)
    return info.st_dev, info.st_ino


def _fsync_spy(
    *identities: tuple[int, int],
) -> tuple[dict[tuple[int, int], int], Callable]:
    original = os.fsync
    hits = {identity: 0 for identity in identities}

    def spy(fd: int) -> None:
        info = os.fstat(fd)
        identity = (info.st_dev, info.st_ino)
        if identity in hits:
            hits[identity] += 1
        original(fd)

    return hits, spy


class CrossLedgerOrderDurabilityRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CrossLedgerOrderFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_strict_prefix_receipt_is_rebuilt_and_committed(self) -> None:
        _receipt_write_crash(self.fixture, lambda raw: raw[:17])
        _store, record = _record_paths(self.fixture)
        self.assertEqual(
            sorted(os.listdir(record)),
            [writer.RECEIPT_PENDING, writer.INTENT_NAME],
        )
        recovered = self.fixture.persist()
        self.assertEqual(recovered.state, "committed")
        self.assertEqual(
            sorted(os.listdir(record)),
            [writer.INTENT_NAME, writer.RECEIPT_NAME],
        )

    def test_full_unflushed_receipt_is_resynced_before_promotion(self) -> None:
        _receipt_write_crash(self.fixture, lambda raw: raw)
        _store, record = _record_paths(self.fixture)
        pending = os.path.join(record, writer.RECEIPT_PENDING)
        pending_inode = _inode(pending)
        hits, spy = _fsync_spy(pending_inode)
        with patch.object(writer.os, "fsync", side_effect=spy):
            recovered = self.fixture.persist()
        self.assertEqual(recovered.state, "committed")
        self.assertGreaterEqual(hits[pending_inode], 2)

    def test_complete_conflicting_receipt_is_not_rebuilt(self) -> None:
        _receipt_write_crash(self.fixture, lambda raw: raw[:17])
        _store, record = _record_paths(self.fixture)
        intent_path = os.path.join(record, writer.INTENT_NAME)
        with open(intent_path, "rb") as source:
            intent = parse_cross_ledger_order_document_v1(source.read())
        conflicting = build_cross_ledger_order_receipt_v1(
            intent.identity, "0" * 64
        )
        pending = os.path.join(record, writer.RECEIPT_PENDING)
        with open(pending, "wb") as output:
            output.write(conflicting)
        os.chmod(pending, 0o600)
        with self.assertRaises(CrossLedgerOrderError):
            self.fixture.persist()
        with open(pending, "rb") as source:
            self.assertEqual(source.read(), conflicting)

    def test_nonregular_incomplete_receipt_is_not_rebuilt(self) -> None:
        for kind in ("symlink", "fifo"):
            with self.subTest(kind=kind):
                fixture = CrossLedgerOrderFixture()
                self.addCleanup(fixture.close)
                _receipt_write_crash(fixture, lambda raw: raw[:17])
                _store, record = _record_paths(fixture)
                pending = os.path.join(record, writer.RECEIPT_PENDING)
                os.unlink(pending)
                if kind == "symlink":
                    os.symlink(writer.INTENT_NAME, pending)
                else:
                    os.mkfifo(pending, 0o600)
                with self.assertRaises(CrossLedgerOrderError):
                    fixture.persist()
                self.assertTrue(
                    os.path.islink(pending) or not os.path.isfile(pending)
                )

    def test_oversize_incomplete_receipt_is_not_rebuilt(self) -> None:
        _receipt_write_crash(self.fixture, lambda raw: raw[:17])
        _store, record = _record_paths(self.fixture)
        pending = os.path.join(record, writer.RECEIPT_PENDING)
        with open(pending, "wb") as output:
            output.write(b"x" * 16_385)
        os.chmod(pending, 0o600)
        with self.assertRaises(CrossLedgerOrderError):
            self.fixture.persist()
        self.assertEqual(os.path.getsize(pending), 16_385)

    def test_visible_prepared_record_parent_is_resynced(self) -> None:
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
                raise OSError("simulated parent fsync failure")
            original_fsync(fd)

        with patch.object(
            writer.os, "rename", side_effect=rename
        ), patch.object(
            writer.os, "fsync", side_effect=fail_after_rename
        ), self.assertRaises(
            CrossLedgerOrderError
        ):
            self.fixture.persist()
        store, record = _record_paths(self.fixture)
        store_inode, record_inode = _inode(store), _inode(record)
        hits, spy = _fsync_spy(store_inode, record_inode)
        with patch.object(writer.os, "fsync", side_effect=spy):
            recovered = self.fixture.persist()
        self.assertEqual(recovered.state, "committed")
        self.assertGreaterEqual(hits[store_inode], 1)
        self.assertGreaterEqual(hits[record_inode], 1)

    def test_visible_committed_record_directory_is_resynced(self) -> None:
        original_rename, original_fsync = os.rename, os.fsync
        renamed, failed = False, False

        def rename(src: str, dst: str, **kwargs: object) -> None:
            nonlocal renamed
            original_rename(src, dst, **kwargs)
            if src == writer.RECEIPT_PENDING:
                renamed = True

        def fail_after_rename(fd: int) -> None:
            nonlocal failed
            if renamed and not failed:
                failed = True
                raise OSError("simulated record fsync failure")
            original_fsync(fd)

        with patch.object(
            writer.os, "rename", side_effect=rename
        ), patch.object(
            writer.os, "fsync", side_effect=fail_after_rename
        ), self.assertRaises(
            CrossLedgerOrderError
        ):
            self.fixture.persist()
        store, record = _record_paths(self.fixture)
        store_inode, record_inode = _inode(store), _inode(record)
        hits, spy = _fsync_spy(store_inode, record_inode)
        with patch.object(writer.os, "fsync", side_effect=spy):
            recovered = self.fixture.persist()
        self.assertEqual(recovered.state, "replay")
        self.assertGreaterEqual(hits[store_inode], 1)
        self.assertGreaterEqual(hits[record_inode], 1)

    def test_visible_rejection_parent_is_resynced(self) -> None:
        request = self.fixture.request()
        persist_or_replay_operation_admission_v3(request.admission)
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
                raise OSError("simulated rejection parent fsync failure")
            original_fsync(fd)

        with patch.object(
            writer.os, "rename", side_effect=rename
        ), patch.object(
            writer.os, "fsync", side_effect=fail_after_rename
        ), self.assertRaises(
            CrossLedgerOrderError
        ):
            self.fixture.persist()
        store, record = _record_paths(self.fixture)
        store_inode, record_inode = _inode(store), _inode(record)
        hits, spy = _fsync_spy(store_inode, record_inode)
        with patch.object(
            writer.os, "fsync", side_effect=spy
        ), self.assertRaises(CrossLedgerOrderPermanentRejectionV1):
            self.fixture.persist()
        self.assertGreaterEqual(hits[store_inode], 1)
        self.assertGreaterEqual(hits[record_inode], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
