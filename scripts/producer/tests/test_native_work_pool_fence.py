"""The compatibility fence against the real base-engine (4a15560) pool client, in both launch orders.

The older client runs in separate processes from tests/fixtures/base_pool_driver.py, which
imports byte-identical copies of the base pool modules (checked against SOURCE.json). Both
clients share one private TEST namespace and one TEST schema-1 host record; the canonical
host pool and record are never read.
"""
from __future__ import annotations

import time
import unittest
from unittest import mock

import native_work_lease as work
import native_work_pool as pool
from native_render_resources import GIB
from native_work_pool_fence import NativeWorkUnsupportedMix
from native_work_pool_state import NativeWorkQuarantined
from _native_pool_fixture import BasePoolClient, isolate_pool, members, plan_project, project_dir, qualify_fixture_host

FENCED = ('TEST disk reserved on another filesystem',)
APFS = 'which older pool clients charge per volume'  # every new member on this Mac's APFS volumes


class BaseClientFenceTests(BasePoolClient, unittest.TestCase):
    """Older clients never join a fenced member; fenced work never joins older requests ahead of it."""

    def setUp(self) -> None:
        """Private namespace, a TEST Short and a TEST Long project."""
        self.root = isolate_pool(self)
        self.short = str(plan_project(self, 'short', 45.0))
        self.long = str(plan_project(self, 'long', 600.0))

    def qualify(self, heavy: int) -> None:
        """A TEST schema-1 record both clients read: heavy slots plus one audio slot."""
        self.records = qualify_fixture_host(self, {'heavy': heavy, 'audio': 1})

    def acquire(self, project: str, lane: str = 'heavy', fence_reasons: tuple = ()) -> object:
        """Admit a new-client member in this process and always close it."""
        request = pool.PoolRequest(lane, project, fence_reasons=fence_reasons)
        try:
            lease = work.NativeWorkLease.acquire(lane, project, request=request)
        finally:
            request.withdraw()
        self.addCleanup(lease.close)
        return lease

    def release_then_resume(self, lease: object, waiter: object) -> dict:
        """Complete a member after the older client has waited; return the waiter's admission."""
        time.sleep(2)
        released = time.time()
        lease.complete()
        admitted = self.event(waiter)
        self.assertEqual(admitted['event'], 'admitted')
        self.assertGreaterEqual(admitted['at'], released)
        return admitted

    def test_new_exclusive_first_older_clients_wait_then_resume(self) -> None:
        """A Long no profile covers runs alone: older heavy and audio requests queue behind its fence."""
        self.qualify(3)
        long = self.acquire(self.long)
        self.assertEqual((long.admission['mode'], len(long.fence)), ('exclusive', 2))
        for lane in ('heavy', 'audio'):
            probe = self.base('queue', lane, self.short)
            refused = self.event(probe)
            self.assertEqual(refused['event'], 'queued', refused)
            self.assertIn('queued behind', refused['reason'])
            self.stop(probe)
        waiter = self.base('hold', 'heavy', self.short, '1')
        admitted = self.release_then_resume(long, waiter)
        self.assertEqual(admitted['mode'], 'qualified')
        self.assertEqual(sorted(self.root.glob('pool-v1/t-*.json')), [])

    def test_older_member_first_new_exclusive_is_refused_by_name(self) -> None:
        """An older client's live member makes an uncovered request an unsupported mix, not a waiter."""
        self.qualify(3)
        holder = self.base('hold', 'heavy', self.short, '3')
        self.assertEqual(self.event(holder)['mode'], 'qualified')
        with self.assertRaisesRegex(NativeWorkUnsupportedMix, 'no SLA is promised'):
            self.acquire(self.long)
        beside = self.acquire(self.short)  # schema 1 covers the older client's unrecorded owner
        self.assertEqual((beside.admission['mode'], len(beside.fence)), ('qualified', 2))
        self.assertIn(APFS, beside.admission['fence'][0], 'its APFS disk is fenced; joining older members is not')
        beside.complete()
        self.assertEqual(self.event(holder)['event'], 'completed')
        holder.wait(timeout=10)
        long = self.acquire(self.long)
        self.assertEqual(long.admission['mode'], 'exclusive')
        long.complete()

    def test_fenced_member_admits_new_clients_but_not_older_ones(self) -> None:
        """The E2 off-root case: new members join a fenced member; an older one waits for its release."""
        self.qualify(3)
        fenced = self.acquire(self.short, fence_reasons=FENCED)
        self.assertEqual((fenced.admission['mode'], fenced.admission['fence'][0]), ('qualified', FENCED[0]))
        beside = self.acquire(self.short)
        self.assertEqual(beside.admission['mode'], 'qualified')
        beside.complete()  # itself fenced (APFS disk): an older client waits for every fenced member
        waiter = self.base('hold', 'heavy', self.short, '1')
        self.release_then_resume(fenced, waiter)

    def test_older_request_queued_ahead_waits_behind_a_later_fence(self) -> None:
        """Fenced work never waits for older requests: they sort behind its sequence-0 fence and wait for it."""
        self.qualify(2)
        holders = [self.base('admit-disk', self.short, str(project_dir(self, f'held-{index}')), str(3 * GIB),
                             str(500 * GIB), stdin=True) for index in range(2)]
        for holder in holders:  # two older members fill both heavy slots
            self.send(holder)
            self.assertEqual([self.event(holder)['event'] for _ in range(2)], ['transacting', 'admitted'])
        early = self.base('hold', 'heavy', self.short, '1')
        time.sleep(1.5)
        fenced = self.acquire(self.short, lane='audio', fence_reasons=FENCED)  # admitted at once, no wait
        self.assertEqual((len(fenced.fence), fenced.fence[0].sequence), (2, 0))
        late = self.base('queue', 'audio', self.short)
        self.assertIn('queued behind', self.event(late)['reason'])
        self.send(holders[0], 'done')
        self.assertEqual(holders[0].wait(timeout=30), 0)
        time.sleep(2.5)  # a heavy slot is free, but the older request waits behind the fence
        self.assertEqual(len(members(self.root)), 2)
        fenced.complete()
        self.assertEqual(self.event(early)['event'], 'admitted')
        self.send(holders[1], 'done')

    def test_without_the_fence_the_exclusive_charge_still_keeps_the_base_client_out(self) -> None:
        """Negative control of the fence: an unfenced exclusive member still charges the whole memory budget."""
        import native_work_pool_fence as fence
        self.qualify(3)
        with mock.patch.object(fence, 'reasons_for', return_value=[]):
            long = self.acquire(self.long)
        self.assertEqual((long.admission['mode'], long.fence), ('exclusive', []))
        self.assertEqual(long.admission['chargedReservationBytes'], long.admission['aggregateBudgetBytes'])
        probe = self.base('queue', 'heavy', self.short)
        refused = self.event(probe)
        self.assertEqual(refused['event'], 'queued', refused)
        self.assertIn('host memory budget is fully reserved', refused['reason'])
        self.stop(probe)
        long.complete()

    def test_dead_exclusive_supervisor_keeps_older_clients_out(self) -> None:
        """Without a live holder the fence lapses, but the quarantined whole-budget charge refuses older clients."""
        self.qualify(3)
        long = self.acquire(self.long)
        long.close()
        joined = self.base('hold', 'heavy', self.short, '1')
        refused = self.event(joined)
        self.assertEqual((refused['event'], refused['error']), ('refused', 'NativeWorkQuarantined'), refused)
        self.assertIn('quarantined and legacy reservations leave no room', refused['reason'])
        with self.assertRaisesRegex(NativeWorkQuarantined, 'unverified cleanup'):
            self.acquire(self.short)


class FenceTakeTests(unittest.TestCase):
    """fence.take is all or none: a failed publish leaves no fence held or on disk."""

    def test_a_failed_later_ticket_releases_the_ones_already_published(self) -> None:
        """The second class's ticket fails to publish: the first is closed and removed before the error."""
        import native_work_pool_fence as fence
        import native_work_pool_state as state
        from native_work_pool_observe import observe
        root = isolate_pool(self)
        real, published = fence.publish_ticket, []
        def flaky(namespace: object, view: object, fields: dict) -> object:
            """Publish the first ticket; fail the second (TEST)."""
            if published:
                raise OSError('TEST publish failure')
            published.append(real(namespace, view, fields))
            return published[-1]
        with state.ledger(time.monotonic() + 10) as namespace, mock.patch.object(fence, 'publish_ticket', flaky):
            with self.assertRaisesRegex(OSError, 'TEST publish failure'):
                fence.take(namespace, observe(namespace), {'project': '/TEST', 'nonce': 'TEST'}, ['TEST'])
        self.assertEqual((len(published), published[0].fd), (1, -1))
        self.assertEqual(sorted((root / 'pool-v1').glob('t-*.json')), [])

if __name__ == '__main__':
    unittest.main()
