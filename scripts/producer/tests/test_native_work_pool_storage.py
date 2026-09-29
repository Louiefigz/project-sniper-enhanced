"""Which filesystems the pool can charge exactly: real volumes, real disk images, and statfs doubles.

Real checks use this Mac's own volumes and two small TEST sparse images that the test
creates, attaches (hidden, under a private temporary folder) and detaches. The statfs
doubles cover network and stacked filesystems this host does not mount.
"""
from __future__ import annotations

import fcntl
import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import native_work_lease as work
import native_work_pool as pool
import native_work_pool_disk as disk
import native_work_pool_expand as expand
import native_work_pool_roots as pool_roots
import native_work_pool_storage as storage
from native_render_resources import GIB
from _native_pool_fixture import isolate_pool, project_dir, qualify_fixture_host

HDIUTIL = '/usr/bin/hdiutil'


def statfs(kind: str, source: str, local: bool = True) -> storage.Statfs:
    """A TEST statfs result naming a filesystem type, mount source and locality."""
    info = storage.Statfs()
    info.f_fstypename, info.f_mntfromname = kind.encode(), source.encode()
    info.f_flags = storage.MNT_LOCAL if local else 0
    return info


class StatfsDoubleTests(unittest.TestCase):
    """Refusal rules for filesystems this host does not mount (statfs and IOKit answers are TEST doubles)."""

    def space(self, info: storage.Statfs, protocol: tuple = ('Apple Fabric', 'Internal')) -> str:
        """Classify one TEST filesystem."""
        with mock.patch.object(storage, 'read_statfs', return_value=info), \
                mock.patch.object(storage, 'protocol', return_value=protocol):
            return storage.space('/TEST/directory', 42)

    def test_non_local_stacked_and_memory_filesystems_are_refused(self) -> None:
        """Network shares, nullfs/bindfs, tmpfs and devfs never get a space of their own."""
        cases = [(statfs('smbfs', '//TEST@server/share', local=False), 'is not a local filesystem'),
                 (statfs('nfs', 'server:/TEST', local=False), 'is not a local filesystem'),
                 (statfs('afpfs', 'afp://TEST', local=False), 'is not a local filesystem'),
                 (statfs('apfs', '/dev/disk3s5', local=False), 'is not a local filesystem'),
                 (statfs('nullfs', '/System/Volumes/Data/TEST'), "type 'nullfs' is not accounted"),
                 (statfs('bindfs', '/TEST'), "type 'bindfs' is not accounted"),
                 (statfs('tmpfs', 'tmpfs'), "type 'tmpfs' is not accounted"),
                 (statfs('APFS', '/dev/disk3s5'), "type 'APFS' is not accounted")]
        for info, message in cases:
            with self.subTest(kind=info.f_fstypename), self.assertRaisesRegex(storage.DiskUnaccountable, message):
                self.space(info)

    def test_only_real_disks_named_by_their_node_are_accounted(self) -> None:
        """Images and unidentified devices are refused; internal and external disks keep their space."""
        refused = [(statfs('hfs', '/dev/disk9s2'), ('Virtual Interface', 'File'), 'not a real disk'),
                   (statfs('apfs', '/dev/disk15s1'), ('Virtual Interface', 'File'), 'not a real disk'),
                   (statfs('exfat', '/dev/disk9s1'), ('Virtual Interface', 'RAM'), 'not a real disk'),
                   (statfs('apfs', '/dev/disk12s1'), (None, None), 'not a real disk'),
                   (statfs('apfs', '/dev/disk3s5'), ('USB', None), 'not a real disk'),
                   (statfs('apfs', 'com.apple.TimeMachine.TEST.local@/dev/disk3s5'), None, 'not a disk node'),
                   (statfs('apfs', '/dev/diskXs1'), None, 'not a disk node')]
        for info, protocol, message in refused:
            with self.subTest(source=info.f_mntfromname), self.assertRaisesRegex(storage.DiskUnaccountable, message):
                self.space(info, protocol)
        self.assertEqual(self.space(statfs('apfs', '/dev/disk3s1s1')), 'apfs-container:disk3')
        self.assertEqual(self.space(statfs('exfat', '/dev/disk9s1'), ('USB', 'External')), 'filesystem:42')
        self.assertEqual(self.space(statfs('msdos', '/dev/disk9s1'), ('Secure Digital', 'Internal')), 'filesystem:42')
        self.assertEqual(self.space(statfs('hfs', '/dev/disk4s2'), ('Thunderbolt', 'External')), 'filesystem:42')

    def test_unaccountable_earlier_record_is_charged_in_every_space(self) -> None:
        """An earlier engine's root on a refused filesystem is charged everywhere, never dropped."""
        record = {'diskDevice': os.stat('/dev').st_dev, 'diskReservationBytes': GIB, 'root': '/dev'}
        self.assertEqual(disk.record_spaces(record), {disk.EVERY_SPACE: GIB})


class RealVolumeTests(unittest.TestCase):
    """This Mac's internal volumes are accounted; disk images attached here are refused."""

    def test_internal_volumes_report_a_real_disk(self) -> None:
        """The temporary folder's volume is on an internal disk; devfs and autofs are refused."""
        found = disk.filesystem(tempfile.gettempdir())
        self.assertTrue(found.space.startswith('apfs-container:disk'), found)
        node = storage.read_statfs(tempfile.gettempdir()).f_mntfromname.decode().removeprefix('/dev/')
        interconnect, location = storage.protocol(node)
        self.assertIn(location, storage.REAL_LOCATIONS)
        self.assertNotEqual(interconnect, storage.VIRTUAL)
        with self.assertRaisesRegex(storage.DiskUnaccountable, "type 'devfs'"):
            disk.filesystem('/dev')

    def attach(self, kind: str, folder: Path) -> Path:
        """Create, attach (hidden) and schedule detaching one small TEST sparse image."""
        image, mount = folder / f'TEST-{kind}', folder / f'mnt-{kind}'
        mount.mkdir()
        filesystem = {'apfs': 'APFS', 'hfs': 'HFS+'}[kind]
        subprocess.run([HDIUTIL, 'create', '-quiet', '-size', '40m', '-fs', filesystem, '-volname', f'TEST{kind}',
                        '-type', 'SPARSE', str(image)], check=True, timeout=120)
        subprocess.run([HDIUTIL, 'attach', '-quiet', '-nobrowse', '-noautoopen', '-mountpoint', str(mount),
                        f'{image}.sparseimage'], check=True, timeout=120)
        self.addCleanup(subprocess.run, [HDIUTIL, 'detach', '-force', '-quiet', str(mount)], timeout=120)
        return mount

    def test_disk_images_never_admit_the_host_volume_bytes_twice(self) -> None:
        """Verification repro: reservations on Data, an APFS image and an HFS image were each admitted.

        Each image reports its own free bytes, but writing into it spends the free bytes of the
        volume holding its file, so three reservations that each fit alone overspent the host.
        """
        isolate_pool(self)
        qualify_fixture_host(self, {'heavy': 3, 'audio': 1})
        folder, data = project_dir(self, 'images'), project_dir(self, 'data')
        each = (disk.filesystem(str(data)).free - 10 * GIB) * 3 // 4  # each fits alone; three do not
        mounts = [self.attach(kind, folder) for kind in ('apfs', 'hfs')]
        for mount in mounts:
            with self.subTest(mount=mount.name):
                self.assertEqual(storage.read_statfs(str(mount)).f_fstypename, mount.name[4:].encode())
                self.assertEqual(storage.protocol(storage.read_statfs(str(mount)).f_mntfromname.decode()[5:]),
                                 (storage.VIRTUAL, 'File'))
                request = pool.PoolRequest('heavy', str(mount), root=str(mount), disk_bytes=each)
                try:
                    with self.assertRaisesRegex(storage.DiskUnaccountable, 'is not a real disk'):
                        work.NativeWorkLease.acquire('heavy', str(mount), request=request)
                finally:
                    request.withdraw()  # a supplied request keeps its ticket until its owner withdraws it
        lease = work.NativeWorkLease.acquire('heavy', str(data), request=pool.PoolRequest(
            'heavy', str(data), root=str(data), disk_bytes=each))
        self.addCleanup(lease.close)
        self.assertTrue(lease.record['diskSpace'].startswith('apfs-container:'))
        lease.complete()



class LedgerFreeClassificationTests(unittest.TestCase):
    """Earlier engines' member roots are classified before the host-wide ledger lock, never inside it."""

    def setUp(self) -> None:
        """A qualified TEST pool holding one quarantined member rewritten as an earlier engine's record."""
        self.root = isolate_pool(self)
        qualify_fixture_host(self, {'heavy': 3, 'audio': 1})
        self.project = str(project_dir(self))
        lost = work.NativeWorkLease.acquire('heavy', self.project)
        lost.close()
        path = self.root / 'pool-v1' / lost.marker
        record = {key: value for key, value in json.loads(path.read_text()).items()
                  if key not in ('diskSpace', 'diskAccounting')}
        path.write_text(json.dumps(record))
        self.older_root = record['root'] or record['project']

    def ledger_held(self) -> bool:
        """Whether some descriptor holds the pool ledger lock right now."""
        descriptor = os.open(self.root / 'pool-v1' / 'ledger.lock', os.O_RDWR)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        finally:
            os.close(descriptor)
        return False

    def test_no_foreign_root_is_classified_under_the_ledger(self) -> None:
        """Admission charges the earlier record by its root space, and never statted it under the lock."""
        real, seen = disk.filesystem, []
        def watched(path: str) -> disk.Filesystem:
            """Record whether the ledger was held while classifying the earlier engine's root."""
            if path == self.older_root:
                seen.append(self.ledger_held())
            return real(path)
        other = str(project_dir(self, 'other'))  # the requester's own root is statted in the transaction, as before
        with mock.patch.object(disk, 'filesystem', side_effect=watched):
            lease = work.NativeWorkLease.acquire('heavy', other, request=pool.PoolRequest('heavy', other, disk_bytes=0))
        self.addCleanup(lease.close)
        self.assertEqual((seen, lease.admission['diskReservedByOthersBytes']), ([False], 3 * GIB))
        lease.complete()

    def admit_other(self) -> dict:
        """One admission beside the earlier member (another root); return its admission record."""
        other = str(project_dir(self, f'other-{len(self._outcomes)}'))
        lease = work.NativeWorkLease.acquire('heavy', other, request=pool.PoolRequest('heavy', other, disk_bytes=0))
        self._outcomes.append(lease.admission)
        lease.complete()
        lease.close()
        return lease.admission

    def test_a_hung_root_is_charged_everywhere_by_one_thread(self) -> None:
        """30 attempts against a root that never answers: admitted each time, named, and one thread only."""
        self._outcomes, release, real = [], threading.Event(), disk.filesystem
        self.addCleanup(release.set)
        def hung(path: str) -> disk.Filesystem:
            """TEST: the earlier engine's root filesystem stops answering until the test ends."""
            if path == self.older_root:
                release.wait(60)
            return real(path)
        self.enterContext(mock.patch.object(pool_roots, 'ROOT_CLASSIFY_SECONDS', .2))
        self.enterContext(mock.patch.object(disk, 'filesystem', side_effect=hung))
        started = time.monotonic()
        for _ in range(30):
            admission = self.admit_other()
        self.assertLess(time.monotonic() - started, 20, 'only the first attempt waits for the pending thread')
        self.assertEqual(admission['diskChargedInEverySpace'],
                         [f'charged in every space: root {self.older_root} did not answer within 0.2 s'])
        threads = [thread for thread in threading.enumerate() if thread.name.startswith('sniper-pool-root:')
                   and thread.name.endswith(self.older_root)]
        self.assertEqual(len(threads), 1)
        self.assertFalse(self.ledger_held())

    def earlier_member(self, name: str) -> str:
        """One more quarantined member rewritten as an earlier engine's record; return its root."""
        project = str(project_dir(self, name))
        lost = work.NativeWorkLease.acquire('heavy', project)
        lost.close()
        path = self.root / 'pool-v1' / lost.marker
        record = {key: value for key, value in json.loads(path.read_text()).items()
                  if key not in ('diskSpace', 'diskAccounting')}
        path.write_text(json.dumps(record))
        return record['root'] or record['project']

    def hang(self, roots: set[str]) -> None:
        """TEST: these earlier roots stop answering until the test ends."""
        release, real = threading.Event(), disk.filesystem
        self.addCleanup(release.set)
        pool_roots._SLOTS.clear()  # forget classifications made before the roots hung
        def hung(path: str) -> disk.Filesystem:
            """Block on a hung root; answer every other path."""
            if path in roots:
                release.wait(60)
            return real(path)
        self.enterContext(mock.patch.object(disk, 'filesystem', side_effect=hung))

    def test_hung_roots_are_classified_concurrently(self) -> None:
        """Two hung roots cost one classification wait, not one per root."""
        self.hang({self.older_root, self.earlier_member('second')})
        self.enterContext(mock.patch.object(pool_roots, 'ROOT_CLASSIFY_SECONDS', 1.0))
        started = time.monotonic()
        notes = pool_roots.prescan().notes
        self.assertLess(time.monotonic() - started, 1.8)
        self.assertEqual(len(notes), 2)
        self.assertTrue(all('did not answer within 1 s' in note for note in notes), notes)

    def test_the_callers_deadline_bounds_the_prescan(self) -> None:
        """An owner's admission deadline and a Long monitor's tick cut the wait short (named)."""
        self.hang({self.older_root})
        other = str(project_dir(self, 'bounded'))
        started = time.monotonic()
        request = pool.PoolRequest('heavy', other, disk_bytes=0, until=time.monotonic() + .3)
        lease = work.NativeWorkLease.acquire('heavy', other, request=request)
        self.addCleanup(lease.close)
        self.assertLess(time.monotonic() - started, 2, 'admission never waits the full 5 s')
        self.assertEqual(lease.admission['diskChargedInEverySpace'],
                         [f"charged in every space: root {self.older_root} had not answered by this attempt's deadline"])
        started = time.monotonic()
        grant = expand.expand_disk(lease, {other: GIB}, time.monotonic() + .3)  # one monitor tick
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(len(grant['diskChargedInEverySpace']), 1)
        lease.complete()

    def test_a_crashing_classifier_is_a_conservative_charge(self) -> None:
        """A classifier that raises charges the member in every space and says why; admission proceeds."""
        self._outcomes = []
        self.enterContext(mock.patch.object(disk, 'root_space', side_effect=RuntimeError('TEST classifier crash')))
        notes = self.admit_other()['diskChargedInEverySpace']
        self.assertEqual(len(notes), 1)
        self.assertIn('classifier failed (RuntimeError: TEST classifier crash)', notes[0])
        self.assertNotIn('did not answer', notes[0])

    def test_a_record_without_root_or_project_is_charged_not_refused(self) -> None:
        """An earlier-engine record naming no root or project is charged everywhere, admission continues."""
        self._outcomes = []
        path = next((self.root / 'pool-v1').glob('m-*.json'))
        record = {key: value for key, value in json.loads(path.read_text()).items() if key not in ('root', 'project')}
        path.write_text(json.dumps(record))
        admission = self.admit_other()
        self.assertEqual(admission['diskReservedByOthersBytes'], 3 * GIB)  # charged in every space
        self.assertEqual(admission['diskChargedInEverySpace'],
                         [f"charged in every space: member {record['nonce']}: its record names no root or project"])

    def test_a_member_that_appears_after_classification_is_charged_everywhere(self) -> None:
        """Inside the lock only the pre-lock result is read; an unclassified earlier root costs every space."""
        record = json.loads(next((self.root / 'pool-v1').glob('m-*.json')).read_text())
        charges = pool_roots.RootCharges()
        self.assertEqual(disk.record_spaces(record, charges), {disk.EVERY_SPACE: 3 * GIB})
        self.assertIn('appeared after classification', charges.notes[0])
        self.assertEqual(disk.record_spaces(record, pool_roots.prescan()),
                         {disk.filesystem(self.project).space: 3 * GIB})

if __name__ == '__main__':
    unittest.main()
