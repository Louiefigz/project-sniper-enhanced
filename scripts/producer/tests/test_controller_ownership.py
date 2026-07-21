"""Single-controller kernel-lock regressions."""
from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _common import pl  # noqa: F401
from headless.controller_ownership import (
    ControllerOwnershipError,
    IDENTITY_NAME,
    LOCK_NAME,
    assert_controller_ownership,
    controller_ownership,
)


class ControllerOwnershipTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.authority = Path(self.temp.name).resolve() / "authority"
        self.authority.mkdir(mode=0o700)
        os.chmod(self.authority, 0o700)
        boot = mock.patch("headless.controller_ownership.read_boot_id",
                          return_value="boot-v1-" + "b" * 64)
        boot.start()
        self.addCleanup(boot.stop)

    def test_second_controller_fails_until_first_releases(self) -> None:
        with controller_ownership(str(self.authority)) as lease:
            assert_controller_ownership(lease, str(self.authority))
            with self.assertRaisesRegex(ControllerOwnershipError, "already owns"):
                with controller_ownership(str(self.authority)):
                    pass
        with controller_ownership(str(self.authority)) as replay:
            assert_controller_ownership(replay, str(self.authority))

    def test_exception_releases_lock_and_lock_inode_is_never_unlinked(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "stop"):
            with controller_ownership(str(self.authority)):
                raise RuntimeError("stop")
        before = (self.authority / LOCK_NAME).stat()
        with controller_ownership(str(self.authority)):
            after = (self.authority / LOCK_NAME).stat()
        self.assertEqual((before.st_dev, before.st_ino),
                         (after.st_dev, after.st_ino))

    def test_restrictive_umask_still_creates_private_lock(self) -> None:
        previous = os.umask(0o777)
        try:
            with controller_ownership(str(self.authority)):
                pass
        finally:
            os.umask(previous)
        mode = stat.S_IMODE((self.authority / LOCK_NAME).stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_first_use_crash_after_lock_creation_recovers_identity(self) -> None:
        lock = self.authority / LOCK_NAME
        lock.write_bytes(b"")
        os.chmod(lock, 0o600)
        with controller_ownership(str(self.authority)) as lease:
            assert_controller_ownership(lease, str(self.authority))
        self.assertTrue((self.authority / IDENTITY_NAME).is_file())

    def test_replaced_lock_path_invalidates_live_lease(self) -> None:
        with controller_ownership(str(self.authority)) as lease:
            path = self.authority / LOCK_NAME
            path.rename(self.authority / ".old-controller.lock")
            path.write_bytes(b"replacement")
            os.chmod(path, 0o600)
            with self.assertRaisesRegex(ControllerOwnershipError,
                                        "replaced|no longer live"):
                assert_controller_ownership(lease, str(self.authority))

    def test_expired_lease_cannot_resurrect_after_fd_reuse(self) -> None:
        with controller_ownership(str(self.authority)) as lease:
            assert_controller_ownership(lease, str(self.authority))
        reopened = os.open(self.authority / LOCK_NAME, os.O_RDWR)
        try:
            with self.assertRaisesRegex(ControllerOwnershipError, "expired"):
                assert_controller_ownership(lease, str(self.authority))
        finally:
            os.close(reopened)

    @unittest.skipUnless(hasattr(os, "fork"), "fork is required")
    def test_forked_child_cannot_inherit_controller_capability(self) -> None:
        with controller_ownership(str(self.authority)) as lease:
            read_fd, write_fd = os.pipe()
            pid = os.fork()
            if pid == 0:
                os.close(read_fd)
                try:
                    assert_controller_ownership(lease, str(self.authority))
                except ControllerOwnershipError:
                    os.write(write_fd, b"rejected")
                else:
                    os.write(write_fd, b"accepted")
                os.close(write_fd)
                os._exit(0)
            os.close(write_fd)
            verdict = os.read(read_fd, 32)
            os.close(read_fd)
            os.waitpid(pid, 0)
            self.assertEqual(verdict, b"rejected")
            assert_controller_ownership(lease, str(self.authority))

    def test_authority_root_replacement_invalidates_lease(self) -> None:
        original = self.authority.with_name("authority-original")
        with controller_ownership(str(self.authority)) as lease:
            self.authority.rename(original)
            self.authority.mkdir(mode=0o700)
            os.chmod(self.authority, 0o700)
            (original / LOCK_NAME).rename(self.authority / LOCK_NAME)
            with self.assertRaisesRegex(ControllerOwnershipError,
                                        "replaced|no longer live"):
                assert_controller_ownership(lease, str(self.authority))

    def test_lock_replacement_does_not_admit_second_controller(self) -> None:
        with controller_ownership(str(self.authority)):
            path = self.authority / LOCK_NAME
            path.rename(self.authority / ".moved-controller.lock")
            path.write_bytes(b"replacement")
            os.chmod(path, 0o600)
            with self.assertRaisesRegex(ControllerOwnershipError, "identity"):
                with controller_ownership(str(self.authority)):
                    pass

    def test_identity_validation_failure_releases_acquired_flock(self) -> None:
        with controller_ownership(str(self.authority)):
            pass
        identity = self.authority / IDENTITY_NAME
        original = identity.read_bytes()
        identity.write_bytes(b"{}\n")
        os.chmod(identity, 0o600)
        with self.assertRaisesRegex(ControllerOwnershipError, "identity"):
            with controller_ownership(str(self.authority)):
                pass
        identity.write_bytes(original)
        os.chmod(identity, 0o600)
        with controller_ownership(str(self.authority)) as lease:
            assert_controller_ownership(lease, str(self.authority))


if __name__ == "__main__":
    unittest.main(verbosity=2)
