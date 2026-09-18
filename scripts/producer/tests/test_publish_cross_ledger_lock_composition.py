"""Publisher-to-cross-ledger lock ordering and live-witness attacks."""

from __future__ import annotations

import dataclasses
import multiprocessing
import os
import unittest
from unittest.mock import patch

from _common import pl  # noqa: F401
from _cross_ledger_order_fixture import CrossLedgerOrderFixture
from headless.active_fence_lock import (
    locked_publish_mutex_v1,
    validate_active_fence_lock_v1,
)
from headless.cross_ledger_order_lock import (
    CrossLedgerOrderLockError,
    locked_cross_ledger_order_under_publish_mutex_v1,
    validate_cross_ledger_order_lock_v1,
)
from headless.cross_ledger_order_protocol import (
    build_cross_ledger_order_request_identity_v1,
    persist_or_replay_cross_ledger_ordered_admission_under_lock_v1,
    persist_or_replay_cross_ledger_ordered_admission_v1,
)
from headless.cross_ledger_order_types import CrossLedgerOrderError

build_order_identity = build_cross_ledger_order_request_identity_v1
persist_under_lock = (
    persist_or_replay_cross_ledger_ordered_admission_under_lock_v1
)
persist_ordered = persist_or_replay_cross_ledger_ordered_admission_v1


def _fork_acquire(publish_lock: object, output: object) -> None:
    try:
        with locked_cross_ledger_order_under_publish_mutex_v1(publish_lock):
            output.send("accepted")
    except CrossLedgerOrderLockError:
        output.send("rejected")
    finally:
        output.close()


def _fork_persist(request: object, cross_lock: object, output: object) -> None:
    try:
        persist_under_lock(request, cross_lock)
    except CrossLedgerOrderError:
        output.send("rejected")
    else:
        output.send("accepted")
    output.close()


class PublishCrossLedgerLockCompositionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CrossLedgerOrderFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_live_nested_lock_uses_same_root_fd_without_path_reopen(
        self,
    ) -> None:
        stale_cross = None
        with locked_publish_mutex_v1(self.fixture.root) as publish_lock:
            with patch(
                "headless.cross_ledger_order_lock.open_private_dir",
                side_effect=AssertionError("path reopen"),
            ):
                with locked_cross_ledger_order_under_publish_mutex_v1(
                    publish_lock
                ) as cross_lock:
                    validate_active_fence_lock_v1(publish_lock)
                    validate_cross_ledger_order_lock_v1(cross_lock)
                    self.assertEqual(
                        publish_lock.root_identity, cross_lock.root_identity
                    )
                    self.assertEqual(
                        os.fstat(publish_lock.root_fd).st_ino,
                        os.fstat(cross_lock.root_fd).st_ino,
                    )
                    stale_cross = cross_lock
            validate_active_fence_lock_v1(publish_lock)
            with self.assertRaises(CrossLedgerOrderLockError):
                validate_cross_ledger_order_lock_v1(stale_cross)

    def test_forged_stale_and_fork_inherited_publish_witnesses_fail(
        self,
    ) -> None:
        context = multiprocessing.get_context("fork")
        stale = None
        with locked_publish_mutex_v1(self.fixture.root) as publish_lock:
            forged = dataclasses.replace(publish_lock)
            with self.assertRaises(CrossLedgerOrderLockError):
                with locked_cross_ledger_order_under_publish_mutex_v1(forged):
                    pass
            receiver, sender = context.Pipe(duplex=False)
            process = context.Process(
                target=_fork_acquire, args=(publish_lock, sender)
            )
            process.start()
            self.assertEqual(receiver.recv(), "rejected")
            process.join(5)
            self.assertEqual(process.exitcode, 0)
            stale = publish_lock
        with self.assertRaises(CrossLedgerOrderLockError):
            with locked_cross_ledger_order_under_publish_mutex_v1(stale):
                pass

    def test_under_lock_protocol_never_reacquires_cross_lock(self) -> None:
        request = self.fixture.request()
        target = (
            "headless.cross_ledger_order_protocol."
            "locked_cross_ledger_order_root_v1"
        )
        with locked_publish_mutex_v1(self.fixture.root) as publish_lock:
            with locked_cross_ledger_order_under_publish_mutex_v1(
                publish_lock
            ) as cross_lock, patch(
                target, side_effect=AssertionError("lock reacquired")
            ):
                result = persist_under_lock(request, cross_lock)
        self.assertEqual(result.state, "committed")
        self.assertEqual(
            result.intent.identity,
            build_order_identity(request),
        )

    def test_under_lock_rejects_forged_stale_and_fork_witnesses(self) -> None:
        request = self.fixture.request()
        context = multiprocessing.get_context("fork")
        stale = None
        with locked_publish_mutex_v1(self.fixture.root) as publish_lock:
            with locked_cross_ledger_order_under_publish_mutex_v1(
                publish_lock
            ) as cross_lock:
                with self.assertRaises(CrossLedgerOrderError):
                    persist_under_lock(
                        request, dataclasses.replace(cross_lock)
                    )
                receiver, sender = context.Pipe(duplex=False)
                process = context.Process(
                    target=_fork_persist,
                    args=(request, cross_lock, sender),
                )
                process.start()
                self.assertEqual(receiver.recv(), "rejected")
                process.join(5)
                self.assertEqual(process.exitcode, 0)
                stale = cross_lock
        with self.assertRaises(CrossLedgerOrderError):
            persist_under_lock(request, stale)

    def test_root_swap_fails_before_any_inner_or_order_write(self) -> None:
        request = self.fixture.request()
        moved = f"{self.fixture.root}.retained"
        with locked_publish_mutex_v1(self.fixture.root) as publish_lock:
            with locked_cross_ledger_order_under_publish_mutex_v1(
                publish_lock
            ) as cross_lock:
                os.rename(self.fixture.root, moved)
                os.mkdir(self.fixture.root, 0o700)
                os.chmod(self.fixture.root, 0o700)
                try:
                    with self.assertRaises(CrossLedgerOrderError):
                        persist_under_lock(request, cross_lock)
                    self.assertFalse(
                        os.path.exists(
                            os.path.join(moved, "cross-ledger-orders-v1")
                        )
                    )
                    self.assertFalse(
                        os.path.exists(
                            os.path.join(moved, "operation-admissions-v3")
                        )
                    )
                finally:
                    os.rmdir(self.fixture.root)
                    os.rename(moved, self.fixture.root)

    def test_public_wrapper_still_commits_then_nested_api_replays(
        self,
    ) -> None:
        request = self.fixture.request()
        created = persist_ordered(request)
        with locked_publish_mutex_v1(self.fixture.root) as publish_lock:
            with locked_cross_ledger_order_under_publish_mutex_v1(
                publish_lock
            ) as cross_lock:
                replayed = persist_under_lock(request, cross_lock)
        self.assertEqual(created.state, "committed")
        self.assertEqual(replayed.state, "replay")
        self.assertEqual(created.receipt, replayed.receipt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
