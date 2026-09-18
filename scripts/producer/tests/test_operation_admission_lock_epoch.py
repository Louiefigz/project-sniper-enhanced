"""Adversarial epoch, descriptor, teardown, and fork tests for V3 writer."""

from __future__ import annotations

import fcntl
import os
import unittest
from unittest.mock import patch

from _common import pl  # noqa: F401
from _cross_ledger_order_fixture import CrossLedgerOrderFixture
from headless import operation_admission_lock as lock_module
from headless.cross_ledger_order_lock import (
    CROSS_LEDGER_ORDER_LOCK_NAME,
    locked_cross_ledger_order_root_v1,
    locked_cross_ledger_order_under_publish_mutex_v1,
)
from headless.active_fence_lock import locked_publish_mutex_v1
from headless.durable_files import open_private_dir, open_private_file
from headless.operation_admission_lock import (
    OperationAdmissionWriterLockError,
    locked_operation_admission_writer_v3,
    validate_operation_admission_writer_lock_v3,
)
from headless.operation_admission_lock_resources import (
    OPERATION_ADMISSION_LOCK_NAME,
    OPERATION_ADMISSION_STORE_NAME,
)


def _explode(*_args: object) -> object:
    raise AssertionError("hostile scalar protocol executed")


class _Explosive:
    __eq__ = __fspath__ = __index__ = _explode


def _opposite_nonblock(fd: int) -> None:
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags ^ os.O_NONBLOCK)


def _reuse_number(source_fd: int, target_fd: int) -> None:
    if source_fd != target_fd:
        os.dup2(source_fd, target_fd)
        os.close(source_fd)


def _probe_unlocked(root: str, names: tuple[str, ...]) -> None:
    root_fd = open_private_dir(root)
    try:
        for name in names:
            lock_fd = open_private_file(root_fd, name, os.O_RDWR)
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)
    finally:
        os.close(root_fd)


def _crash_owner(
    root: str, authority_id: str, channels: tuple[int, int, int]
) -> None:
    ready_fd, release_fd, done_fd = channels
    outer_context = locked_cross_ledger_order_root_v1(root)
    outer = outer_context.__enter__()
    writer_context = locked_operation_admission_writer_v3(
        root, authority_id, outer
    )
    writer_context.__enter__()
    child_pid = os.fork()
    if child_pid == 0:
        os.write(ready_fd, b"1")
        os.read(release_fd, 1)
        os.write(done_fd, b"1")
        os._exit(0)
    os._exit(0)


class OperationAdmissionLockEpochTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CrossLedgerOrderFixture()
        self.request = self.fixture.request().admission
        self.authority_id = self.request.admission.authority_id

    def tearDown(self) -> None:
        self.fixture.close()

    def test_reopened_public_lock_fd_fails_and_survives_teardown(self) -> None:
        with locked_cross_ledger_order_root_v1(self.fixture.root) as outer:
            context = locked_operation_admission_writer_v3(
                self.fixture.root, self.authority_id, outer
            )
            writer = context.__enter__()
            target = writer.lock_fd
            os.close(target)
            reopened = open_private_file(
                writer.root_fd, OPERATION_ADMISSION_LOCK_NAME, os.O_RDWR
            )
            _opposite_nonblock(reopened)
            _reuse_number(reopened, target)
            with self.assertRaises(OperationAdmissionWriterLockError):
                validate_operation_admission_writer_lock_v3(writer)
            with self.assertRaises(OperationAdmissionWriterLockError):
                context.__exit__(None, None, None)
            os.fstat(target)
            os.close(target)

    def test_reopened_private_guard_releases_actual_lock(self) -> None:
        with locked_cross_ledger_order_root_v1(self.fixture.root) as outer:
            context = locked_operation_admission_writer_v3(
                self.fixture.root, self.authority_id, outer
            )
            writer = context.__enter__()
            resources = lock_module._ACTIVE_WRITERS[
                writer.context_token
            ].resources
            target = resources.lock_guard_fd
            os.close(target)
            reopened = open_private_file(
                writer.root_fd, OPERATION_ADMISSION_LOCK_NAME, os.O_RDWR
            )
            _opposite_nonblock(reopened)
            _reuse_number(reopened, target)
            with self.assertRaises(OperationAdmissionWriterLockError):
                context.__exit__(None, None, None)
            fcntl.flock(target, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(target, fcntl.LOCK_UN)
            os.close(target)

    def test_unlock_laundering_and_lease_tamper_fail(self) -> None:
        for attack in ("launder", "lease"):
            with self.subTest(attack=attack):
                with locked_cross_ledger_order_root_v1(
                    self.fixture.root
                ) as outer:
                    context = locked_operation_admission_writer_v3(
                        self.fixture.root, self.authority_id, outer
                    )
                    writer = context.__enter__()
                    attacker = None
                    if attack == "launder":
                        fcntl.flock(writer.lock_fd, fcntl.LOCK_UN)
                        attacker = open_private_file(
                            writer.root_fd,
                            OPERATION_ADMISSION_LOCK_NAME,
                            os.O_RDWR,
                        )
                        fcntl.flock(attacker, fcntl.LOCK_EX)
                    else:
                        os.pwrite(writer.lock_fd, b"x" * 32, 0)
                        os.fsync(writer.lock_fd)
                    try:
                        with self.assertRaises(
                            OperationAdmissionWriterLockError
                        ):
                            context.__exit__(None, None, None)
                    finally:
                        if attacker is not None:
                            fcntl.flock(attacker, fcntl.LOCK_UN)
                            os.close(attacker)

    def test_epoch_body_error_and_unhashable_token_contracts(self) -> None:
        with locked_cross_ledger_order_root_v1(self.fixture.root) as outer:
            with locked_operation_admission_writer_v3(
                self.fixture.root, self.authority_id, outer
            ) as first:
                first_lease = first.lease_token
                fields = (
                    "context_token authority_root authority_id root_fd "
                    "lock_fd store_fd root_identity lock_identity "
                    "store_identity creator_pid lease_token"
                )
                for field in fields.split():
                    original = getattr(first, field)
                    hostile = [] if field == "context_token" else _Explosive()
                    object.__setattr__(first, field, hostile)
                    try:
                        with self.assertRaises(
                            OperationAdmissionWriterLockError
                        ):
                            validate_operation_admission_writer_lock_v3(first)
                    finally:
                        object.__setattr__(first, field, original)
            with locked_operation_admission_writer_v3(
                self.fixture.root, self.authority_id, outer
            ) as second:
                self.assertNotEqual(first_lease, second.lease_token)
            sentinel = OSError("BODY-SENTINEL")
            with self.assertRaises(OSError) as raised:
                with locked_operation_admission_writer_v3(
                    self.fixture.root, self.authority_id, outer
                ):
                    raise sentinel
            self.assertIs(raised.exception, sentinel)

    def test_full_publish_cross_inner_body_oserror_is_exact(self) -> None:
        sentinel = OSError("FULL-PATH-BODY-SENTINEL")
        with self.assertRaises(OSError) as raised:
            with locked_publish_mutex_v1(self.fixture.root) as publish:
                with locked_cross_ledger_order_under_publish_mutex_v1(
                    publish
                ) as outer:
                    with locked_operation_admission_writer_v3(
                        self.fixture.root, self.authority_id, outer
                    ):
                        raise sentinel
        self.assertIs(raised.exception, sentinel)

    def test_root_swap_before_inner_write_leaves_replacement_empty(
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

        with locked_cross_ledger_order_root_v1(self.fixture.root) as outer:
            try:
                with patch.object(
                    lock_module.os, "dup", side_effect=swap_after_dup
                ), self.assertRaises(OperationAdmissionWriterLockError):
                    with locked_operation_admission_writer_v3(
                        self.fixture.root, self.authority_id, outer
                    ):
                        pass
                self.assertEqual(os.listdir(self.fixture.root), [])
                retained = os.listdir(moved)
                self.assertNotIn(OPERATION_ADMISSION_LOCK_NAME, retained)
                self.assertNotIn(OPERATION_ADMISSION_STORE_NAME, retained)
            finally:
                os.rmdir(self.fixture.root)
                os.rename(moved, self.fixture.root)

    @unittest.skipUnless(hasattr(os, "fork"), "fork is required")
    def test_owner_crash_does_not_leave_locks_in_live_child(self) -> None:
        ready_r, ready_w = os.pipe()
        release_r, release_w = os.pipe()
        done_r, done_w = os.pipe()
        owner_pid = os.fork()
        if owner_pid == 0:
            os.close(ready_r)
            os.close(release_w)
            os.close(done_r)
            _crash_owner(
                self.fixture.root,
                self.authority_id,
                (ready_w, release_r, done_w),
            )
        os.close(ready_w)
        os.close(release_r)
        os.close(done_w)
        try:
            os.waitpid(owner_pid, 0)
            self.assertEqual(os.read(ready_r, 1), b"1")
            _probe_unlocked(
                self.fixture.root,
                (CROSS_LEDGER_ORDER_LOCK_NAME, OPERATION_ADMISSION_LOCK_NAME),
            )
        finally:
            os.write(release_w, b"1")
            self.assertEqual(os.read(done_r, 1), b"1")
            for fd in (ready_r, release_w, done_r):
                os.close(fd)


if __name__ == "__main__":
    unittest.main(verbosity=2)
