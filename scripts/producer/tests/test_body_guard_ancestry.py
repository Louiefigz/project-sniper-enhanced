"""Fresh guard equivalence and path-mutation faults; no media or render process."""
from __future__ import annotations

import hashlib
import os
import stat
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest.mock import Mock, patch

from cut_preview_io import real_directory
from guided_body_execution import BodyHeldFile, assert_body_files, hold_body_file


class BodyGuardAncestryTests(unittest.TestCase):
    """Never trade exact held-file/ancestry checks for a cross-call stat cache."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="sniper-guard-test-", dir="/private/tmp")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.directory = self.root / "same" / "deep" / "held" / "directory"
        self.directory.mkdir(parents=True)
        self.rows = tuple(self._file(str(index)) for index in range(24))
        self.clock = Mock()
        self.clock.remaining.return_value = 60.0

    def _file(self, name: str) -> BodyHeldFile:
        file = self.directory / name
        data = ("TEST-only " + name).encode()
        file.write_bytes(data)
        return hold_body_file(file, hashlib.sha256(data).hexdigest())

    def test_every_file_stays_checked_and_no_cross_call_cache_exists(self) -> None:
        assert_body_files(self.rows, self.clock)
        self.rows[-1].path.write_bytes(b"changed held bytes")
        with self.assertRaisesRegex(RuntimeError, "metadata identity"):
            assert_body_files(self.rows, self.clock)

    def test_same_bytes_replacement_inode_is_rejected(self) -> None:
        target = self.rows[0].path
        replacement = self.root / "replacement"
        replacement.write_bytes(target.read_bytes())
        os.replace(replacement, target)
        with self.assertRaises(RuntimeError):
            assert_body_files(self.rows, self.clock)

    def test_regular_file_chmod_is_rejected(self) -> None:
        self.rows[0].path.chmod(0o400)
        with self.assertRaises(RuntimeError):
            assert_body_files(self.rows, self.clock)

    def test_symlink_file_is_rejected(self) -> None:
        target = self.rows[0].path
        target.unlink()
        target.symlink_to(self.rows[1].path)
        with self.assertRaises(RuntimeError):
            assert_body_files(self.rows, self.clock)

    def test_symlink_ancestor_is_rejected_even_with_original_file_inode(self) -> None:
        moved = self.root / "moved"
        self.directory.rename(moved)
        self.directory.symlink_to(moved, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "ancestry is unsafe"):
            assert_body_files(self.rows, self.clock)

    def test_nondirectory_ancestor_is_rejected_before_child_traversal(self) -> None:
        self.directory.rename(self.root / "moved")
        self.directory.write_text("not a directory")
        with self.assertRaisesRegex(RuntimeError, "ancestry is unsafe"):
            assert_body_files(self.rows, self.clock)

    def test_relative_and_parent_alias_paths_are_rejected(self) -> None:
        row = self.rows[0]
        paths = (Path("relative/0"), Path("/" + str(row.path)),
                 self.directory / ".." / "directory" / "0")
        for path in paths:
            with self.subTest(path=str(path)), self.assertRaisesRegex(RuntimeError, "not canonical"):
                assert_body_files((BodyHeldFile(path, row.sha256, row.identity),), self.clock)

    def _during_file_sweep(self, change: Callable[[], None]) -> None:
        original = Path.lstat
        changed = False

        def read(file: Path, *args: object, **kwargs: object) -> os.stat_result:
            nonlocal changed
            result = original(file, *args, **kwargs)
            if file == self.rows[-1].path and not changed:
                changed = True
                change()
            return result

        with patch.object(Path, "lstat", read):
            assert_body_files(self.rows, self.clock)
        self.assertTrue(changed)

    def test_ancestor_link_swap_after_file_sweep_is_rejected(self) -> None:
        def change() -> None:
            moved = self.root / "moved"
            self.directory.rename(moved)
            self.directory.symlink_to(moved, target_is_directory=True)

        with self.assertRaisesRegex(RuntimeError, "ancestry is unsafe"):
            self._during_file_sweep(change)

    def test_directory_inode_swap_after_file_sweep_is_rejected(self) -> None:
        def change() -> None:
            self.directory.rename(self.root / "moved")
            self.directory.mkdir()

        with self.assertRaisesRegex(RuntimeError, "ancestry changed"):
            self._during_file_sweep(change)

    def test_directory_mode_change_after_file_sweep_is_rejected(self) -> None:
        mode = stat.S_IMODE(self.directory.lstat().st_mode) ^ 0o010
        with self.assertRaisesRegex(RuntimeError, "ancestry changed"):
            self._during_file_sweep(lambda: self.directory.chmod(mode))

    def test_unrelated_sibling_creation_is_not_a_false_identity_conflict(self) -> None:
        self._during_file_sweep(lambda: (self.directory / "new-sibling").mkdir())

    def test_original_budget_is_checked_after_the_complete_guard(self) -> None:
        self.clock.remaining.side_effect = [1.0, RuntimeError("original deadline exhausted")]
        with self.assertRaisesRegex(RuntimeError, "original deadline"):
            assert_body_files(self.rows, self.clock)
        self.assertEqual(self.clock.remaining.call_count, 2)

    def test_shared_ancestry_reduces_syscalls_without_skipping_file_checks(self) -> None:
        original = os.lstat
        calls: list[str] = []

        def counted(value: str | Path, *args: object, **kwargs: object) -> os.stat_result:
            calls.append(os.fspath(value))
            return original(value, *args, **kwargs)

        with patch.object(os, "lstat", counted):
            for row in self.rows:
                real_directory(row.path.parent)
                row.path.lstat()
        old_count = len(calls)
        calls.clear()
        with patch.object(os, "lstat", counted):
            assert_body_files(self.rows, self.clock)
        new_count = len(calls)
        self.assertLess(new_count * 5, old_count)
        for row in self.rows:
            self.assertEqual(calls.count(str(row.path)), 1)
        for parent in self.rows[0].path.parents:
            self.assertEqual(calls.count(str(parent)), 2)


if __name__ == "__main__":
    unittest.main()
