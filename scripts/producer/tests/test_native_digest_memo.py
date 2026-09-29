"""Same-process digest memo: reuse only exact unchanged identities; every mutation re-reads."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused
from studio import native_digest_memo as memo
from studio.native_runtime import digest
from studio.native_short_worker import verify_files
from studio.native_stage_evidence import MAX_NATIVE_FILE_BYTES, verify_pins

SETTLED = 60 * 10 ** 9  # pretend the memo's racy-clean margin elapsed long ago


def hashed_files() -> float:
    """Full reads performed so far in this process."""
    return memo.totals()['hashedFiles']


class NativeDigestMemoTests(unittest.TestCase):
    """Memo hits never change a verdict; every tested mutation class forces a full read."""

    def setUp(self) -> None:
        """Fresh files, an empty memo and a clock past every file's racy margin."""
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp'))).resolve()
        self.file = self.base / 'pinned.bin'
        self.file.write_bytes(b'A' * 4096)
        memo.forget()
        self.addCleanup(memo.forget)
        self.enterContext(mock.patch.object(memo, '_now_ns', lambda: time.time_ns() + SETTLED))

    def test_repeat_is_memoized_and_matches_a_cold_read(self) -> None:
        """Only the first check reads bytes; the digest equals a direct hash."""
        first = digest(self.file)
        before = hashed_files()
        self.assertEqual(digest(self.file), first)
        self.assertEqual(hashed_files(), before)
        memo.forget()
        self.assertEqual(digest(self.file), first)
        self.assertEqual(hashed_files(), before + 1)

    def test_same_size_in_place_rewrite_is_read_again(self) -> None:
        """An overwrite with identical length still changes mtime/ctime."""
        first = digest(self.file)
        with self.file.open('r+b') as handle:
            handle.write(b'B')
        self.assertNotEqual(digest(self.file), first)

    def test_rewrite_with_restored_mtime_is_caught_by_ctime(self) -> None:
        """utime can restore mtime but user space cannot restore ctime."""
        first = digest(self.file)
        info = self.file.stat()
        time.sleep(0.01)
        with self.file.open('r+b') as handle:
            handle.write(b'C')
        os.utime(self.file, ns=(info.st_atime_ns, info.st_mtime_ns))
        self.assertEqual(self.file.stat().st_mtime_ns, info.st_mtime_ns)
        self.assertNotEqual(digest(self.file), first)

    def test_same_size_replacement_by_rename_is_read_again(self) -> None:
        """A new inode at the same path never inherits the old digest."""
        first = digest(self.file)
        replacement = self.base / 'replacement.bin'
        replacement.write_bytes(b'D' * 4096)
        info = self.file.stat()
        os.utime(replacement, ns=(info.st_atime_ns, info.st_mtime_ns))
        os.replace(replacement, self.file)
        self.assertNotEqual(digest(self.file), first)

    def test_symlink_swap_is_read_again(self) -> None:
        """A followed link retargeted to another same-size file changes both identities."""
        other = self.base / 'other.bin'
        other.write_bytes(b'E' * 4096)
        link = self.base / 'link.bin'
        link.symlink_to(self.file)
        first = digest(link)
        swapped = self.base / 'swapped.bin'
        swapped.symlink_to(other)
        os.replace(swapped, link)
        self.assertNotEqual(digest(link), first)
        self.assertEqual(digest(link), digest(other))

    def test_no_follow_hash_rejects_links_even_after_a_followed_memo(self) -> None:
        """The stage-evidence variant keeps file_hash's symlink and hard-link refusals."""
        link = self.base / 'link.bin'
        link.symlink_to(self.file)
        digest(link)
        with self.assertRaises(OSError):
            memo.pinned_file_hash(link, MAX_NATIVE_FILE_BYTES)
        value = memo.pinned_file_hash(self.file, MAX_NATIVE_FILE_BYTES)
        self.assertEqual(value, digest(self.file))
        os.link(self.file, self.base / 'hardlink.bin')
        with self.assertRaisesRegex(RuntimeError, 'unsafe'):
            memo.pinned_file_hash(self.file, MAX_NATIVE_FILE_BYTES)

    def test_no_follow_hash_keeps_its_size_bound_on_a_memo_hit(self) -> None:
        """A memoized digest is not returned for a caller whose byte limit is smaller."""
        with mock.patch.object(memo, 'file_hash', return_value='b' * 64) as full:
            self.assertEqual(memo.pinned_file_hash(self.file, MAX_NATIVE_FILE_BYTES), 'b' * 64)
        full.assert_called_once_with(self.file, maximum=MAX_NATIVE_FILE_BYTES)
        memo.forget()
        memo.pinned_file_hash(self.file, MAX_NATIVE_FILE_BYTES)
        with self.assertRaisesRegex(RuntimeError, 'over budget'):
            memo.pinned_file_hash(self.file, 1024)

    def test_recent_files_are_never_memoized(self) -> None:
        """Inside the racy margin every check is a full read."""
        with mock.patch.object(memo, '_now_ns', time.time_ns):
            fresh = self.base / 'fresh.bin'
            fresh.write_bytes(b'F' * 64)
            before = hashed_files()
            digest(fresh)
            digest(fresh)
            self.assertEqual(hashed_files(), before + 2)

    def test_change_during_the_read_is_not_memoized(self) -> None:
        """An identity that moved between stat and read leaves no memo entry."""
        real_observe, calls = memo._observe, []

        def moving(path: Path):
            calls.append(path)
            value = real_observe(path)
            return value if len(calls) == 1 else None
        with mock.patch.object(memo, '_observe', moving):
            digest(self.file)
        before = hashed_files()
        digest(self.file)
        self.assertEqual(hashed_files(), before + 1)

    def test_runtime_change_between_worker_checks_is_rejected(self) -> None:
        """verify_files memoizes the first read but still refuses a later changed runtime."""
        runtime = self.base / 'native-capture-library.mjs'
        runtime.write_text('export const version = 1;')
        pins = {str(runtime): digest(runtime), str(self.file): digest(self.file)}
        verify_files({'pins': pins})
        verify_files({'pins': pins})
        runtime.write_text('export const version = 2;')  # same size, same process
        with self.assertRaisesRegex(RuntimeError, 'native-capture-library.mjs'):
            verify_files({'pins': pins})

    def test_donor_mutation_between_same_process_verifications_is_rejected(self) -> None:
        """A donor artifact changed in place after a memoized pass fails the next pin check."""
        donor = self.base / 'donor-picture.mp4'
        donor.write_bytes(b'G' * 8192)
        pins = {str(donor): memo.pinned_file_hash(donor, MAX_NATIVE_FILE_BYTES)}
        verify_pins(pins)
        with donor.open('r+b') as handle:
            handle.seek(100)
            handle.write(b'H')
        with self.assertRaisesRegex(ValueError, 'changed input'):
            verify_pins(pins)

    def test_telemetry_records_boundary_counts_and_never_fails_the_check(self) -> None:
        """Each boundary appends one row; an unwritable root is ignored."""
        digest(self.file)
        with memo.integrity_boundary(self.base, 'test-boundary'):
            digest(self.file)
        row = json.loads((self.base / memo.TELEMETRY_NAME).read_text().splitlines()[-1])
        self.assertEqual((row['boundary'], row['status'], row['files']), ('test-boundary', 'completed', 1))
        self.assertEqual((row['memoFiles'], row['memoBytes'], row['hashedFiles']), (1, 4096, 0))
        with memo.integrity_boundary(self.base / 'missing-directory', 'unwritable'):
            digest(self.file)
        with self.assertRaises(ValueError), memo.integrity_boundary(self.base, 'failing'):
            raise ValueError('check failed')
        row = json.loads((self.base / memo.TELEMETRY_NAME).read_text().splitlines()[-1])
        self.assertEqual((row['boundary'], row['status']), ('failing', 'failed'))


class MemoizedStageEvidenceTests(unittest.TestCase):
    """Seals/reads keep their verdicts with the memo; telemetry stays in the sealing attempt."""

    def setUp(self) -> None:
        """Reuse the existing stage-evidence fixture with every file past the racy margin."""
        from test_native_stage_evidence import NativeStageEvidenceTests
        memo.forget()
        self.addCleanup(memo.forget)
        self.enterContext(mock.patch.object(memo, '_now_ns', lambda: time.time_ns() + SETTLED))
        NativeStageEvidenceTests.setUp(self)

    def test_read_after_seal_is_memoized_and_detects_same_size_artifact_change(self) -> None:
        """A sealed artifact rewritten in place (same length) fails the same-process read."""
        from studio import native_stage_evidence as stages
        stages.seal_stage(self.spec)
        before = hashed_files()
        stages.read_stage(self.receipt, self.inputs, 'render')
        self.assertEqual(hashed_files(), before + 1, 'only the new seal receipt is read in full')
        stages.read_stage(self.receipt, self.inputs, 'render')
        self.assertEqual(hashed_files(), before + 1, 'unchanged evidence should not be re-read')
        artifact = self.artifacts['picture']
        data = artifact.read_bytes()
        artifact.write_bytes(data[:-1] + (b'X' if data[-1:] != b'X' else b'Y'))
        with self.assertRaises(ValueError):
            stages.read_stage(self.receipt, self.inputs, 'render')

    def test_seal_telemetry_is_written_only_in_the_sealing_root(self) -> None:
        """Reading a donor never writes beside the donor."""
        from studio import native_stage_evidence as stages
        stages.seal_stage(self.spec)
        telemetry = self.root / memo.TELEMETRY_NAME
        rows = [json.loads(line) for line in telemetry.read_text().splitlines()]
        self.assertEqual([row['boundary'] for row in rows], ['stage-seal:render'])
        stages.read_stage(self.receipt, self.inputs, 'render')
        self.assertEqual(len(telemetry.read_text().splitlines()), 1)


if __name__ == '__main__':
    unittest.main()
