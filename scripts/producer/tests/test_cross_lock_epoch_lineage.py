"""Lease ownership, exact publisher lineage, and controller preflight."""

from __future__ import annotations

import dataclasses
import fcntl
import os
import unittest
from unittest.mock import patch

from _common import pl  # noqa: F401
from _cross_ledger_order_fixture import CrossLedgerOrderFixture
from headless import cross_ledger_order_lock as lock_module
from headless.active_fence_lock import (
    ActiveFenceLockError,
    locked_publish_mutex_v1,
)
from headless.cross_ledger_order_lock import (
    CROSS_LEDGER_ORDER_LOCK_NAME,
    CrossLedgerOrderLockError,
    locked_cross_ledger_order_root_v1,
    locked_cross_ledger_order_under_publish_mutex_v1,
    validate_cross_ledger_order_lock_v1,
    validate_publish_cross_ledger_lock_pair_v1,
)
from headless.cross_ledger_order_protocol import (
    persist_or_replay_cross_ledger_ordered_admission_under_lock_v1,
    preflight_cross_ledger_ordered_admission_under_lock_v1,
)
from headless.cross_ledger_order_types import CrossLedgerOrderError
from headless.durable_files import open_private_dir, open_private_file


def _explode(*_args: object) -> object:
    raise AssertionError("hostile scalar protocol executed")


class _Explosive:
    __eq__ = __fspath__ = __index__ = _explode


def _opposite_nonblock(fd: int) -> None:
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags ^ os.O_NONBLOCK)


def _reuse_number(source_fd: int, target_fd: int) -> int:
    if source_fd == target_fd:
        return target_fd
    os.dup2(source_fd, target_fd)
    os.close(source_fd)
    return target_fd


class CrossLockEpochLineageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CrossLedgerOrderFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_controller_apis_reject_normal_standalone_cross_witness(
        self,
    ) -> None:
        request = self.fixture.request()
        with locked_cross_ledger_order_root_v1(self.fixture.root) as lock:
            for call in (
                preflight_cross_ledger_ordered_admission_under_lock_v1,
                persist_or_replay_cross_ledger_ordered_admission_under_lock_v1,
            ):
                with self.subTest(call=call), self.assertRaises(
                    CrossLedgerOrderError
                ):
                    call(request, lock)
        self.assertFalse(
            os.path.exists(
                os.path.join(self.fixture.root, "cross-ledger-orders-v1")
            )
        )
        self.assertFalse(
            os.path.exists(
                os.path.join(self.fixture.root, "operation-admissions-v3")
            )
        )

    def test_publish_preflight_is_absent_and_creates_no_order(self) -> None:
        request = self.fixture.request()
        with locked_publish_mutex_v1(self.fixture.root) as publish_lock:
            with locked_cross_ledger_order_under_publish_mutex_v1(
                publish_lock
            ) as cross_lock:
                validate_publish_cross_ledger_lock_pair_v1(
                    publish_lock, cross_lock
                )
                state = preflight_cross_ledger_ordered_admission_under_lock_v1(
                    request, cross_lock
                )
        self.assertEqual(state.state, "absent")
        self.assertFalse(
            os.path.exists(
                os.path.join(self.fixture.root, "cross-ledger-orders-v1")
            )
        )

    def test_released_publish_cannot_be_laundered_by_other_holder(
        self,
    ) -> None:
        request = self.fixture.request()
        publish_context = locked_publish_mutex_v1(self.fixture.root)
        publish_lock = publish_context.__enter__()
        cross_context = locked_cross_ledger_order_under_publish_mutex_v1(
            publish_lock
        )
        cross_lock = cross_context.__enter__()
        attacker = open_private_file(
            publish_lock.root_fd, ".publish.mutex", os.O_RDWR
        )
        try:
            fcntl.flock(publish_lock.lock_fd, fcntl.LOCK_UN)
            fcntl.flock(attacker, fcntl.LOCK_EX)
            with self.assertRaises(CrossLedgerOrderError):
                persist_or_replay_cross_ledger_ordered_admission_under_lock_v1(
                    request, cross_lock
                )
            with self.assertRaises(CrossLedgerOrderLockError):
                cross_context.__exit__(None, None, None)
            with self.assertRaises(ActiveFenceLockError):
                publish_context.__exit__(None, None, None)
        finally:
            fcntl.flock(attacker, fcntl.LOCK_UN)
            os.close(attacker)
        self.assertFalse(
            os.path.exists(
                os.path.join(self.fixture.root, "cross-ledger-orders-v1")
            )
        )

    def test_reopened_same_inode_fd_fails_and_survives_teardown(self) -> None:
        context = locked_cross_ledger_order_root_v1(self.fixture.root)
        lock = context.__enter__()
        target = lock.lock_fd
        os.close(target)
        reopened = open_private_file(
            lock.root_fd, CROSS_LEDGER_ORDER_LOCK_NAME, os.O_RDWR
        )
        _opposite_nonblock(reopened)
        _reuse_number(reopened, target)
        with self.assertRaises(CrossLedgerOrderLockError):
            validate_cross_ledger_order_lock_v1(lock)
        with self.assertRaises(CrossLedgerOrderLockError):
            context.__exit__(None, None, None)
        os.fstat(target)
        os.close(target)

    def test_reopened_same_root_fd_fails_and_survives_teardown(self) -> None:
        context = locked_cross_ledger_order_root_v1(self.fixture.root)
        lock = context.__enter__()
        target = lock.root_fd
        os.close(target)
        reopened = open_private_dir(self.fixture.root)
        _opposite_nonblock(reopened)
        _reuse_number(reopened, target)
        with self.assertRaises(CrossLedgerOrderLockError):
            validate_cross_ledger_order_lock_v1(lock)
        with self.assertRaises(CrossLedgerOrderLockError):
            context.__exit__(None, None, None)
        os.fstat(target)
        os.close(target)

    def test_reopened_private_guard_releases_actual_lock(self) -> None:
        context = locked_cross_ledger_order_root_v1(self.fixture.root)
        lock = context.__enter__()
        retained = lock_module._ACTIVE_WITNESSES[lock.context_token]
        target = retained.lock_guard_fd
        os.close(target)
        reopened = open_private_file(
            lock.root_fd, CROSS_LEDGER_ORDER_LOCK_NAME, os.O_RDWR
        )
        _opposite_nonblock(reopened)
        _reuse_number(reopened, target)
        with self.assertRaises(CrossLedgerOrderLockError):
            validate_cross_ledger_order_lock_v1(lock)
        with self.assertRaises(CrossLedgerOrderLockError):
            context.__exit__(None, None, None)
        fcntl.flock(target, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(target, fcntl.LOCK_UN)
        os.close(target)

    def test_body_error_and_hostile_fields(self) -> None:
        sentinel = OSError("BODY-SENTINEL")
        with self.assertRaises(OSError) as raised:
            with locked_cross_ledger_order_root_v1(self.fixture.root):
                raise sentinel
        self.assertIs(raised.exception, sentinel)
        with locked_cross_ledger_order_root_v1(self.fixture.root) as lock:
            fields = (
                "context_token authority_root root_fd lock_fd root_identity "
                "lock_identity creator_pid lease_token"
            )
            for field in fields.split():
                original = getattr(lock, field)
                hostile = [] if field == "context_token" else _Explosive()
                object.__setattr__(lock, field, hostile)
                try:
                    with self.assertRaises(CrossLedgerOrderLockError):
                        validate_cross_ledger_order_lock_v1(lock)
                finally:
                    object.__setattr__(lock, field, original)

    def test_cross_lock_laundering_and_lease_tamper_fail(self) -> None:
        for attack in ("launder", "lease"):
            with self.subTest(attack=attack):
                context = locked_cross_ledger_order_root_v1(self.fixture.root)
                lock = context.__enter__()
                attacker = None
                if attack == "launder":
                    fcntl.flock(lock.lock_fd, fcntl.LOCK_UN)
                    attacker = open_private_file(
                        lock.root_fd, CROSS_LEDGER_ORDER_LOCK_NAME, os.O_RDWR
                    )
                    fcntl.flock(attacker, fcntl.LOCK_EX)
                else:
                    os.pwrite(lock.lock_fd, b"x" * 32, 0)
                    os.fsync(lock.lock_fd)
                try:
                    with self.assertRaises(CrossLedgerOrderLockError):
                        validate_cross_ledger_order_lock_v1(lock)
                    with self.assertRaises(CrossLedgerOrderLockError):
                        context.__exit__(None, None, None)
                finally:
                    if attacker is not None:
                        fcntl.flock(attacker, fcntl.LOCK_UN)
                        os.close(attacker)

    def test_cross_lease_changes_on_each_acquisition(self) -> None:
        with locked_cross_ledger_order_root_v1(self.fixture.root) as first:
            first_lease = first.lease_token
        with locked_cross_ledger_order_root_v1(self.fixture.root) as second:
            self.assertNotEqual(first_lease, second.lease_token)

    def test_root_swap_before_cross_write_leaves_replacement_empty(
        self,
    ) -> None:
        moved = f"{self.fixture.root}.retained"
        original_dup = os.dup
        attacked = False

        def swap_after_dup(fd: int) -> int:
            nonlocal attacked
            duplicated = original_dup(fd)
            if not attacked:
                attacked = True
                os.rename(self.fixture.root, moved)
                os.mkdir(self.fixture.root, 0o700)
            return duplicated

        with locked_publish_mutex_v1(self.fixture.root) as publish_lock:
            try:
                with patch.object(
                    lock_module.os, "dup", side_effect=swap_after_dup
                ):
                    with self.assertRaises(CrossLedgerOrderLockError):
                        with locked_cross_ledger_order_under_publish_mutex_v1(
                            publish_lock
                        ):
                            pass
                self.assertEqual(os.listdir(self.fixture.root), [])
                self.assertNotIn(
                    CROSS_LEDGER_ORDER_LOCK_NAME, os.listdir(moved)
                )
            finally:
                os.rmdir(self.fixture.root)
                os.rename(moved, self.fixture.root)

    def test_hostile_exact_type_request_fields_are_normalized(self) -> None:
        request = self.fixture.request()

        def nested(**changes: object) -> object:
            admission = dataclasses.replace(request.admission, **changes)
            return dataclasses.replace(request, admission=admission)

        cases = (
            dataclasses.replace(request, authority_root=_Explosive()),
            nested(authority_root=_Explosive()),
            dataclasses.replace(request, enrollment=_Explosive()),
            nested(operation=_Explosive()),
            nested(admission=_Explosive()),
            nested(proposal=_Explosive()),
        )
        for hostile in cases:
            with self.subTest(hostile=hostile), self.assertRaises(
                CrossLedgerOrderError
            ):
                preflight_cross_ledger_ordered_admission_under_lock_v1(
                    hostile, object()
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
