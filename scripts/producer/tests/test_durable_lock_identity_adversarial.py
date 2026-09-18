"""Hostile types and inode replacement attacks on durable lock helpers."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from _common import pl  # noqa: F401
from headless import authority_record as authority_module
from headless.authority_record import (
    AuthorityRecordError,
    ensure_authority_record,
)
from headless.durable_files import (
    DurableFileError,
    exact_directory_entries,
    locked_private_dir,
    open_private_dir,
)


class _AlwaysEqual(str):
    def __eq__(self, other: object) -> bool:
        return True

    def __ne__(self, other: object) -> bool:
        return False

    __hash__ = str.__hash__


class DurableLockIdentityAdversarialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = os.path.join(
            os.path.realpath(self.temporary.name), "authority"
        )
        os.mkdir(self.root, 0o700)
        os.chmod(self.root, 0o700)

    def test_expected_closure_rejects_hostile_string_members(self) -> None:
        root_fd = open_private_dir(self.root)
        try:
            with self.assertRaises(DurableFileError):
                exact_directory_entries(root_fd, {_AlwaysEqual("missing")})
        finally:
            os.close(root_fd)

    def test_noncanonical_hostile_root_string_cannot_bypass_type_check(
        self,
    ) -> None:
        alias = _AlwaysEqual(
            os.path.join(self.root, "..", os.path.basename(self.root))
        )
        with self.assertRaises(DurableFileError):
            open_private_dir(alias)

    def test_lock_inode_replacement_is_detected_before_success(self) -> None:
        lock_path = os.path.join(self.root, ".test.lock")
        with self.assertRaisesRegex(DurableFileError, "lock inode"):
            with locked_private_dir(self.root, ".test.lock"):
                os.unlink(lock_path)
                with open(lock_path, "wb"):
                    pass
                os.chmod(lock_path, 0o600)

    def test_authority_root_path_replacement_is_detected(self) -> None:
        moved = os.path.join(self.temporary.name, "moved-authority")
        with self.assertRaisesRegex(DurableFileError, "directory inode"):
            with locked_private_dir(self.root, ".test.lock"):
                os.rename(self.root, moved)
                os.mkdir(self.root, 0o700)
                os.chmod(self.root, 0o700)

    def test_late_orphan_during_first_authority_bind_blocks_success(
        self,
    ) -> None:
        root_fd = open_private_dir(self.root)
        original = authority_module.write_pending_replace

        def attacked(dir_fd: int, names: tuple[str, str], raw: bytes) -> None:
            original(dir_fd, names, raw)
            orphan_fd = os.open(
                "late-orphan",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=dir_fd,
            )
            os.close(orphan_fd)

        try:
            with mock.patch.object(
                authority_module, "write_pending_replace", attacked
            ), self.assertRaisesRegex(AuthorityRecordError, "changed"):
                ensure_authority_record(root_fd, "authority-mp4-v1")
        finally:
            os.close(root_fd)


if __name__ == "__main__":
    unittest.main(verbosity=2)
