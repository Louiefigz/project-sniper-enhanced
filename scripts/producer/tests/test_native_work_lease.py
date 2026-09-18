"""Real kernel-lock and durable failure-fence tests; no media or browser jobs."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import native_work_lease as work


class NativeWorkLeaseTests(unittest.TestCase):
    """Use private temporary namespaces so tests never reserve the user's lane."""

    def setUp(self) -> None:
        """Create an isolated real filesystem namespace."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / 'registry'
        patch = mock.patch.object(work, 'state_root', return_value=self.root)
        patch.start()
        self.addCleanup(patch.stop)

    def acquire(self) -> work.NativeWorkLease:
        """Always close descriptors even when a regression assertion fails."""
        lease = work.NativeWorkLease.acquire('heavy', '/TEST/project')
        self.addCleanup(lease.close)
        return lease

    def test_real_subprocess_cannot_enter_held_lane(self) -> None:
        """A different interpreter/checkout cannot race through the same flock."""
        lease = self.acquire()
        before = (self.root / 'heavy.active.json').read_bytes()
        script = ('import sys; from pathlib import Path; import native_work_lease as w; '
                  'w.state_root=lambda:Path(sys.argv[1]); '
                  "w.NativeWorkLease.acquire('heavy','/TEST/other')")
        result = subprocess.run([sys.executable, '-c', script, str(self.root)],
                                capture_output=True, text=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('already active', result.stderr)
        self.assertEqual(before, (self.root / 'heavy.active.json').read_bytes())
        lease.complete()

    def test_close_without_cleanup_fences_the_next_launch(self) -> None:
        """Kernel lock release on crash does not erase uncertain child ownership."""
        self.acquire().close()
        with self.assertRaisesRegex(work.NativeWorkBusy, 'cleanup is unverified'):
            self.acquire()

    def test_completed_lane_reuses_the_original_mutex_inode(self) -> None:
        """No unlink/recreate race can manufacture a second independent lock."""
        lease = self.acquire()
        inode = (self.root / 'heavy.lock').stat().st_ino
        lease.complete()
        lease.close()
        second = self.acquire()
        self.assertEqual(inode, (self.root / 'heavy.lock').stat().st_ino)
        second.complete()

    def test_live_registered_child_prevents_completion(self) -> None:
        """A failed render cannot release capacity while its child survives."""
        lease = self.acquire()
        row = dict(pid=23456, pgid=23456, started='Wed Sep  9 11:00:00 2026')
        lease.record_processes([row])
        with mock.patch.object(work, '_live_identities', return_value=[23456]):
            with self.assertRaisesRegex(RuntimeError, 'live recorded'):
                lease.complete()
        self.assertTrue((self.root / 'heavy.active.json').exists())
        with mock.patch.object(work, '_live_identities', return_value=[]):
            lease.complete()

    def test_reparented_and_prior_identities_are_retained(self) -> None:
        """Reporting only current children cannot erase an earlier obligation."""
        lease = self.acquire()
        one = dict(pid=23456, pgid=23456, started='Wed Sep  9 11:00:00 2026')
        two = dict(pid=23457, pgid=23457, started='Wed Sep  9 11:00:01 2026')
        lease.record_processes([one])
        lease.record_processes([two])
        self.assertEqual(lease.record['processes'], [one, two])
        with mock.patch.object(work, '_live_identities', return_value=[]):
            lease.complete()

    def test_changed_active_record_refuses_release(self) -> None:
        """Ownership drift cannot delete another job's marker."""
        lease = self.acquire()
        path = self.root / 'heavy.active.json'
        path.write_text(json.dumps(dict(lease.record, nonce='different')))
        with self.assertRaisesRegex(RuntimeError, 'record changed'):
            lease.complete()
        self.assertTrue(path.exists())

    def test_malformed_and_symlink_markers_fail_closed(self) -> None:
        """Any existing active entry is a fence, including a dangling link."""
        self.root.mkdir(mode=0o700)
        (self.root / 'heavy.active.json').symlink_to(self.root / 'missing')
        with self.assertRaisesRegex(work.NativeWorkBusy, 'cleanup is unverified'):
            self.acquire()

    def test_recycled_pid_does_not_count_as_original_child(self) -> None:
        """Matching PID alone never grants lifecycle authority."""
        row = dict(pid=23456, pgid=23456, started='Wed Sep  9 11:00:00 2026')
        result = mock.Mock(stdout='23456 1 23456 Wed Sep  9 12:00:00 2026\n')
        with mock.patch.object(work.subprocess, 'run', return_value=result):
            self.assertEqual(work._live_identities([row]), [])

    def test_invalid_identity_rejected_without_changing_registry(self) -> None:
        """Boolean/system IDs and missing starts cannot become cleanup pins."""
        lease = self.acquire()
        for row in (dict(pid=True, pgid=2, started='TEST'), dict(pid=2, pgid=2, started='')):
            with self.assertRaises(ValueError):
                lease.record_processes([row])
        self.assertEqual(lease.record['processes'], [])
        lease.complete()

    def test_replaced_namespace_cannot_release_old_job_as_current(self) -> None:
        """Moving the directory cannot redirect cleanup to another lock family."""
        lease = self.acquire()
        self.root.rename(self.root.with_name('old-registry'))
        self.root.mkdir(mode=0o700)
        with self.assertRaisesRegex(RuntimeError, 'directory inode was replaced'):
            lease.complete()


if __name__ == '__main__':
    unittest.main()
