"""Recovery regressions on private fixtures: legacy markers and quarantined pool members.

Process-table facts are controlled; locks, files and namespaces are real. Nothing
touches the host's canonical namespace (state_root is patched by the fixture).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

import native_work_lease as work
import native_work_pool as pool
import native_work_pool_disk as disk
import native_work_pool_expand as expand
import native_work_pool_recovery as pool_recovery
import native_work_recovery as recovery
from native_render_processes import process_table
from _native_pool_fixture import (
    hold_legacy_exclusive, isolate_pool, legacy_record, members, project_dir,
    qualify_fixture_host, write_legacy_marker,
)

CHILD = dict(pid=24567, pgid=24567, started='Wed Sep  9 11:00:00 2026')
DEAD = dict(pid=987654321, pgid=987654321, started='Wed Sep  9 10:00:00 2026')
NONCE = 'a' * 32
REAL_SNAPSHOT = pool_recovery.process_snapshot


def table(*rows: str) -> dict:
    """A controlled successful process-table read."""
    return process_table(''.join(rows) or '1 0 1 Wed Sep  9 01:00:00 2026\n')


class LegacyRecoveryTests(unittest.TestCase):
    """A heavy.active.json written by old lease code, recovered beside a running pool."""

    def setUp(self) -> None:
        """Write the legacy obligation of a dead old-code supervisor."""
        self.root = isolate_pool(self)
        self.path = self.root / 'heavy.active.json'
        self.before = write_legacy_marker(self.root, legacy_record(NONCE, 987654321, [CHILD]))
        self.ps = self.enterContext(mock.patch.object(pool_recovery, 'process_snapshot', return_value=table()))

    def test_live_legacy_owner_blocks_recovery(self) -> None:
        """An old-code exclusive holder means its job may still be running."""
        hold_legacy_exclusive(self, self.root)
        with self.assertRaisesRegex(work.NativeWorkBusy, 'still locked'):
            recovery.recover(NONCE)
        self.assertEqual(self.path.read_bytes(), self.before)

    def test_absence_archives_proof_while_pool_members_run(self) -> None:
        """A running pool member (shared legacy lock) does not block legacy recovery."""
        qualify_fixture_host(self, {'heavy': 3, 'audio': 1})
        project = str(project_dir(self))
        running = work.NativeWorkLease.acquire('heavy', project)
        self.addCleanup(running.close)
        self.assertEqual(running.admission['quarantinedChargedBytes'], 16 * 1024 ** 3)
        result = recovery.recover(NONCE)
        self.assertEqual(result['kind'], 'legacy-heavy')
        self.assertFalse(self.path.exists())
        proof = json.loads(Path(result['proof']).read_text())
        self.assertEqual(proof['originalMarker'], json.loads(self.before))
        self.assertEqual(proof['signals'], [])
        after = work.NativeWorkLease.acquire('heavy', project)
        self.assertEqual(after.admission['quarantinedChargedBytes'], 0)
        after.complete(); after.close(); running.complete()

    def test_wrong_nonce_preserves_obligation(self) -> None:
        """A stale recovery command cannot clear the current job's fence."""
        with self.assertRaisesRegex(RuntimeError, 'nonce'):
            recovery.recover('0' * 32)
        self.assertEqual(self.path.read_bytes(), self.before)

    def test_live_supervisor_or_child_refuses_recovery(self) -> None:
        """Presence of either recorded obligation prevents release."""
        for row in ('987654321 1 987654321 Wed Sep  9 11:00:00 2026\n',
                    '24567 1 24567 Wed Sep  9 11:00:00 2026\n'):
            self.ps.return_value = table(row)
            with self.assertRaises(work.NativeWorkBusy):
                recovery.recover(NONCE)
            self.assertEqual(self.path.read_bytes(), self.before)

    def test_process_inspection_diagnostics_preserve_fence(self) -> None:
        """A failed measurement is never interpreted as zero live processes."""
        denied = mock.Mock(returncode=0, stdout='1 0 1 X\n', stderr='Operation not permitted')
        with mock.patch.object(pool_recovery.subprocess, 'run', return_value=denied):
            with self.assertRaisesRegex(RuntimeError, 'diagnostics'):
                REAL_SNAPSHOT()
        self.ps.side_effect = RuntimeError('Process inspection returned diagnostics; recovery refused')
        with self.assertRaisesRegex(RuntimeError, 'diagnostics'):
            recovery.recover(NONCE)
        self.assertEqual(self.path.read_bytes(), self.before)

    def test_recycled_child_pid_does_not_block_or_get_signalled(self) -> None:
        """Recovery observes but never signals a later unrelated process."""
        self.ps.return_value = table('24567 1 24567 Wed Sep  9 12:00:00 2026\n')
        self.assertEqual(recovery.recover(NONCE)['reusedChildPids'], [24567])

    def test_empty_legacy_registry_is_not_cleanup_evidence(self) -> None:
        """Legacy records never declared launches, so an empty list proves nothing."""
        self.path.unlink()
        write_legacy_marker(self.root, legacy_record(NONCE, 987654321, []))
        with self.assertRaisesRegex(ValueError, 'nonempty'):
            recovery.recover(NONCE)
        self.assertTrue(self.path.exists())


class PoolMemberRecoveryTests(unittest.TestCase):
    """Per-member recovery keeps other members and releases only the proven slot."""

    def setUp(self) -> None:
        """Quarantine one declared member whose supervisor is replaced by a dead identity."""
        self.root = isolate_pool(self)
        self.project = str(project_dir(self))
        self.ps = self.enterContext(mock.patch.object(pool_recovery, 'process_snapshot', return_value=table()))

    def quarantine(self, phase: str, processes: list[dict], supervisor: dict = DEAD) -> str:
        """Admit, rewrite the record as a crashed supervisor's, then drop the lock."""
        request = pool.PoolRequest('heavy', self.project, declares_launch=True)
        lease = work.NativeWorkLease.acquire('heavy', self.project, request=request)
        self.addCleanup(lease.close)
        path = members(self.root)[0]
        path.write_text(json.dumps(dict(lease.record, phase=phase, processes=processes,
                                        supervisor=supervisor, supervisorPid=supervisor['pid'])))
        lease.close()
        return lease.nonce

    def test_held_member_lock_blocks_recovery(self) -> None:
        """A live supervisor's kernel lock is authoritative over any record content."""
        lease = work.NativeWorkLease.acquire('heavy', self.project)
        self.addCleanup(lease.close)
        with self.assertRaisesRegex(work.NativeWorkBusy, 'still held'):
            recovery.recover(lease.nonce)
        self.assertEqual(len(members(self.root)), 1)

    def test_admitted_member_with_empty_registry_is_recovered(self) -> None:
        """No declared launch plus an absent exact supervisor proves nothing was launched."""
        nonce = self.quarantine('admitted', [])
        result = recovery.recover(nonce)
        self.assertEqual((result['kind'], result['recordedIdentityCount']), ('pool-member', 0))
        self.assertEqual(members(self.root), [])
        self.assertFalse((self.root / 'pool-v1' / f'm-{nonce}.lock').exists())
        self.assertTrue(Path(result['proof']).is_file())
        work.NativeWorkLease.acquire('heavy', self.project).complete()

    def test_unknown_or_declared_launch_with_empty_registry_is_refused(self) -> None:
        """A child may exist without a recorded identity; recovery cannot prove absence."""
        for phase in ('launching', 'launch-state-unknown'):
            nonce = self.quarantine(phase, [])
            with self.subTest(phase=phase), self.assertRaisesRegex(ValueError, 'launch state cannot be proved'):
                recovery.recover(nonce)
            (self.root / 'pool-v1' / f'm-{nonce}.json').unlink()

    def test_recovery_releases_a_grown_reservation_on_every_filesystem(self) -> None:
        """A crashed Long's cache and attempt reservations stay charged until the proof clears both."""
        gib = 1024 ** 3
        qualify_fixture_host(self, {'heavy': 3, 'audio': 1})
        cache = str(project_dir(self, 'cache'))
        volumes = {cache: disk.Filesystem(7, 'TEST-volume-7', 55 * gib)}
        self.enterContext(mock.patch.object(disk, 'filesystem', side_effect=lambda path: volumes.get(
            path, disk.Filesystem(8, 'TEST-volume-8', 45 * gib))))
        request = pool.PoolRequest('heavy', self.project, declares_launch=True)
        lost = work.NativeWorkLease.acquire('heavy', self.project, request=request)
        self.addCleanup(lost.close)
        expand.expand_disk(lost, {cache: 40 * gib, self.project: 5 * gib})
        lost.close()
        replacement = work.NativeWorkLease.acquire('heavy', self.project)
        self.addCleanup(replacement.close)
        with self.assertRaisesRegex(pool.NativeWorkQuarantined, 'TEST-volume-7:'):
            expand.expand_disk(replacement, {cache: 10 * gib})
        path = self.root / 'pool-v1' / lost.marker  # the crashed supervisor's exact identity (TEST)
        path.write_text(json.dumps(dict(json.loads(path.read_text()), supervisor=DEAD, supervisorPid=DEAD['pid'])))
        result = recovery.recover(lost.nonce)
        proof = json.loads(Path(result['proof']).read_text())
        self.assertEqual(proof['originalRecord']['diskReservations'],
                         [{'device': 7, 'space': 'TEST-volume-7', 'bytes': 40 * gib},
                          {'device': 8, 'space': 'TEST-volume-8', 'bytes': 8 * gib}])
        expand.expand_disk(replacement, {cache: 40 * gib})
        replacement.complete()

    def test_exact_supervisor_identity_decides_absence(self) -> None:
        """A live exact supervisor refuses; a recycled PID with another start does not."""
        nonce = self.quarantine('launching', [CHILD])
        self.ps.return_value = table('987654321 1 987654321 Wed Sep  9 10:00:00 2026\n')
        with self.assertRaisesRegex(work.NativeWorkBusy, 'supervisor is still running'):
            recovery.recover(nonce)
        self.ps.return_value = table('24567 1 24567 Wed Sep  9 11:00:00 2026\n')
        with self.assertRaisesRegex(work.NativeWorkBusy, 'children are still alive'):
            recovery.recover(nonce)
        self.ps.return_value = table('987654321 1 987654321 Wed Sep  9 13:00:00 2026\n')
        result = recovery.recover(nonce)
        self.assertTrue(result['supervisorPidReused'])
        self.assertEqual(members(self.root), [])


if __name__ == '__main__':
    unittest.main()
