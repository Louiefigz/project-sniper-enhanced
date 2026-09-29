"""Mixed engines on one pool: the unmodified base (4a15560) client beside this one, in both launch orders.

Three members whose guarantees the base client cannot see, each tested with the base client
launched after (new first) and before (old first) the new member:
- an exclusive member (a Long no profile covers);
- an off-root disk reservation (a member growing onto another filesystem; Longs are already
  fenced at admission as exclusive or schema-2 members, so the hook is shown on a member the
  admission did not fence, on TEST non-APFS volumes);
- a root admission on a sibling APFS volume (different st_dev, same container as the base
  client's volume), on this Mac's real Preboot or VM volume.
The base client runs from tests/fixtures/base_pool_driver.py (hash-checked vendored modules);
both share a private TEST namespace and a TEST schema-1 record. Nothing reads the host pool.
"""
from __future__ import annotations

import os
import signal
import time
import unittest
from pathlib import Path
from unittest import mock

import native_work_lease as work
import native_work_pool as pool
import native_work_pool_disk as disk
import native_work_pool_expand as expand
import native_work_recovery as recovery
from native_render_resources import GIB
from native_work_pool_fence import NativeWorkUnsupportedMix
from native_work_pool_state import NativeWorkQueued
from _native_pool_fixture import (
    CURRENT_DRIVER, BasePoolClient, isolate_pool, members, plan_project, project_dir, qualify_fixture_host,
)

CRASH_DRIVER = CURRENT_DRIVER.with_name('crash_member_driver.py')

SIBLINGS = ('/System/Volumes/Preboot', '/System/Volumes/VM')


class MixedEngineTests(BasePoolClient, unittest.TestCase):
    """Every member the base client cannot account keeps it out; nothing the new client admits overspends."""

    def setUp(self) -> None:
        """Private namespace, a TEST schema-1 record (3 heavy, 1 audio), a Short and a Long project."""
        self.root = isolate_pool(self)
        self.records = qualify_fixture_host(self, {'heavy': 3, 'audio': 1})
        self.short = str(plan_project(self, 'short', 45.0))
        self.long = str(plan_project(self, 'long', 600.0))

    def acquire(self, project: str, root: str | None = None) -> object:
        """Admit a new-client heavy member in this process (closed at cleanup)."""
        return self.acquire_lane('heavy', project, root)

    def acquire_lane(self, lane: str, project: str, root: str | None = None) -> object:
        """Admit a new-client member of `lane` in this process (closed at cleanup)."""
        request = pool.PoolRequest(lane, project, root=root, declares_launch=True)
        try:
            lease = work.NativeWorkLease.acquire(lane, project, request=request)
        finally:
            request.withdraw()
        self.addCleanup(lease.close)
        return lease

    def sibling(self) -> str:
        """A real APFS volume of the temporary folder's container on another device."""
        path = next((path for path in SIBLINGS if Path(path).is_dir()), None)
        self.assertIsNotNone(path, 'this macOS host must expose an APFS system volume')
        here, there = disk.filesystem(self.short), disk.filesystem(path)
        self.assertEqual(here.space, there.space)
        self.assertNotEqual(here.device, there.device)
        return path

    def fake_volumes(self) -> tuple[str, str]:
        """TEST non-APFS volumes for the new client: attempt on device 8, cache on device 7."""
        attempt, cache = str(project_dir(self, 'attempt')), str(project_dir(self, 'cache'))
        volumes = {attempt: disk.Filesystem(8, 'filesystem:8', 500 * GIB),
                   cache: disk.Filesystem(7, 'filesystem:7', 500 * GIB)}
        real = disk.filesystem
        self.enterContext(mock.patch.object(disk, 'filesystem', side_effect=lambda path: volumes.get(
            path) or real(path)))
        return attempt, cache

    def older_member(self) -> object:
        """A base-client member on the Short's volume, held until send(process, 'done')."""
        holder = self.base('admit-disk', self.short, str(project_dir(self, 'older')), str(3 * GIB),
                           str(500 * GIB), stdin=True)
        self.send(holder)
        self.assertEqual([self.event(holder)['event'] for _ in range(2)], ['transacting', 'admitted'])
        return holder

    def release(self, holder: object) -> None:
        """Complete a base-client member and require a clean exit."""
        self.send(holder, 'done')
        self.assertEqual(holder.wait(timeout=30), 0)

    def assert_older_queued(self, lane: str = 'heavy') -> None:
        """A new base-client request queues (never admitted) behind the fence."""
        probe = self.base('queue', lane, self.short)
        refused = self.event(probe)
        self.assertEqual(refused['event'], 'queued', refused)
        self.assertIn('queued behind', refused['reason'])
        self.stop(probe)

    def assert_older_resumes(self, lease: object) -> dict:
        """A waiting base client is admitted only after the fenced member completes; it then completes."""
        waiter = self.base('hold', 'heavy', self.short, '1')
        time.sleep(2)
        released = time.time()
        lease.complete()
        admitted = self.event(waiter)
        self.assertEqual(admitted['event'], 'admitted', admitted)
        self.assertGreaterEqual(admitted['at'], released)
        self.assertEqual(self.event(waiter)['event'], 'completed')
        return admitted

    def test_new_first_exclusive_member(self) -> None:
        """An uncovered Long runs alone behind its fence: base heavy and audio requests queue, then resume."""
        long = self.acquire(self.long)
        self.assertEqual((long.admission['mode'], len(long.fence)), ('exclusive', 2))
        self.assert_older_queued('heavy')
        self.assert_older_queued('audio')
        self.assertEqual(self.assert_older_resumes(long)['mode'], 'qualified')

    def test_old_first_exclusive_member(self) -> None:
        """Beside a live base member an uncovered Long fails at once; alone it runs fenced."""
        holder = self.older_member()
        with self.assertRaisesRegex(NativeWorkUnsupportedMix, 'no SLA is promised'):
            self.acquire(self.long)
        self.release(holder)
        long = self.acquire(self.long)
        self.assertEqual((long.admission['mode'], len(long.fence)), ('exclusive', 2))
        self.assert_older_queued()
        long.complete()

    def test_new_first_off_root_disk_reservation(self) -> None:
        """Growing onto another filesystem fences an unfenced member before the bytes are reserved."""
        attempt, cache = self.fake_volumes()
        member = self.acquire(self.short, root=attempt)
        self.assertEqual((member.fence, member.admission['fence']), ([], []))
        expand.expand_disk(member, {attempt: GIB})
        self.assertEqual(member.fence, [], 'bytes on its own root device stay visible to the base client')
        grant = expand.expand_disk(member, {cache: 5 * GIB})
        self.assertEqual([row['space'] for row in grant['filesystems']], ['filesystem:7'])
        self.assertEqual(len(member.fence), 2)
        self.assert_older_queued('heavy')
        self.assert_older_queued('audio')
        self.assert_older_resumes(member)
        self.assertEqual(sorted(self.root.glob('pool-v1/t-*.json')), [])

    def test_old_first_off_root_disk_reservation(self) -> None:
        """Beside live base members the fence is taken, even with a base request queued; that request waits."""
        attempt, cache = self.fake_volumes()
        first = self.older_member()
        member = self.acquire(self.short, root=attempt)
        second = self.older_member()  # the three heavy slots are full
        waiting = self.base('hold', 'heavy', self.short, '1')
        time.sleep(1.5)
        expand.expand_disk(member, {cache: 5 * GIB})  # a queued base request never refuses the growth
        self.assertEqual((len(member.fence), 'diskReservations' in member.record), (2, True))
        self.release(second)
        time.sleep(2.5)  # a heavy slot is free; the base request waits behind the fence
        self.assertEqual(len(members(self.root)), 2)
        member.complete()
        self.assertEqual(self.event(waiting)['event'], 'admitted')
        self.assertEqual(self.event(waiting)['event'], 'completed')
        self.release(first)

    def test_new_first_sibling_apfs_root_admission(self) -> None:
        """A root on a sibling volume is fenced; without the fence the base client would not see its bytes."""
        sibling = self.sibling()
        member = self.acquire(self.short, root=sibling)
        self.assertEqual(member.record['diskDevice'], os.stat(sibling).st_dev)
        self.assertIn(f'disk reserved in {disk.filesystem(sibling).space}', member.admission['fence'][0])
        self.assert_older_queued()
        self.assert_older_resumes(member)
        with mock.patch.object(disk, 'fence_reasons', return_value=[]):  # negative control: no fence
            unfenced = self.acquire(self.short, root=sibling)
        joined = self.base('hold', 'heavy', self.short, '30')
        seen = self.event(joined)
        self.assertEqual(seen['event'], 'admitted', 'without its fence the base client joins')
        self.assertEqual(seen['diskReservedByOthersBytes'], 0, 'the base client keys disk by device')
        beside = self.acquire(self.short)
        self.assertEqual(beside.admission['diskReservedByOthersBytes'], 6 * GIB, 'this client keys by container')
        for lease in (beside, unfenced):
            lease.complete()

    def test_old_first_sibling_apfs_root_admission(self) -> None:
        """Beside a live base member a sibling-volume root is admitted fenced and charges that member's bytes."""
        sibling = self.sibling()
        holder = self.older_member()
        member = self.acquire(self.short, root=sibling)
        self.assertEqual(len(member.fence), 2)
        self.assertEqual(member.admission['diskReservedByOthersBytes'], 3 * GIB)  # the base member, by container
        self.assert_older_queued()
        self.release(holder)
        member.complete()


    def test_new_shorts_overlap_while_an_older_request_waits(self) -> None:
        """The p2 convoy: with a base request queued, this engine still runs 3 heavy + 1 audio at once."""
        shorts = [str(plan_project(self, 'short', 45.0)) for _ in range(4)]
        first = self.acquire(shorts[0])
        waiting = self.base('hold', 'heavy', self.short, '1')
        time.sleep(1.5)  # the base request is queued behind the first member's fence
        started = time.monotonic()
        heavy = [first] + [self.acquire(project) for project in shorts[1:3]]
        audio = self.acquire_lane('audio', shorts[3])
        self.assertLess(time.monotonic() - started, 2, 'fenced Shorts never wait for the queued base request')
        self.assertEqual([len(lease.fence) for lease in (*heavy, audio)], [2, 2, 2, 2])
        self.assertEqual(len(members(self.root)), 4)
        for lease in (*heavy, audio):
            lease.complete()
        self.assertEqual(self.event(waiting)['event'], 'admitted')

    def test_fenced_request_is_not_held_behind_an_older_request(self) -> None:
        """Regression for the exact interleaving: N0 live, O3 queued behind N0's fence, then N1 arrives."""
        n0 = self.acquire(self.short)
        o3 = self.base('hold', 'heavy', self.short, '1')
        time.sleep(1.5)
        n1 = self.acquire(str(plan_project(self, 'short', 45.0)))  # admitted: O3 sorts behind its fence
        n0.complete()
        time.sleep(2.5)
        self.assertEqual(len(members(self.root)), 1, 'O3 still waits behind N1')
        n1.complete()
        self.assertEqual(self.event(o3)['event'], 'admitted')

    def test_counting_older_requests_would_deadlock(self) -> None:
        """Negative control: without the skip, N1 waits for O3 by FIFO while O3 waits for N1's fence."""
        import native_work_pool_fence as fence
        import native_work_pool_mix as mix
        n0 = self.acquire(self.short)
        o3 = self.base('hold', 'heavy', self.short, '1')
        time.sleep(1.5)
        n1 = pool.PoolRequest('heavy', self.short, declares_launch=True)
        self.addCleanup(n1.withdraw)
        with mock.patch.object(mix, 'competing', side_effect=lambda view, fenced: fence.request_tickets(view)):
            with self.assertRaisesRegex(NativeWorkQueued, 'queued behind 1 earlier request'):
                work.NativeWorkLease.acquire('heavy', self.short, request=n1)
            n0.complete()
            time.sleep(2.5)
            self.assertEqual(members(self.root), [], 'O3 waits for N1\'s fence ...')
            with self.assertRaisesRegex(NativeWorkQueued, 'queued behind 1 earlier request'):
                work.NativeWorkLease.acquire('heavy', self.short, request=n1)  # ... and N1 for O3
        n1.withdraw()  # releasing N1's fence breaks the cycle
        self.assertEqual(self.event(o3)['event'], 'admitted')

    def test_sigkilled_exclusive_owner_keeps_the_base_client_out(self) -> None:
        """A crashed exclusive Long leaves no fence but charges the whole budget: base requests are refused."""
        holder = self.base('hold', 'heavy', self.long, '600', driver=CURRENT_DRIVER)
        admitted = self.event(holder)
        self.assertEqual((admitted['event'], admitted['mode']), ('admitted', 'exclusive'))
        self.assert_older_queued()
        holder.send_signal(signal.SIGKILL)
        holder.wait(timeout=10)
        probe = self.base('hold', 'heavy', self.short, '1')
        refused = self.event(probe)
        self.assertEqual((refused['event'], refused['error']), ('refused', 'NativeWorkQuarantined'), refused)
        self.assertIn('quarantined and legacy reservations leave no room', refused['reason'])
        self.assertIn(admitted['nonce'], [path.stem[2:] for path in members(self.root)])

    def crash_then_probe(self, command: str, *paths: str) -> dict:
        """Start a fenced member of this engine, SIGKILL it, then send a base request; return its event."""
        member = self.base(command, self.short, *paths, stdin=True, driver=CRASH_DRIVER)
        events = [self.event(member) for _ in range(2 if command == 'offroot' else 1)]
        self.assertEqual(events[0]['fence'], 0 if command == 'offroot' else 2, events)
        self.assertEqual(events[-1]['fence'], 2, events)
        self.assertGreater(events[-1]['reservationBytes'], events[-1]['guardReservationBytes'])
        member.send_signal(signal.SIGKILL)
        member.wait(timeout=10)
        probe = self.base('hold', 'heavy', self.short, '1')
        refused = self.event(probe)
        recovery.recover(events[0]['nonce'])  # the next case starts from an empty pool
        return refused

    def test_sigkilled_fenced_members_keep_the_base_client_out(self) -> None:
        """A crashed sibling-APFS member and a crashed off-root-expanded member: fences lapse, charges stay."""
        cases = (('sibling', (self.sibling(),)),
                 ('offroot', (str(project_dir(self, 'crash-attempt')), str(project_dir(self, 'crash-cache')))))
        for command, paths in cases:
            with self.subTest(command=command):
                refused = self.crash_then_probe(command, *paths)
                self.assertEqual((refused['event'], refused['error']), ('refused', 'NativeWorkQuarantined'), refused)
                self.assertIn('quarantined and legacy reservations leave no room', refused['reason'])

if __name__ == '__main__':
    unittest.main()
