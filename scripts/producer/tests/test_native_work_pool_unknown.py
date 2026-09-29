"""Member records admission cannot read: live ones are waited for, quarantined ones are recoverable.

An unreadable record hides its class, memory and disk reservations. While its supervisor
holds the member lock the pool waits for it (NativeWorkQueued), including under a schema-2
profile that could not describe it; once the lock is free every disk admission is refused
until native_work_recovery removes it on proof of the free lock. Locks, files and the
recovery command are real; process tables are TEST doubles where named.
"""
from __future__ import annotations

import base64
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
from native_render_resources import GIB
from native_work_pool_state import NativeWorkQuarantined, NativeWorkQueued
from _native_pool_fixture import (
    fixture_profile, isolate_pool, members, plan_project, project_dir, qualify_fixture_host,
    qualify_fixture_profiles,
)

REAL_SNAPSHOT = pool_recovery.process_snapshot
DAMAGE = {'truncated JSON': lambda raw: raw[:40],
          'invalid class': lambda raw: json.dumps(dict(json.loads(raw), **{'class': 'TEST-bogus'})).encode(),
          'not an object': lambda raw: b'["TEST", "damaged"]\n',
          'unreadable disk rows': lambda raw: json.dumps(dict(json.loads(raw), diskReservations=[
              {'device': 1, 'space': 'TEST', 'bytes': GIB, 'TEST-extra': 1}], supervisor={})).encode()}


class UnknownMemberTests(unittest.TestCase):
    """Real pool members whose record bytes a TEST step damages."""

    def setUp(self) -> None:
        """Qualified TEST host with three heavy slots; the process table is empty unless a test says so."""
        self.root = isolate_pool(self)
        qualify_fixture_host(self, {'heavy': 3, 'audio': 1})
        self.project = str(project_dir(self))
        self.ps = self.enterContext(mock.patch.object(pool_recovery, 'process_snapshot',
                                                      return_value=process_table('1 0 1 Wed Sep  9 01:00:00 2026\n')))

    def acquire(self, project: str | None = None) -> object:
        """Admit one declared heavy member (closed at cleanup)."""
        project = project or self.project
        request = pool.PoolRequest('heavy', project, declares_launch=True)
        try:
            lease = work.NativeWorkLease.acquire('heavy', project, request=request)
        finally:
            request.withdraw()
        self.addCleanup(lease.close)
        return lease

    def damage(self, lease: object, how: str) -> bytes:
        """Rewrite a member's record bytes; return what was written."""
        path = self.root / 'pool-v1' / lease.marker
        raw = DAMAGE[how](path.read_bytes())
        path.write_bytes(raw)
        self.assertIsNone(disk.charged_spaces(pool_recovery._parsed(raw)), how)
        return raw

    def test_live_unreadable_member_is_waited_for(self) -> None:
        """Held member lock: admission and expansion wait (queued), never quarantine."""
        running, live = self.acquire(), self.acquire()
        original = (self.root / 'pool-v1' / live.marker).read_bytes()
        self.damage(live, 'truncated JSON')
        with self.assertRaisesRegex(NativeWorkQueued, 'record cannot be read') as caught:
            self.acquire()
        self.assertNotIn('quarantined', str(caught.exception))
        with self.assertRaisesRegex(NativeWorkQueued, 'Disk expansion refused: a live pool member'):
            expand.expand_disk(running, {self.project: GIB})
        with self.assertRaisesRegex(work.NativeWorkBusy, 'still held by its supervisor'):
            recovery.recover(live.nonce)
        (self.root / 'pool-v1' / live.marker).write_bytes(original)
        live.complete()
        self.acquire().complete()
        running.complete()

    def test_live_unreadable_member_is_waited_for_under_a_schema_2_profile(self) -> None:
        """A profile cannot describe it, so the mix check ignores it; capacity makes the request wait."""
        short = str(plan_project(self, 'short', 45.0))
        qualify_fixture_profiles(self, [fixture_profile({'heavy': 3, 'audio': 1})])
        live = self.acquire(short)
        original = (self.root / 'pool-v1' / live.marker).read_bytes()
        self.damage(live, 'invalid class')
        with self.assertRaisesRegex(NativeWorkQueued, 'record cannot be read'):
            self.acquire(short)
        (self.root / 'pool-v1' / live.marker).write_bytes(original)
        live.complete()

    def test_quarantined_unreadable_records_are_recovered_on_the_free_lock(self) -> None:
        """Truncated, invalid-class, non-object and bad-disk records: terminal until recovery removes them."""
        for how in DAMAGE:
            with self.subTest(damage=how):
                lost = self.acquire()
                lost.close()
                raw = self.damage(lost, how)
                with self.assertRaisesRegex(NativeWorkQuarantined, 'unknown disk reservations'):
                    self.acquire()
                result = recovery.recover(lost.nonce)
                self.assertEqual((result['kind'], result['memberLockPresent']), ('unreadable-pool-member', True))
                proof = json.loads(Path(result['proof']).read_text())
                self.assertEqual(base64.b64decode(proof['originalRecordBase64']), raw)
                self.assertEqual((proof['memberLockFree'], proof['signals']), (True, []))
                self.assertEqual(members(self.root), [])
                self.assertFalse((self.root / 'pool-v1' / f'm-{lost.nonce}.lock').exists())
                self.acquire().complete()

    def test_missing_lock_file_proves_nothing(self) -> None:
        """A live owner whose lock file was unlinked and whose record is unreadable is never removed."""
        live = self.acquire()
        (self.root / 'pool-v1' / f'm-{live.nonce}.lock').unlink()  # the owner still holds the deleted inode
        self.damage(live, 'truncated JSON')
        with self.assertRaisesRegex(work.NativeWorkBusy, 'has no liveness lock file'):
            recovery.recover(live.nonce)
        self.assertEqual(len(members(self.root)), 1)

    def test_unsafe_record_file_is_removed_by_name(self) -> None:
        """A record the pool refuses to open (here world-readable) is unknown; recovery removes it by name."""
        lost = self.acquire()
        lost.close()
        path = self.root / 'pool-v1' / lost.marker
        path.chmod(0o644)
        with self.assertRaisesRegex(NativeWorkQuarantined, 'unknown disk reservations'):
            self.acquire()
        result = recovery.recover(lost.nonce)
        proof = json.loads(Path(result['proof']).read_text())
        self.assertEqual((proof['kind'], proof['originalRecordBase64'], proof['readableIdentitiesChecked']),
                         ('unreadable-pool-member', None, 0))
        self.assertFalse(path.exists())
        self.acquire().complete()

    def test_a_readable_identity_that_is_still_running_blocks_removal(self) -> None:
        """The supervisor an invalid-class record still names is this live process: recovery refuses."""
        lost = self.acquire()
        lost.close()
        self.damage(lost, 'invalid class')
        self.ps.return_value = REAL_SNAPSHOT()
        with self.assertRaisesRegex(work.NativeWorkBusy, 'still running; recovery refused'):
            recovery.recover(lost.nonce)
        self.assertEqual(len(members(self.root)), 1)

    def test_readable_invalid_record_keeps_the_full_rules(self) -> None:
        """A readable member whose launch state cannot be proved is still refused, not removed on the lock."""
        lost = self.acquire()
        path = self.root / 'pool-v1' / lost.marker
        path.write_text(json.dumps(dict(json.loads(path.read_text()), phase='launching', processes=[])))
        lost.close()
        with self.assertRaisesRegex(ValueError, 'launch state cannot be proved'):
            recovery.recover(lost.nonce)
        self.assertTrue(path.exists())


if __name__ == '__main__':
    unittest.main()
