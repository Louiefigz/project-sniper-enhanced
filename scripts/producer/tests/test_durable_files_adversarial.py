"""Availability regressions for bounded private authority reads."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _common import pl  # noqa: F401
from headless.durable_files import (
    DurableFileError,
    bounded_directory_entries,
    exact_directory_entries,
    open_private_dir,
    read_private_file,
)

PRODUCER_DIR = Path(__file__).resolve().parents[1]


class DurableFilesAdversarialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "authority"
        self.root.mkdir(mode=0o700)
        os.chmod(self.root, 0o700)

    def test_short_os_reads_are_reassembled_until_eof(self) -> None:
        payload = b"a canonical authority record"
        path = self.root / "record.json"
        path.write_bytes(payload)
        os.chmod(path, 0o600)
        real_read = os.read
        root_fd = open_private_dir(str(self.root))
        try:
            with mock.patch(
                "headless.durable_files.os.read",
                side_effect=lambda fd, size: real_read(fd, min(size, 3)),
            ):
                self.assertEqual(
                    read_private_file(root_fd, path.name), payload
                )
        finally:
            os.close(root_fd)

    def test_fifo_leaf_rejects_without_blocking(self) -> None:
        fifo = self.root / "record.json"
        os.mkfifo(fifo, 0o600)
        code = (
            "import os,sys;"
            "from headless.durable_files import open_private_dir,"
            "read_private_file;"
            "fd=open_private_dir(sys.argv[1]);"
            "read_private_file(fd,'record.json')"
        )
        env = {**os.environ, "PYTHONPATH": str(PRODUCER_DIR)}
        completed = subprocess.run(
            [sys.executable, "-c", code, str(self.root)],
            cwd=PRODUCER_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("DurableFileError", completed.stderr)

    def test_exact_directory_comparison_rejects_unknown_without_listdir(
        self,
    ) -> None:
        (self.root / "expected").mkdir(mode=0o700)
        (self.root / "unknown").mkdir(mode=0o700)
        root_fd = open_private_dir(str(self.root))
        try:
            with mock.patch(
                "headless.durable_files.os.listdir",
                side_effect=AssertionError("unbounded listdir called"),
            ):
                self.assertFalse(
                    exact_directory_entries(root_fd, {"expected"})
                )
        finally:
            os.close(root_fd)

    def test_bounded_directory_listing_stops_at_explicit_limit(self) -> None:
        for index in range(3):
            (self.root / f"entry-{index}").mkdir(mode=0o700)
        root_fd = open_private_dir(str(self.root))
        try:
            with self.assertRaisesRegex(DurableFileError, "entry limit"):
                bounded_directory_entries(root_fd, 2)
            self.assertEqual(
                bounded_directory_entries(root_fd, 3),
                ("entry-0", "entry-1", "entry-2"),
            )
        finally:
            os.close(root_fd)


if __name__ == "__main__":
    unittest.main(verbosity=2)
