"""Crash ambiguity and no-overwrite tests for order-start intents."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from _common import pl  # noqa: F401
from _fence_admission_reservation_fixture import same_file
from _fence_order_start_fixture import FenceOrderStartFixture
from headless import fence_order_start_pending as pending_io
from headless import fence_order_start_records as records_io
from headless.cross_ledger_order_store import (
    persist_cross_ledger_order_prepared_v1,
)
from headless.fence_order_start_schema import (
    build_fence_order_start_intent_v1,
)
from headless.fence_order_start_store import (
    STORE_NAME,
    FenceOrderStartConflictV1,
    FenceOrderStartError,
    reobserve_fence_order_start_v1,
)


class FenceOrderStartRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = FenceOrderStartFixture()
        self.addCleanup(self.fixture.close)

    def _paths(self) -> tuple[str, str, str]:
        name = records_io.fence_order_start_record_name_v1(
            self.fixture.identity.attempt_id
        )
        store = os.path.join(self.fixture.root, STORE_NAME)
        return store, os.path.join(store, name), f".pending-{name}"

    def _expected(self) -> bytes:
        return build_fence_order_start_intent_v1(
            self.fixture.reservation,
            self.fixture.fence,
            self.fixture.identity,
        ).document_json

    def test_visible_final_after_failed_directory_fsync_replays(self) -> None:
        store, final, _ = self._paths()
        original = os.fsync
        failed = False

        def interrupt(fd: int) -> None:
            nonlocal failed
            if not failed and os.path.exists(final) and same_file(fd, store):
                failed = True
                raise OSError("simulated visible-final fsync failure")
            original(fd)

        with patch.object(pending_io.os, "fsync", side_effect=interrupt):
            with self.assertRaises(FenceOrderStartError):
                self.fixture.persist()
        self.assertTrue(failed)
        self.assertTrue(os.path.isfile(final))
        synced = {"file": False, "store": False}

        def track(fd: int) -> None:
            synced["file"] |= same_file(fd, final)
            synced["store"] |= same_file(fd, store)
            original(fd)

        with patch.object(records_io.os, "fsync", side_effect=track):
            replayed = self.fixture.persist()
        self.assertFalse(replayed.created)
        self.assertEqual(synced, {"file": True, "store": True})

    def test_crash_before_link_recovers_complete_pending(self) -> None:
        store, final, pending = self._paths()
        with patch.object(
            pending_io.os, "link", side_effect=OSError("before link")
        ):
            with self.assertRaises(FenceOrderStartError):
                self.fixture.persist()
        pending_path = os.path.join(store, pending)
        self.assertTrue(os.path.isfile(pending_path))
        self.assertFalse(os.path.exists(final))
        replayed = self.fixture.persist()
        self.assertFalse(replayed.created)
        self.assertFalse(os.path.exists(pending_path))
        self.assertTrue(os.path.isfile(final))

    def test_prepared_order_blocks_retroactive_pending_promotion(self) -> None:
        store, final, pending = self._paths()
        with patch.object(
            pending_io.os, "link", side_effect=OSError("before link")
        ):
            with self.assertRaises(FenceOrderStartError):
                self.fixture.persist()
        pending_path = os.path.join(store, pending)
        with self.fixture.locked_request() as request:
            state = persist_cross_ledger_order_prepared_v1(
                request.locks.cross_lock, self.fixture.identity
            )
        self.assertEqual(state.state, "prepared")
        with self.assertRaises(FenceOrderStartError):
            self.fixture.persist()
        self.assertTrue(os.path.isfile(pending_path))
        self.assertFalse(os.path.exists(final))

    def test_crash_after_visible_link_recovers_same_inode_pair(self) -> None:
        store, final, pending = self._paths()
        original = os.link

        def visible_then_fail(*args: object, **kwargs: object) -> None:
            original(*args, **kwargs)
            raise OSError("after visible link")

        with patch.object(
            pending_io.os, "link", side_effect=visible_then_fail
        ):
            with self.assertRaises(FenceOrderStartError):
                self.fixture.persist()
        pending_path = os.path.join(store, pending)
        self.assertEqual(os.stat(final).st_ino, os.stat(pending_path).st_ino)
        replayed = self.fixture.persist()
        self.assertFalse(replayed.created)
        self.assertFalse(os.path.exists(pending_path))
        self.assertEqual(os.stat(final).st_nlink, 1)

    def test_strict_prefix_recovers_but_read_does_not_heal_it(self) -> None:
        expected = self._expected()
        store, final, pending = self._paths()
        os.mkdir(store, 0o700)
        pending_path = os.path.join(store, pending)
        with open(pending_path, "wb") as output:
            output.write(expected[:40])
        os.chmod(pending_path, 0o600)
        with self.fixture.locked_request() as request:
            with self.assertRaises(FenceOrderStartError):
                reobserve_fence_order_start_v1(request)
        self.assertTrue(os.path.isfile(pending_path))
        self.assertFalse(os.path.exists(final))
        replayed = self.fixture.persist()
        self.assertFalse(replayed.created)
        self.assertFalse(os.path.exists(pending_path))

    def test_conflicting_final_is_never_overwritten(self) -> None:
        store, final, pending = self._paths()
        original = os.link
        marker = b"conflicting-start-final"

        def install_conflict(*args: object, **kwargs: object) -> None:
            destination = args[1]
            dir_fd = kwargs["dst_dir_fd"]
            fd = os.open(
                destination,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=dir_fd,
            )
            try:
                os.write(fd, marker)
            finally:
                os.close(fd)
            original(*args, **kwargs)

        with patch.object(pending_io.os, "link", side_effect=install_conflict):
            with self.assertRaises(FenceOrderStartConflictV1):
                self.fixture.persist()
        with open(final, "rb") as source:
            self.assertEqual(source.read(), marker)
        self.assertTrue(os.path.isfile(os.path.join(store, pending)))
        with self.assertRaises(FenceOrderStartConflictV1):
            self.fixture.persist()
        with open(final, "rb") as source:
            self.assertEqual(source.read(), marker)


if __name__ == "__main__":
    unittest.main(verbosity=2)
