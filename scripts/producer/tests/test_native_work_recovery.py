"""Recovery regression tests use private fixtures, never the real heavy lane."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import native_work_lease as work
import native_work_recovery as recovery


class NativeWorkRecoveryTests(unittest.TestCase):
    """Real locks and files with controlled process-table facts."""

    def setUp(self) -> None:
        """Make a real uncompleted fixture lease and a fake dead supervisor."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()/'registry'
        for module in (work,recovery):
            patch = mock.patch.object(module,'state_root',return_value=self.root)
            patch.start()
            self.addCleanup(patch.stop)
        self.lease = work.NativeWorkLease.acquire('heavy','/TEST/project')
        self.addCleanup(self.lease.close)
        self.lease.record_processes([dict(pid=24567,pgid=24567,started='Wed Sep  9 11:00:00 2026')])
        self.nonce = self.lease.record['nonce']
        self.path = self.root/'heavy.active.json'
        record = json.loads(self.path.read_text())
        record['supervisorPid'] = 987654321
        self.path.write_text(json.dumps(record))
        self.before = self.path.read_bytes()
        self.process_result = mock.Mock(returncode=0,stdout='1 0 1 Wed Sep  9 01:00:00 2026\n',stderr='')
        patch = mock.patch.object(recovery.subprocess,'run',return_value=self.process_result)
        patch.start()
        self.addCleanup(patch.stop)

    def test_live_kernel_owner_blocks_recovery(self) -> None:
        """Even an absent PID claim cannot bypass a real held flock."""
        with self.assertRaisesRegex(work.NativeWorkBusy,'still locked'):
            recovery.recover(self.nonce)
        self.assertEqual(self.path.read_bytes(),self.before)

    def test_exact_absence_archives_then_clears_only_marker(self) -> None:
        """Explicit recovery preserves the old record inside separate evidence."""
        self.lease.close()
        inode=(self.root/'heavy.lock').stat().st_ino
        result=recovery.recover(self.nonce)
        self.assertFalse(self.path.exists())
        proof=json.loads(Path(result['proof']).read_text())
        self.assertEqual(proof['originalMarker'],json.loads(self.before))
        self.assertEqual(proof['signals'],[])
        self.assertEqual(inode,(self.root/'heavy.lock').stat().st_ino)
        new=work.NativeWorkLease.acquire('heavy','/TEST/next')
        try:
            new.complete()
        finally:
            new.close()

    def test_wrong_nonce_preserves_obligation(self) -> None:
        """A stale recovery command cannot clear the current job's fence."""
        self.lease.close()
        with self.assertRaisesRegex(RuntimeError,'nonce'):
            recovery.recover('0'*32)
        self.assertEqual(self.path.read_bytes(),self.before)

    def test_live_supervisor_or_child_refuses_recovery(self) -> None:
        """Presence of either exact obligation prevents release."""
        self.lease.close()
        rows=['987654321 1 987654321 Wed Sep  9 11:00:00 2026\n',
              '24567 1 24567 Wed Sep  9 11:00:00 2026\n']
        for row in rows:
            self.process_result.stdout=row
            with self.assertRaises(work.NativeWorkBusy):
                recovery.recover(self.nonce)
            self.assertEqual(self.path.read_bytes(),self.before)

    def test_process_inspection_diagnostics_preserve_fence(self) -> None:
        """A failed measurement is never interpreted as zero live processes."""
        self.lease.close()
        self.process_result.stderr='Operation not permitted'
        with self.assertRaisesRegex(RuntimeError,'diagnostics'):
            recovery.recover(self.nonce)
        self.assertEqual(self.path.read_bytes(),self.before)

    def test_recycled_child_pid_does_not_block_or_get_signalled(self) -> None:
        """Recovery observes but never signals a later unrelated process."""
        self.lease.close()
        self.process_result.stdout='24567 1 24567 Wed Sep  9 12:00:00 2026\n'
        result=recovery.recover(self.nonce)
        self.assertEqual(result['reusedChildPids'],[24567])

    def test_empty_child_registry_is_not_automatic_cleanup_evidence(self) -> None:
        """An unknown launch window requires a different explicit investigation."""
        self.lease.close()
        value=json.loads(self.path.read_text())
        value['processes']=[]
        self.path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'nonempty'):
            recovery.recover(self.nonce)
        self.assertTrue(self.path.exists())


if __name__ == '__main__':
    unittest.main()
