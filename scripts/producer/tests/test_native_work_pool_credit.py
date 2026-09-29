"""Pool wait credit (C5): only waits for occupied, eligible slots are credited.

Every case drives the real pool in a private namespace (_native_pool_fixture.isolate_pool) with a
TEST schema-1 record: three heavy slots and one audio slot on the TEST host (32 GiB budget). One
TEST filesystem with 500 GiB free stands in for every root, so disk headroom is exact and no
compatibility fence is taken. The sequences are p5_pool_classification.py's, but the refusal comes
from real admission, not from stubbed decide() inputs.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import unittest
from unittest import mock

import native_work_lease as work
import native_work_pool as pool
import native_work_pool_disk as disk
from native_render_resources import GIB
from native_work_pool_credit import MAX_OCCUPANTS, ReasonGroups, classify
from native_work_pool_state import NativeWorkQueued
from _native_pool_fixture import hold_legacy_exclusive, isolate_pool, plan_project, qualify_fixture_host

SLOTS = {'heavy': 3, 'audio': 1}
STAGES = {'heavy': 'pipeline', 'audio': 'audio-stage'}
FREE_BYTES = 500 * GIB


class CreditTests(unittest.TestCase):
    """Real admission refusals and the capacity evidence they carry."""

    def setUp(self) -> None:
        """Private namespace, TEST record, one TEST Short project on one TEST filesystem."""
        self.root = isolate_pool(self)
        qualify_fixture_host(self, SLOTS)
        self.project = plan_project(self, 'short', 45.0)
        space = disk.Filesystem(8, 'filesystem:8', FREE_BYTES)
        self.enterContext(mock.patch.object(disk, 'filesystem', return_value=space))

    def request(self, lane: str = 'heavy', disk_bytes: int | None = None) -> pool.PoolRequest:
        """One owner's request (kept across attempts), withdrawn at cleanup."""
        request = pool.PoolRequest(lane, str(self.project), root=str(self.project), disk_bytes=disk_bytes,
                                   receipt=str(self.project / f'{STAGES[lane]}.render.json'), declares_launch=True)
        self.addCleanup(request.withdraw)
        return request

    def admit(self, lane: str = 'heavy') -> object:
        """A live member of this class, closed at cleanup."""
        lease = work.NativeWorkLease.acquire(lane, str(self.project), request=self.request(lane))
        self.addCleanup(lease.close)
        return lease

    def refused(self, request: pool.PoolRequest) -> NativeWorkQueued:
        """The waitable refusal this request gets now; its ticket is kept."""
        with self.assertRaises(NativeWorkQueued) as caught:
            work.NativeWorkLease.acquire(request.lane, request.project, request=request)
        return caught.exception

    def assert_credit(self, error: NativeWorkQueued, credited: bool, wait_class: str) -> None:
        """capacityOnly as the refusal and its evidence both carry it, and the wait class."""
        self.assertIs(error.capacity_only, credited)
        self.assertEqual((error.capacity_evidence['capacityOnly'], error.capacity_evidence['waitClass']),
                         (credited, wait_class))

    @staticmethod
    def inflate(lease: object, reservation: int) -> None:
        """Raise one member's own memory reservation (its guard size) in its durable record."""
        lease._write(dict(lease.record, guardReservationBytes=reservation))

    def test_all_live_slots_occupied_is_credited(self) -> None:
        """Three live members fill the three slots: the fourth request's wait is credited."""
        holders = [self.admit() for _ in range(3)]
        request = self.request()
        error = self.refused(request)
        self.assertIn('all 3 heavy slot(s) are occupied', str(error))
        self.assert_credit(error, True, 'capacity')
        evidence = error.capacity_evidence
        self.assertEqual(evidence['occupants'], sorted(lease.nonce for lease in holders))
        self.assertEqual((evidence['liveOccupied'], evidence['liveFull'], evidence['occupantsTruncated']),
                         (3, True, False))
        self.assertEqual(evidence['ticket'], request.sequence)

    def test_quarantined_slots_are_not_credited(self) -> None:
        """Two slots held by unverified cleanup and one live member: a quarantine wait earns nothing."""
        for lease in (self.admit(), self.admit()):
            lease.close()  # closed without complete(): quarantined, still occupying its slot
        live = self.admit()
        error = self.refused(self.request())
        self.assertIn('all 3 heavy slot(s) are occupied', str(error))
        self.assert_credit(error, False, 'other')
        self.assertEqual((error.capacity_evidence['liveOccupied'], error.capacity_evidence['occupants']),
                         (1, [live.nonce]))

    def test_queue_order_with_free_live_slots_is_not_credited(self) -> None:
        """Behind an older request that waits for disk, a request with two free live slots earns nothing."""
        self.admit()
        older = self.request(disk_bytes=489 * GIB)  # fits the space, but not beside the live member's 3 GiB
        self.assert_credit(self.refused(older), False, 'other')
        error = self.refused(self.request())
        self.assertIn('queued behind 1 earlier request(s)', str(error))
        self.assertNotIn('slot(s) are occupied', str(error))
        self.assert_credit(error, False, 'other')
        self.assertEqual(error.capacity_evidence['liveOccupied'], 1)

    def test_queue_order_behind_full_live_slots_is_credited(self) -> None:
        """Three live members and two waiters: 'queued behind 1' is the same occupied-slot wait."""
        for _ in range(3):
            self.admit()
        self.assert_credit(self.refused(self.request()), True, 'capacity')
        error = self.refused(self.request())
        self.assertIn('queued behind 1 earlier request(s)', str(error))
        self.assert_credit(error, True, 'capacity')

    def test_memory_refusal_with_free_live_slots_is_not_credited(self) -> None:
        """One live member reserving 30 GiB of the 32 GiB budget: a memory wait with free slots earns nothing."""
        self.inflate(self.admit(), 30 * GIB)
        error = self.refused(self.request())
        self.assertIn('host memory budget is fully reserved by running members', str(error))
        self.assertNotIn('slot(s) are occupied', str(error))
        self.assert_credit(error, False, 'other')

    def test_memory_refusal_with_full_live_slots_is_credited(self) -> None:
        """With every live slot occupied, the memory reason is the same wait and is credited."""
        holders = [self.admit() for _ in range(3)]
        self.inflate(holders[0], 20 * GIB)
        error = self.refused(self.request())
        self.assertIn('host memory budget is fully reserved by running members', str(error))
        self.assertIn('all 3 heavy slot(s) are occupied', str(error))
        self.assert_credit(error, True, 'capacity')

    def test_legacy_exclusive_work_is_credited(self) -> None:
        """Old-code exclusive work holding heavy.lock is live work on the capacity: credited."""
        hold_legacy_exclusive(self, self.root)
        error = self.refused(self.request())
        self.assertIn('legacy exclusive heavy work is running', str(error))
        self.assert_credit(error, True, 'capacity')

    def test_own_disk_refusal_and_audio_lane_are_never_credited(self) -> None:
        """Controls: a disk reason beside full live slots, and an audio wait, never earn credit."""
        for _ in range(3):
            self.admit()
        error = self.refused(self.request(disk_bytes=485 * GIB))
        self.assertIn('disk headroom is reserved by running members', str(error))
        self.assertIn('all 3 heavy slot(s) are occupied', str(error))
        self.assert_credit(error, False, 'other')
        self.admit('audio')
        error = self.refused(self.request('audio'))
        self.assertIn('all 1 audio slot(s) are occupied', str(error))
        self.assert_credit(error, False, 'other')


class ClassifyTests(unittest.TestCase):
    """The pure rule on hand-built decisions: bounds and the groups that never earn credit."""

    @staticmethod
    def decision(reasons: list[str], lane: str = 'heavy', capacity: int = 1) -> pool.Decision:
        """A TEST decision holding only what classify reads."""
        return pool.Decision(None, 0, 0, 0, reasons=list(reasons), context={'capacity': capacity}, lane=lane)

    @staticmethod
    def row(nonce: str, quarantined: bool = False) -> dict:
        """One charged member row."""
        return {'nonce': nonce, 'quarantined': quarantined}

    def test_occupants_are_bounded_sorted_and_include_mix_blockers(self) -> None:
        """At most MAX_OCCUPANTS sorted nonces (live occupancy plus blockers); truncation is recorded."""
        decision = self.decision(['TEST wait'], capacity=10)
        rows = [self.row(f'n{index:02d}') for index in range(9, 0, -1)] + [self.row('q', True)]
        classify(decision, rows, ReasonGroups(mix=('TEST mix wait',), blockers=('b0',)))
        context = decision.context
        expected = sorted(['b0', *(f'n{index:02d}' for index in range(1, 10))])[:MAX_OCCUPANTS]
        self.assertEqual(context['occupants'], expected)
        self.assertEqual((context['liveOccupied'], context['liveFull'], context['occupantsTruncated']),
                         (9, False, True))
        self.assertEqual((context['capacityOnly'], context['waitClass']), (True, 'capacity'))

    def test_an_uncredited_group_or_refusal_withholds_credit(self) -> None:
        """A disk or session reason, a terminal or unsupported refusal, or a non-heavy class: never credited."""
        full = [self.row('live')]
        cases = [(self.decision(['TEST slot', 'TEST disk']), ReasonGroups(slot=('TEST slot',), other=('TEST disk',))),
                 (self.decision(['TEST slot'], lane='audio'), ReasonGroups(slot=('TEST slot',))),
                 (self.decision(['TEST slot'], lane='studio'), ReasonGroups(slot=('TEST slot',)))]
        terminal = self.decision(['TEST slot'])
        terminal.terminal.append('TEST quarantined')
        cases.append((terminal, ReasonGroups(slot=('TEST slot',))))
        for decision, groups in cases:
            classify(decision, full, groups)
            with self.subTest(lane=decision.lane, groups=groups):
                self.assertEqual((decision.context['capacityOnly'], decision.context['waitClass']), (False, 'other'))
        admitted = self.decision([])
        classify(admitted, full, ReasonGroups())
        self.assertEqual((admitted.context['capacityOnly'], admitted.context['waitClass']), (False, None))


if __name__ == '__main__':
    unittest.main()
