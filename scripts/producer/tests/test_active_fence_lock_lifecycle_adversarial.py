"""Process, exception, and cleanup-anchor attacks on publisher mutexes."""

from __future__ import annotations

import dataclasses
import fcntl
import multiprocessing
import os
import signal
import time
import unittest
from unittest.mock import patch

from _active_fence_fixture import ActiveFenceFixture
from _common import pl  # noqa: F401
from headless import active_fence_lock as lock_module
from headless.active_fence_lock import (
    ActiveFenceLockError,
    locked_existing_publish_mutex_v1,
    validate_active_fence_lock_v1,
)
from headless.active_fence_protocol import (
    reserve_active_generation_fence_under_lock_v1,
)
from headless.active_fence_types import ActiveFenceError


class _HostileScalar:
    def __eq__(self, other: object) -> bool:
        raise AssertionError("hostile equality executed")

    def __fspath__(self) -> str:
        raise AssertionError("hostile path protocol executed")

    def __index__(self) -> int:
        raise AssertionError("hostile descriptor protocol executed")


def _crash_owner_after_fork(root: str, output: object) -> None:
    context = locked_existing_publish_mutex_v1(root)
    context.__enter__()
    child_pid = os.fork()
    if child_pid == 0:
        output.send(("child-ready", os.getpid()))
        output.close()
        time.sleep(30)
        os._exit(0)
    output.close()
    os._exit(0)


def _reuse_fd_before_inherited_context_unwinds(
    root: str, output: object
) -> None:
    child_branch = False
    target_fd = None
    try:
        with locked_existing_publish_mutex_v1(root) as lock:
            child_pid = os.fork()
            if child_pid == 0:
                child_branch = True
                target_fd = lock.lock_fd
                source_fd = os.open("/dev/null", os.O_RDONLY)
                if source_fd != target_fd:
                    os.dup2(source_fd, target_fd)
                    os.close(source_fd)
            else:
                os.waitpid(child_pid, 0)
    except ActiveFenceLockError:
        if not child_branch:
            output.send(("parent", "lock-error"))
            output.close()
            return
    if child_branch:
        try:
            os.fstat(target_fd)
        except OSError:
            state = "replacement-closed"
        else:
            state = "replacement-open"
        output.send(("child", state))
        output.close()
        os._exit(0)
    output.send(("parent", "clean"))
    output.close()


class ActiveFenceLockLifecycleAdversarialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = ActiveFenceFixture()
        self.fixture.bootstrap()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_body_oserror_is_preserved_during_normal_teardown(self) -> None:
        sentinel = OSError("body sentinel")
        with self.assertRaises(OSError) as captured:
            with locked_existing_publish_mutex_v1(self.fixture.root):
                raise sentinel
        self.assertIs(captured.exception, sentinel)
        with locked_existing_publish_mutex_v1(self.fixture.root) as lock:
            validate_active_fence_lock_v1(lock)

    def test_body_error_survives_reused_public_fd_teardown(self) -> None:
        sentinel = OSError("body and teardown sentinel")
        replacement = None
        with self.assertRaises(OSError) as captured:
            with locked_existing_publish_mutex_v1(self.fixture.root) as lock:
                public_number = lock.lock_fd
                os.close(public_number)
                replacement = os.open("/dev/null", os.O_RDONLY)
                self.assertEqual(replacement, public_number)
                raise sentinel
        self.assertIs(captured.exception, sentinel)
        try:
            os.fstat(replacement)
        finally:
            os.close(replacement)
        with locked_existing_publish_mutex_v1(self.fixture.root) as lock:
            validate_active_fence_lock_v1(lock)

    def test_hostile_unhashable_token_fails_as_lock_error(self) -> None:
        with locked_existing_publish_mutex_v1(self.fixture.root) as lock:
            forged = dataclasses.replace(lock, context_token=[])
            with self.assertRaises(ActiveFenceLockError):
                validate_active_fence_lock_v1(forged)
            with self.assertRaises(ActiveFenceError):
                reserve_active_generation_fence_under_lock_v1(
                    forged,
                    self.fixture.authority_id,
                    self.fixture.attempt_a,
                )

    def test_hostile_witness_fields_fail_before_python_protocols(self) -> None:
        with locked_existing_publish_mutex_v1(self.fixture.root) as lock:
            hostile = _HostileScalar()
            cases = (
                ("authority_root", hostile),
                ("root_fd", hostile),
                ("lock_fd", hostile),
                ("root_identity", hostile),
                ("lock_identity", (hostile, 1)),
                ("creator_pid", hostile),
                ("lease_token", hostile),
            )
            for field, forged in cases:
                original = getattr(lock, field)
                object.__setattr__(lock, field, forged)
                try:
                    with self.subTest(field=field), self.assertRaises(
                        ActiveFenceLockError
                    ):
                        validate_active_fence_lock_v1(lock)
                finally:
                    object.__setattr__(lock, field, original)

    def test_invalid_generated_context_token_releases_mutex(self) -> None:
        with patch.object(
            lock_module.secrets,
            "token_bytes",
            side_effect=(b"x" * 32, []),
        ), self.assertRaises(ActiveFenceLockError):
            with locked_existing_publish_mutex_v1(self.fixture.root):
                pass
        with locked_existing_publish_mutex_v1(self.fixture.root) as lock:
            validate_active_fence_lock_v1(lock)

    def test_invalid_generated_lease_does_not_mutate_or_hold_mutex(
        self,
    ) -> None:
        with open(self.fixture.lock_path, "rb") as source:
            before = source.read()
        with patch.object(
            lock_module.secrets, "token_bytes", return_value=[]
        ), self.assertRaises(ActiveFenceLockError):
            with locked_existing_publish_mutex_v1(self.fixture.root):
                pass
        with open(self.fixture.lock_path, "rb") as source:
            self.assertEqual(source.read(), before)
        with locked_existing_publish_mutex_v1(self.fixture.root) as lock:
            validate_active_fence_lock_v1(lock)

    def test_reused_validation_guard_cannot_leak_public_flock(self) -> None:
        context = locked_existing_publish_mutex_v1(self.fixture.root)
        lock = context.__enter__()
        registration = lock_module._ACTIVE_WITNESSES[lock.context_token]
        guard_number = registration.lock_guard_fd
        os.close(guard_number)
        replacement = os.open(self.fixture.lock_path, os.O_RDWR)
        self.assertEqual(replacement, guard_number)
        with self.assertRaises(ActiveFenceLockError):
            context.__exit__(None, None, None)
        try:
            os.fstat(replacement)
        finally:
            os.close(replacement)
        with locked_existing_publish_mutex_v1(self.fixture.root) as current:
            validate_active_fence_lock_v1(current)

    def test_owner_crash_does_not_leave_lock_in_live_fork_child(self) -> None:
        context = multiprocessing.get_context("fork")
        receiver, sender = context.Pipe(duplex=False)
        owner = context.Process(
            target=_crash_owner_after_fork,
            args=(self.fixture.root, sender),
        )
        child_pid = None
        try:
            owner.start()
            self.assertTrue(receiver.poll(5))
            status, child_pid = receiver.recv()
            owner.join(0.25)
            self.assertEqual(status, "child-ready")
            self.assertEqual(owner.exitcode, 0)
            probe = os.open(self.fixture.lock_path, os.O_RDWR)
            try:
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(probe, fcntl.LOCK_UN)
            finally:
                os.close(probe)
        finally:
            receiver.close()
            if owner.is_alive():
                owner.kill()
                owner.join(5)
            if child_pid is not None:
                try:
                    os.kill(child_pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass

    def test_inherited_context_teardown_preserves_reused_child_fd(
        self,
    ) -> None:
        context = multiprocessing.get_context("fork")
        receiver, sender = context.Pipe(duplex=False)
        owner = context.Process(
            target=_reuse_fd_before_inherited_context_unwinds,
            args=(self.fixture.root, sender),
        )
        owner.start()
        results = {receiver.recv(), receiver.recv()}
        owner.join(5)
        receiver.close()
        self.assertEqual(
            results,
            {("child", "replacement-open"), ("parent", "clean")},
        )
        self.assertEqual(owner.exitcode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
