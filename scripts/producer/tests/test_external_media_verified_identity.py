"""Same-hash descriptor identity faults over tiny TEST bytes; no media admission jobs."""
from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from headless import external_media_snapshot as module
from headless.external_media_snapshot import ExternalMediaSnapshot, observe_external_media_snapshot, verify_external_media_snapshot
from headless.external_media_verification import SourceVerificationRuntime, snapshot_stat_identity


class ExternalMediaVerifiedIdentityTests(unittest.TestCase):
    """The returned hash and all nine fields must describe the very same opened inode."""

    def setUp(self) -> None:
        """Use actual small files and a deterministic original-clock callback."""
        self.temp = tempfile.TemporaryDirectory(prefix="sniper-source-identity-", dir="/private/tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "TEST.media"
        self.data = b"TEST original verified bytes" * 100
        self.path.write_bytes(self.data)
        self.snapshot = ExternalMediaSnapshot(str(self.path), hashlib.sha256(self.data).hexdigest(), len(self.data), 0, 0)
        self.clock = Mock(return_value=30.0)
        self.runtime = SourceVerificationRuntime(self.clock)

    def observe(self) -> object:
        """Run actual descriptor hashing with a small chunk for boundary injections."""
        with patch.object(module, "CHUNK_BYTES", 128):
            return observe_external_media_snapshot(self.snapshot, self.runtime)

    def test_single_hash_returns_same_nine_field_identity_without_reopening(self) -> None:
        """Capture reuses exactly one original hash pass and no current-stat baseline."""
        with patch.object(module, "_hash_descriptor", wraps=module._hash_descriptor) as hashes:
            value = self.observe()
        self.assertEqual(hashes.call_count, 1)
        self.assertEqual((value.path, value.sha256, value.size_bytes), (str(self.path), self.snapshot.sha256, len(self.data)))
        self.assertEqual(value.stat_identity, snapshot_stat_identity(self.path.lstat()))
        self.assertGreater(self.clock.call_count, len(self.data) // 128)

    def test_legacy_verifier_still_returns_none(self) -> None:
        """Old callers retain their no-result contract and do not create a work clock."""
        self.assertIsNone(verify_external_media_snapshot(self.snapshot))
        self.clock.assert_not_called()

    def test_path_replaced_after_successful_hash_cannot_rebind_returned_identity(self) -> None:
        """The completed FD hash cannot be attached to a different current path inode."""
        actual = module._hash_descriptor

        def swap(fd: int, maximum: int, runtime: object) -> tuple[str, int]:
            """Hash genuine original bytes, then replace the path before the final check."""
            result = actual(fd, maximum, runtime)
            self.path.rename(self.root / "TEST-original")
            self.path.write_bytes(self.data)
            return result

        with patch.object(module, "_hash_descriptor", side_effect=swap), self.assertRaisesRegex(RuntimeError, "identity changed"):
            self.observe()

    def test_mode_change_after_hash_is_not_hidden_by_same_content(self) -> None:
        """Mode is one of the nine held fields, even if byte SHA remains unchanged."""
        actual = module._hash_descriptor

        def chmod(fd: int, maximum: int, runtime: object) -> tuple[str, int]:
            """Change one permission bit without changing the source payload."""
            result = actual(fd, maximum, runtime)
            self.path.chmod(self.path.stat().st_mode ^ 0o010)
            return result

        with patch.object(module, "_hash_descriptor", side_effect=chmod), self.assertRaisesRegex(RuntimeError, "identity changed"):
            self.observe()

    def test_growth_fails_at_original_size_without_waiting_for_unbounded_eof(self) -> None:
        """Appended bytes cannot exceed the original exact size under a still-positive clock."""
        actual, calls = os.read, []

        def grow(fd: int, size: int) -> bytes:
            """Append after the first actual chunk and track bounded subsequent reads."""
            data = actual(fd, size)
            calls.append(size)
            if len(calls) == 1:
                with self.path.open("ab") as stream:
                    stream.write(b"x" * 10000)
            return data

        with patch.object(module.os, "read", side_effect=grow), self.assertRaisesRegex(RuntimeError, "grew"):
            self.observe()
        self.assertLessEqual(len(calls), len(self.data) // 128 + 1)

    def test_expiry_between_chunks_is_terminal_and_closes_original_descriptor(self) -> None:
        """A failed hash has no retained identity, retry or renewed work allowance."""
        opened, actual = [], module._source_fd

        def open_source(path: str) -> int:
            """Retain only the real opened descriptor number for closure assertion."""
            fd = actual(path)
            opened.append(fd)
            return fd

        self.clock.side_effect = [30, 29, 28, RuntimeError("TEST expired")]
        with patch.object(module, "_source_fd", side_effect=open_source), self.assertRaisesRegex(RuntimeError, "expired"):
            self.observe()
        self.assertEqual(len(opened), 1)
        with self.assertRaises(OSError):
            os.fstat(opened[0])

    def test_failed_initial_fstat_also_closes_opened_descriptor(self) -> None:
        """An acquisition failure cannot leave an unowned source descriptor behind."""
        fd = os.open(self.path, os.O_RDONLY)
        with patch.object(module.os, "open", return_value=fd), patch.object(module.os, "fstat", side_effect=OSError("TEST fstat")):
            with self.assertRaises(OSError):
                module._source_fd(str(self.path))
        with self.assertRaises(OSError):
            os.fstat(fd)

    def test_invalid_original_clock_refuses_before_source_open(self) -> None:
        """Absent, nonfinite or boolean time is not a new budget."""
        for value in (True, 0, float("inf"), float("nan")):
            self.clock.return_value = value
            with patch.object(module, "_source_fd") as opened, self.assertRaises(RuntimeError):
                self.observe()
            opened.assert_not_called()


if __name__ == "__main__":
    unittest.main()
