"""Lock-lineage and filesystem attacks on fence-order start intents."""

from __future__ import annotations

import dataclasses
import os
import shutil
import unittest
from unittest.mock import patch

from _common import pl  # noqa: F401
from _fence_order_start_fixture import FenceOrderStartFixture
from headless import fence_order_start_records as records_io
from headless.active_fence_lock import locked_existing_publish_mutex_v1
from headless.cross_ledger_order_lock import (
    locked_cross_ledger_order_root_v1,
)
from headless.fence_order_start_store import (
    STORE_NAME,
    FenceOrderStartError,
    persist_or_replay_fence_order_start_v1,
)
from headless.fence_order_start_types import (
    FenceOrderStartRequestV1,
    PublishCrossLedgerLockPairV1,
)


class FenceOrderStartAdversarialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = FenceOrderStartFixture()
        self.addCleanup(self.fixture.close)

    def test_cross_lock_without_exact_publish_parent_is_rejected(self) -> None:
        with locked_existing_publish_mutex_v1(self.fixture.root) as publish:
            with locked_cross_ledger_order_root_v1(self.fixture.root) as cross:
                request = FenceOrderStartRequestV1(
                    PublishCrossLedgerLockPairV1(publish, cross),
                    self.fixture.reservation,
                    self.fixture.fence,
                    self.fixture.identity,
                )
                with self.assertRaises(FenceOrderStartError):
                    persist_or_replay_fence_order_start_v1(request)
        self.assertFalse(self.fixture.start_store_exists())

    def test_released_parent_and_forged_pair_are_rejected(self) -> None:
        with self.fixture.locked_request() as request:
            forged = dataclasses.replace(
                request,
                locks=PublishCrossLedgerLockPairV1(
                    dataclasses.replace(request.locks.publish_lock),
                    request.locks.cross_lock,
                ),
            )
            with self.assertRaises(FenceOrderStartError):
                persist_or_replay_fence_order_start_v1(forged)
            stale = request
        with self.assertRaises(FenceOrderStartError):
            persist_or_replay_fence_order_start_v1(stale)

    def test_nonregular_hardlink_oversize_and_unknown_entries_fail(
        self,
    ) -> None:
        attacks = ("fifo", "symlink", "hardlink", "oversize", "unknown")
        for attack in attacks:
            with self.subTest(attack=attack):
                fixture = FenceOrderStartFixture()
                self.addCleanup(fixture.close)
                store = os.path.join(fixture.root, STORE_NAME)
                os.mkdir(store, 0o700)
                name = records_io.fence_order_start_record_name_v1(
                    fixture.identity.attempt_id
                )
                final = os.path.join(store, name)
                target = os.path.join(fixture.root, f"target-{attack}")
                if attack == "fifo":
                    os.mkfifo(final, 0o600)
                elif attack == "unknown":
                    with open(os.path.join(store, "surprise"), "wb"):
                        pass
                    os.chmod(os.path.join(store, "surprise"), 0o600)
                elif attack == "oversize":
                    with open(final, "wb") as output:
                        output.write(b"x" * (records_io.MAX_START_BYTES + 1))
                    os.chmod(final, 0o600)
                else:
                    with open(target, "wb") as output:
                        output.write(b"target")
                    os.chmod(target, 0o600)
                    if attack == "symlink":
                        os.symlink(target, final)
                    else:
                        os.link(target, final)
                with self.assertRaises(FenceOrderStartError):
                    fixture.persist()

    def test_named_inode_swap_during_replay_is_detected(self) -> None:
        created = self.fixture.persist()
        store = os.path.join(self.fixture.root, STORE_NAME)
        final = os.path.join(store, created.record_name)
        archived = os.path.join(self.fixture.root, "archived-start")
        original = records_io.assert_named_private_file_identity
        calls = 0

        def attack(parent_fd: int, name: str, child_fd: int) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                os.rename(final, archived)
                shutil.copy2(archived, final)
                os.chmod(final, 0o600)
            original(parent_fd, name, child_fd)

        with patch.object(
            records_io,
            "assert_named_private_file_identity",
            side_effect=attack,
        ), self.assertRaises(FenceOrderStartError):
            self.fixture.persist()

    def test_record_name_rejects_noncanonical_attempt(self) -> None:
        with self.assertRaises(RuntimeError):
            records_io.fence_order_start_record_name_v1("not-a-uuid")


if __name__ == "__main__":
    unittest.main(verbosity=2)
