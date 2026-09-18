"""Crash points, recovery barriers, and no-inferred-release tests."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from _active_fence_fixture import ActiveFenceFixture
from _common import pl  # noqa: F401
from headless import active_fence_journal as journal
from headless import active_fence_materialized as materialized
from headless.active_fence_types import (
    ActiveFenceConflictError,
    ActiveFenceError,
)
from headless.durable_files import open_private_file, write_all


def _inode(path: str) -> tuple[int, int]:
    info = os.stat(path, follow_symlinks=False)
    return info.st_dev, info.st_ino


def _tear_append(prefix_bytes: int):
    original = journal.write_all
    tripped = False

    def tear(fd: int, data: bytes) -> None:
        nonlocal tripped
        if tripped:
            original(fd, data)
            return
        tripped = True
        original(fd, data[:prefix_bytes])
        raise OSError("simulated crash during active-fence append")

    return tear


def _write_pending_then_crash(
    root_fd: int, names: tuple[str, str], raw: bytes
) -> None:
    pending, _final = names
    fd = open_private_file(
        root_fd, pending, os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    )
    try:
        write_all(fd, raw[:17])
        os.fsync(fd)
    finally:
        os.close(fd)
    raise OSError("simulated crash before FENCE rename")


def _replace_then_crash(
    root_fd: int, names: tuple[str, str], raw: bytes
) -> None:
    pending, final = names
    fd = open_private_file(
        root_fd, pending, os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    )
    try:
        write_all(fd, raw)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(pending, final, src_dir_fd=root_fd, dst_dir_fd=root_fd)
    raise OSError("simulated crash before post-rename root fsync")


class ActiveFenceCrashRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = ActiveFenceFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_torn_reserve_is_discarded_as_never_committed(self) -> None:
        self.fixture.bootstrap()
        with patch.object(
            journal, "write_all", side_effect=_tear_append(31)
        ), self.assertRaises(ActiveFenceError):
            self.fixture.reserve()
        self.assertIsNone(
            materialized.parse_active_fence_document_v1(
                self.fixture.fence_bytes()
            ).active_attempt_id
        )
        recovered = self.fixture.reserve(self.fixture.attempt_b)
        self.assertEqual(
            recovered.state.active_attempt_id, self.fixture.attempt_b
        )
        self.assertEqual(len(self.fixture.journal_bytes().splitlines()), 2)

    def test_torn_cancel_never_infers_release(self) -> None:
        self.fixture.bootstrap()
        active = self.fixture.reserve()
        with patch.object(
            journal, "write_all", side_effect=_tear_append(29)
        ), self.assertRaises(ActiveFenceError):
            self.fixture.cancel()
        self.assertEqual(
            self.fixture.fence_bytes(), active.state.document_json
        )
        with self.assertRaises(ActiveFenceConflictError):
            self.fixture.reserve(self.fixture.attempt_b)
        self.assertEqual(
            materialized.parse_active_fence_document_v1(
                self.fixture.fence_bytes()
            ).active_attempt_id,
            self.fixture.attempt_a,
        )
        canceled = self.fixture.cancel()
        self.assertIsNone(canceled.state.active_attempt_id)

    def test_complete_malformed_cancel_is_corruption_not_torn_tail(
        self,
    ) -> None:
        self.fixture.bootstrap()
        active = self.fixture.reserve()

        def corrupt(fd: int, _data: bytes) -> None:
            write_all(fd, b"{}\n")
            raise OSError("simulated complete corrupt append")

        with patch.object(
            journal, "write_all", side_effect=corrupt
        ), self.assertRaises(ActiveFenceError):
            self.fixture.cancel()
        with self.assertRaises(ActiveFenceError):
            self.fixture.cancel()
        self.assertEqual(
            self.fixture.fence_bytes(), active.state.document_json
        )

    def test_visible_frame_after_fdatasync_error_is_resynced(self) -> None:
        self.fixture.bootstrap()
        sync_name = (
            "fdatasync" if hasattr(journal.os, "fdatasync") else "fsync"
        )
        original = getattr(journal.os, sync_name)
        journal_identity = _inode(self.fixture.journal_path)
        calls = 0

        def fail_once(fd: int) -> None:
            nonlocal calls
            if _fd_identity(fd) == journal_identity:
                calls += 1
            if calls == 2 and _fd_identity(fd) == journal_identity:
                raise OSError("simulated journal fdatasync failure")
            original(fd)

        with patch.object(journal.os, sync_name, side_effect=fail_once):
            with self.assertRaises(ActiveFenceError):
                self.fixture.reserve()
        hits = 0

        def spy(fd: int) -> None:
            nonlocal hits
            if _inode(self.fixture.journal_path) == _fd_identity(fd):
                hits += 1
            original(fd)

        with patch.object(journal.os, sync_name, side_effect=spy):
            replay = self.fixture.reserve()
        self.assertTrue(replay.replayed)
        self.assertGreaterEqual(hits, 1)

    def test_journal_append_before_projection_recovers_exact_active(
        self,
    ) -> None:
        bootstrap = self.fixture.bootstrap()
        with patch.object(
            materialized,
            "write_pending_replace",
            side_effect=OSError("simulated projection failure"),
        ), self.assertRaises(ActiveFenceError):
            self.fixture.reserve()
        self.assertEqual(
            self.fixture.fence_bytes(), bootstrap.state.document_json
        )
        recovered = self.fixture.reserve()
        self.assertTrue(recovered.replayed)
        self.assertEqual(
            recovered.state.active_attempt_id, self.fixture.attempt_a
        )

    def test_torn_pending_projection_is_rebuilt_from_journal(self) -> None:
        self.fixture.bootstrap()
        with patch.object(
            materialized,
            "write_pending_replace",
            side_effect=_write_pending_then_crash,
        ), self.assertRaises(ActiveFenceError):
            self.fixture.reserve()
        pending = os.path.join(self.fixture.root, ".FENCE.pending")
        self.assertTrue(os.path.exists(pending))
        recovered = self.fixture.reserve()
        self.assertTrue(recovered.replayed)
        self.assertFalse(os.path.exists(pending))
        self.assertEqual(
            recovered.state.active_attempt_id, self.fixture.attempt_a
        )

    def test_replaced_fence_after_root_fsync_error_is_reflushed(self) -> None:
        self.fixture.bootstrap()
        with patch.object(
            materialized,
            "write_pending_replace",
            side_effect=_replace_then_crash,
        ), self.assertRaises(ActiveFenceError):
            self.fixture.reserve()
        fence_identity = _inode(self.fixture.fence_path)
        original = materialized.os.fsync
        hits = 0

        def spy(fd: int) -> None:
            nonlocal hits
            if _fd_identity(fd) == fence_identity:
                hits += 1
            original(fd)

        with patch.object(materialized.os, "fsync", side_effect=spy):
            replay = self.fixture.reserve()
        self.assertTrue(replay.replayed)
        self.assertGreaterEqual(hits, 1)

    def test_missing_projection_after_reservation_is_not_recreated(
        self,
    ) -> None:
        self.fixture.bootstrap()
        self.fixture.reserve()
        os.unlink(self.fixture.fence_path)
        with self.assertRaises(ActiveFenceError):
            self.fixture.bootstrap()
        self.assertEqual(len(self.fixture.journal_bytes().splitlines()), 2)

    def test_projection_without_journal_is_not_rebootstrapped(self) -> None:
        self.fixture.bootstrap()
        os.unlink(self.fixture.journal_path)
        with self.assertRaises(ActiveFenceError):
            self.fixture.bootstrap()
        self.assertFalse(os.path.exists(self.fixture.journal_path))

    def test_journal_inode_swap_across_resync_barrier_fails(self) -> None:
        self.fixture.bootstrap()
        raw = self.fixture.journal_bytes()
        identity = _inode(self.fixture.journal_path)
        sync_name = (
            "fdatasync" if hasattr(journal.os, "fdatasync") else "fsync"
        )
        original = getattr(journal.os, sync_name)
        swapped = False

        def attack(fd: int) -> None:
            nonlocal swapped
            original(fd)
            if not swapped and _fd_identity(fd) == identity:
                swapped = True
                os.unlink(self.fixture.journal_path)
                with open(self.fixture.journal_path, "wb") as output:
                    output.write(raw)
                os.chmod(self.fixture.journal_path, 0o600)

        with patch.object(journal.os, sync_name, side_effect=attack):
            with self.assertRaises(ActiveFenceError):
                self.fixture.reserve()

    def test_fence_inode_swap_across_resync_barrier_fails(self) -> None:
        self.fixture.bootstrap()
        raw = self.fixture.fence_bytes()
        identity = _inode(self.fixture.fence_path)
        original = materialized.os.fsync
        swapped = False

        def attack(fd: int) -> None:
            nonlocal swapped
            original(fd)
            if not swapped and _fd_identity(fd) == identity:
                swapped = True
                os.unlink(self.fixture.fence_path)
                with open(self.fixture.fence_path, "wb") as output:
                    output.write(raw)
                os.chmod(self.fixture.fence_path, 0o600)

        with patch.object(materialized.os, "fsync", side_effect=attack):
            with self.assertRaises(ActiveFenceError):
                self.fixture.bootstrap()


def _fd_identity(fd: int) -> tuple[int, int]:
    info = os.fstat(fd)
    return info.st_dev, info.st_ino


if __name__ == "__main__":
    unittest.main(verbosity=2)
