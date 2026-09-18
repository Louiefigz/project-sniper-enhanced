"""Epoch, ownership, and descriptor-teardown tests for publisher mutexes."""

from __future__ import annotations

import fcntl
import multiprocessing
import os
import unittest
from unittest.mock import patch

from _active_fence_fixture import ActiveFenceFixture
from _common import pl  # noqa: F401
from headless.active_fence_lock import (
    ActiveFenceLockError,
    locked_existing_publish_mutex_v1,
    validate_active_fence_lock_v1,
)
from headless.active_fence_protocol import (
    reserve_active_generation_fence_under_lock_v1,
    reserve_active_generation_fence_v1,
)
from headless.active_fence_types import ActiveFenceError
from headless.exclusive_lock_lease import LOCK_LEASE_SIZE_V1

_PUBLIC_LOCK_TARGET = (
    "headless.active_fence_protocol.locked_existing_publish_mutex_v1"
)


def _hold_publish_mutex(root: str, acquired: object, release: object) -> None:
    try:
        with locked_existing_publish_mutex_v1(root) as lock:
            acquired.send(("held", lock.lease_token))
            release.recv()
    except Exception as exc:  # pragma: no cover - reported in parent
        acquired.send((type(exc).__name__, b""))
    finally:
        acquired.close()
        release.close()


class ActiveFenceLockLeaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = ActiveFenceFixture()
        self.fixture.bootstrap()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_each_acquisition_rotates_lease_without_replacing_inode(
        self,
    ) -> None:
        inode = os.stat(self.fixture.lock_path).st_ino
        with locked_existing_publish_mutex_v1(self.fixture.root) as first:
            first_token = first.lease_token
            self.assertEqual(
                os.pread(first.lock_fd, LOCK_LEASE_SIZE_V1 + 1, 0),
                first_token,
            )
        with locked_existing_publish_mutex_v1(self.fixture.root) as second:
            second_token = second.lease_token
            self.assertEqual(
                os.pread(second.lock_fd, LOCK_LEASE_SIZE_V1 + 1, 0),
                second_token,
            )
        self.assertEqual(len(first_token), LOCK_LEASE_SIZE_V1)
        self.assertNotEqual(first_token, second_token)
        self.assertEqual(os.stat(self.fixture.lock_path).st_ino, inode)

    def test_reused_epoch_fails_without_changing_mutex_bytes(self) -> None:
        inode = os.stat(self.fixture.lock_path).st_ino
        with open(self.fixture.lock_path, "rb") as source:
            before = source.read()
        with patch(
            "headless.exclusive_lock_lease.secrets.token_bytes",
            return_value=before,
        ), self.assertRaises(ActiveFenceLockError):
            with locked_existing_publish_mutex_v1(self.fixture.root):
                pass
        with open(self.fixture.lock_path, "rb") as source:
            self.assertEqual(source.read(), before)
        self.assertEqual(os.stat(self.fixture.lock_path).st_ino, inode)

    def test_intervening_acquisition_permanently_invalidates_epoch(
        self,
    ) -> None:
        context = locked_existing_publish_mutex_v1(self.fixture.root)
        old = context.__enter__()
        inode = old.lock_identity
        fcntl.flock(old.lock_fd, fcntl.LOCK_UN)
        with locked_existing_publish_mutex_v1(self.fixture.root) as current:
            current_token = current.lease_token
        failed_before_exit = False
        try:
            validate_active_fence_lock_v1(old)
        except ActiveFenceLockError:
            failed_before_exit = True
        with self.assertRaises(ActiveFenceLockError):
            context.__exit__(None, None, None)
        self.assertTrue(failed_before_exit)
        self.assertNotEqual(old.lease_token, current_token)
        self.assertEqual(os.stat(self.fixture.lock_path).st_ino, inode[1])

    def test_released_parent_cannot_launder_child_owned_flock(self) -> None:
        context = multiprocessing.get_context("fork")
        acquired_reader, acquired_writer = context.Pipe(duplex=False)
        release_reader, release_writer = context.Pipe(duplex=False)
        parent_context = locked_existing_publish_mutex_v1(self.fixture.root)
        parent = parent_context.__enter__()
        before = self.fixture.journal_bytes()
        child = context.Process(
            target=_hold_publish_mutex,
            args=(self.fixture.root, acquired_writer, release_reader),
        )
        child.start()
        fcntl.flock(parent.lock_fd, fcntl.LOCK_UN)
        self.assertTrue(acquired_reader.poll(5))
        status, child_token = acquired_reader.recv()
        validation_failed = reservation_failed = False
        try:
            validate_active_fence_lock_v1(parent)
        except ActiveFenceLockError:
            validation_failed = True
        try:
            reserve_active_generation_fence_under_lock_v1(
                parent, self.fixture.authority_id, self.fixture.attempt_a
            )
        except ActiveFenceError:
            reservation_failed = True
        release_writer.send("release")
        child.join(5)
        with self.assertRaises(ActiveFenceLockError):
            parent_context.__exit__(None, None, None)
        self.assertEqual(status, "held")
        self.assertEqual(child.exitcode, 0)
        self.assertTrue(validation_failed and reservation_failed)
        self.assertNotEqual(parent.lease_token, child_token)
        self.assertEqual(self.fixture.journal_bytes(), before)

    def test_same_inode_reused_public_fds_survive_safe_teardown(self) -> None:
        reopened_lock = reopened_root = None
        with self.assertRaises(ActiveFenceLockError):
            with locked_existing_publish_mutex_v1(self.fixture.root) as lock:
                lock_number, root_number = lock.lock_fd, lock.root_fd
                os.close(lock.lock_fd)
                reopened_lock = os.open(self.fixture.lock_path, os.O_RDWR)
                os.close(lock.root_fd)
                reopened_root = os.open(
                    self.fixture.root, os.O_RDONLY | os.O_DIRECTORY
                )
                self.assertEqual(reopened_lock, lock_number)
                self.assertEqual(reopened_root, root_number)
        try:
            os.fstat(reopened_lock)
            os.fstat(reopened_root)
        finally:
            os.close(reopened_lock)
            os.close(reopened_root)
        with locked_existing_publish_mutex_v1(self.fixture.root) as current:
            validate_active_fence_lock_v1(current)

    def test_unrelated_reused_public_fds_are_not_closed_or_leaked(
        self,
    ) -> None:
        before = frozenset(os.listdir("/dev/fd"))
        replacement_lock = replacement_root = None
        with self.assertRaises(ActiveFenceLockError):
            with locked_existing_publish_mutex_v1(self.fixture.root) as lock:
                os.close(lock.lock_fd)
                replacement_lock = os.open("/dev/null", os.O_RDONLY)
                os.close(lock.root_fd)
                replacement_root = os.open("/dev/null", os.O_RDONLY)
        try:
            os.fstat(replacement_lock)
            os.fstat(replacement_root)
        finally:
            os.close(replacement_lock)
            os.close(replacement_root)
        self.assertEqual(frozenset(os.listdir("/dev/fd")), before)
        with locked_existing_publish_mutex_v1(self.fixture.root) as current:
            validate_active_fence_lock_v1(current)

    def test_invalid_public_input_never_opens_existing_mutex(self) -> None:
        before = self.fixture.journal_bytes()
        with patch(
            _PUBLIC_LOCK_TARGET,
            side_effect=AssertionError("invalid input opened mutex"),
        ):
            with self.assertRaises(ActiveFenceError):
                reserve_active_generation_fence_v1(
                    self.fixture.root,
                    self.fixture.authority_id,
                    "NOT-A-UUID",
                )
            with self.assertRaises(ActiveFenceError):
                reserve_active_generation_fence_v1(
                    self.fixture.root,
                    "bad authority!",
                    self.fixture.attempt_a,
                )
        self.assertEqual(self.fixture.journal_bytes(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
