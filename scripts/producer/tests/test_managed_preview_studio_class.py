"""Studio startup in its own pool class (C1): a finished Short's view opens while other Shorts render.

StudioPoolTests drive the real pool in a private namespace, without the Studio manager.
StudioOpenTests drive the real manager, registry and pool through ManagedPreviewFixture (inert TEST
preview identities; no process starts); they need managed_preview_state's registry API (M-025).
Qualified cases use a TEST schema-1 record (three heavy slots, one audio slot) on the TEST host.
The p11_studio_heavy.py sequence is test_finished_short_studio_opens_behind_full_heavy_pool_and_queue.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import json
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import native_work_lease as work
import native_work_pool as pool
import native_work_pool_disk as disk
import native_work_pool_policy as policy
import native_work_pool_recovery as pool_recovery
import native_work_recovery as recovery
from native_render_processes import process_table
from native_render_resources import GIB
from native_work_pool_policy import LEDGER_CLASSES, POOL_CLASSES, STUDIO_CLASS
from native_work_pool_state import NativeWorkQuarantined, NativeWorkQueued
from studio.studio_server import StudioServerError
from _managed_preview_fixture import ManagedPreviewFixture
from _native_pool_fixture import TEST_HOST, isolate_pool, members, plan_project, qualify_fixture_host

SLOTS = {'heavy': 3, 'audio': 1}
DEAD = dict(pid=987654321, pgid=987654321, started='Wed Sep  9 10:00:00 2026')  # a crashed opener (TEST)
POLICY_IDENTITY = {  # policy_identity() before the Studio class existed: committed records stay valid
    'layout': 'native-work-pool-v1', 'aggregateFractionPercent': 50, 'singleJobFractionPercent': 25,
    'singleJobCapBytes': 16 * GIB, 'reservationBytes': {'heavy': 6 * GIB, 'audio': 1 * GIB},
    'diskReservationBytes': {'heavy': 3 * GIB, 'audio': 1 * GIB}, 'diskReserveBytes': 10 * GIB,
    'slotBounds': {'heavy': [2, 5], 'audio': [1, 2]}}


class PoolHelpers:
    """TEST helpers shared by both classes (mixed into a TestCase)."""

    def lease(self, lane: str, project: Path, **fields: object) -> object:
        """Admit one member through the public entry point; closed at cleanup."""
        request = pool.PoolRequest(lane, str(project), **fields)
        self.addCleanup(request.withdraw)
        lease = work.NativeWorkLease.acquire(lane, str(project), request=request)
        self.addCleanup(lease.close)
        return lease

    def queued(self, lane: str, project: Path) -> tuple[pool.PoolRequest, NativeWorkQueued]:
        """A request that waits now, keeping its ticket, and its refusal."""
        request = pool.PoolRequest(lane, str(project), declares_launch=True)
        self.addCleanup(request.withdraw)
        with self.assertRaises(NativeWorkQueued) as caught:
            work.NativeWorkLease.acquire(lane, str(project), request=request)
        return request, caught.exception

    def admit_queued(self, request: pool.PoolRequest) -> None:
        """Admit a queued request on its kept ticket, then complete it."""
        lease = work.NativeWorkLease.acquire(request.lane, request.project, request=request)
        self.addCleanup(lease.close)
        lease.complete()

    def records(self, root: Path) -> list[dict]:
        """Every member record in the private namespace."""
        return [json.loads(path.read_text()) for path in members(root)]

    def recover_as_crashed(self, root: Path, nonce: str) -> dict:
        """Rewrite a quarantined member as a crashed opener's (TEST identity), then recover it by nonce."""
        path = root / 'pool-v1' / f'm-{nonce}.json'
        path.write_text(json.dumps(dict(json.loads(path.read_text()), supervisor=DEAD, supervisorPid=DEAD['pid'])))
        absent = process_table('1 0 1 Wed Sep  9 01:00:00 2026\n')
        with mock.patch.object(pool_recovery, 'process_snapshot', return_value=absent):
            return recovery.recover(nonce)


class StudioPoolTests(PoolHelpers, unittest.TestCase):
    """The pool alone: Studio slots, render occupancy, queue order, credit and policy identity."""

    def setUp(self) -> None:
        """Private namespace, TEST Short and Long projects and a Studio view folder."""
        self.root = isolate_pool(self)
        self.short = plan_project(self, 'short', 45.0)
        self.long = plan_project(self, 'long', 600.0)
        self.view = plan_project(self, 'short', 45.0)

    def test_policy_identity_unchanged(self) -> None:
        """The Studio class is outside every qualified policy: identity and render classes are unchanged."""
        self.assertEqual(policy.policy_identity(), POLICY_IDENTITY)
        self.assertEqual((POOL_CLASSES, LEDGER_CLASSES), (('heavy', 'audio'), ('heavy', 'audio', STUDIO_CLASS)))

    def test_studio_is_admitted_beside_full_heavy_slots_and_a_queued_render(self) -> None:
        """Three live renders and a queued fourth: Studio takes its own slot, the render keeps its place."""
        qualify_fixture_host(self, SLOTS)
        renders = [self.lease('heavy', self.short) for _ in range(3)]
        waiting, _error = self.queued('heavy', self.short)
        studio = self.lease(STUDIO_CLASS, self.view, declares_launch=True)
        self.assertEqual((studio.admission['mode'], studio.admission['class'], studio.reservation_bytes),
                         ('studio', STUDIO_CLASS, policy.STUDIO_RESERVATION_BYTES))
        self.assertEqual((studio.admission['capacity'], studio.admission['occupied']), (policy.STUDIO_SLOTS, 0))
        with self.assertRaisesRegex(NativeWorkQueued, 'all 3 heavy slot') as caught:
            work.NativeWorkLease.acquire('heavy', str(self.short), request=waiting)
        self.assertNotIn('queued behind', str(caught.exception))  # no Studio ticket or member is ahead of it
        renders[0].complete()
        self.admit_queued(waiting)  # the freed render slot goes to the queued render, beside the live Studio
        studio.complete()

    def test_renders_never_count_studio_members_or_tickets_in_qualified_mode(self) -> None:
        """Live Studio members and a waiting Studio ticket leave every render slot free; Studio queues alone."""
        qualify_fixture_host(self, SLOTS)
        for _ in range(policy.STUDIO_SLOTS):
            self.lease(STUDIO_CLASS, self.view, declares_launch=True)
        _request, error = self.queued(STUDIO_CLASS, self.view)
        self.assertIn(f'all {policy.STUDIO_SLOTS} studio slot(s) are occupied', str(error))
        self.assertEqual((error.capacity_only, error.capacity_evidence['waitClass']), (False, 'other'))
        for _ in range(3):  # younger than the waiting Studio ticket, and never behind it
            self.lease('heavy', self.short)
        _request, later = self.queued(STUDIO_CLASS, self.view)
        self.assertIn('queued behind 1 earlier request(s)', str(later))

    def test_an_exclusive_request_waits_the_seconds_a_studio_startup_takes(self) -> None:
        """Without a host record the pool is exclusive: a render needs an idle pool, so it waits for Studio."""
        self.enterContext(mock.patch.object(policy, 'host_identity', return_value=dict(TEST_HOST)))
        studio = self.lease(STUDIO_CLASS, self.view, declares_launch=True)
        waiting, error = self.queued('heavy', self.short)
        self.assertIn('all 1 heavy slot(s) are occupied', str(error))
        studio.complete()
        self.admit_queued(waiting)

    def test_studio_waits_for_no_render_ticket_and_no_live_exclusive_long(self) -> None:
        """A live exclusive Long and a queued Short never hold a Studio startup back."""
        qualify_fixture_host(self, SLOTS)
        long = self.lease('heavy', self.long, root=str(self.long), receipt=str(self.long / 'pipeline.render.json'))
        self.assertEqual(long.admission['mode'], 'exclusive')
        with self.assertRaises(work.NativeWorkBusy):  # the Short cannot run beside the exclusive Long
            self.lease('heavy', self.short)
        self.lease(STUDIO_CLASS, self.view, declares_launch=True).complete()

    def test_a_studio_start_waits_for_the_memory_budget_every_member_shares(self) -> None:
        """Studio is charged against every member: a render reserving 31.5 of 32 GiB makes it wait (M2)."""
        qualify_fixture_host(self, SLOTS)
        render = self.lease('heavy', self.short)
        render._write(dict(render.record, guardReservationBytes=int(31.5 * GIB)))
        waiting, error = self.queued(STUDIO_CLASS, self.view)
        self.assertIn('host memory budget is fully reserved by running members', str(error))
        render.complete()
        self.admit_queued(waiting)

    def test_a_studio_start_waits_for_disk_headroom_every_member_shares(self) -> None:
        """Studio reserves disk in the space every member shares: a render's 3 GiB can make it wait (M2)."""
        space = disk.Filesystem(8, 'filesystem:8', 13 * GIB + 128 * 1024 ** 2)  # room for one render only
        self.enterContext(mock.patch.object(disk, 'filesystem', return_value=space))
        qualify_fixture_host(self, SLOTS)
        render = self.lease('heavy', self.short)
        waiting, error = self.queued(STUDIO_CLASS, self.view)
        self.assertIn('disk headroom is reserved by running members', str(error))
        render.complete()
        self.admit_queued(waiting)

    def test_quarantined_studio_member_is_recoverable_by_nonce(self) -> None:
        """An unverified startup's Studio member declares no launch, so recovery by nonce releases its slot."""
        studio = self.lease(STUDIO_CLASS, self.view, declares_launch=True)
        studio.close()  # attempted and unverified: the member stays quarantined
        record = self.records(self.root)[0]
        self.assertEqual((record['class'], record['phase'], record['processes']), (STUDIO_CLASS, 'admitted', []))
        result = self.recover_as_crashed(self.root, studio.nonce)
        self.assertEqual((result['kind'], result['memberClass']), ('pool-member', STUDIO_CLASS))
        self.assertEqual(members(self.root), [])


class StudioOpenTests(PoolHelpers, ManagedPreviewFixture, unittest.TestCase):
    """The real Studio manager: open_preview takes a Studio slot, never a render slot."""

    def setUp(self) -> None:
        """Manager fixture (private registry and pool namespace) plus a TEST record and TEST projects."""
        super().setUp()
        self.pool_root = self.root / 'registry'
        qualify_fixture_host(self, SLOTS)
        self.short = plan_project(self, 'short', 45.0)
        self.long = plan_project(self, 'long', 600.0)

    def failed_open(self, index: int) -> str:
        """An attempted, unverified startup of one fixture draft; return its quarantined Studio member."""
        before = {row['nonce'] for row in self.records(self.pool_root)}
        self.mocks[3].side_effect = RuntimeError('TEST uncertain startup')
        with self.assertRaisesRegex(RuntimeError, 'uncertain startup'):
            self.open(index)
        self.mocks[3].side_effect = self.launch
        [studio] = [row for row in self.records(self.pool_root) if row['nonce'] not in before]
        self.assertEqual(studio['class'], STUDIO_CLASS)
        return studio['nonce']

    def test_finished_short_studio_opens_behind_full_heavy_pool_and_queue(self) -> None:
        """Three live renders and a queued fourth: the finished Short's Studio view opens now."""
        for _ in range(3):
            self.lease('heavy', self.short)
        self.queued('heavy', self.short)
        record = self.open(0, wait_seconds=0)
        self.assertIn(record.pid, self.identities)
        self.assertEqual(sorted(row['class'] for row in self.records(self.pool_root)), ['heavy'] * 3)

    def test_studio_open_waits_neither_for_a_live_exclusive_long(self) -> None:
        """An exclusive Long runs alone among renders, but the Studio open is admitted at once."""
        long = self.lease('heavy', self.long, root=str(self.long), receipt=str(self.long / 'pipeline.render.json'))
        self.assertEqual(long.admission['mode'], 'exclusive')
        self.assertIn(self.open(0, wait_seconds=0).pid, self.identities)

    def test_unverified_startup_quarantines_one_studio_slot_not_a_render_slot(self) -> None:
        """The unverified startup keeps a Studio member quarantined; every render slot still admits."""
        nonce = self.failed_open(0)
        quarantined = [row for row in self.records(self.pool_root) if row['nonce'] == nonce]
        self.assertEqual([(row['class'], row['phase']) for row in quarantined], [(STUDIO_CLASS, 'admitted')])
        for _ in range(3):
            self.lease('heavy', self.short)
        self.assertIn(self.open(1, wait_seconds=0).pid, self.identities)  # the second Studio slot still opens

    def test_an_open_waits_for_a_studio_slot_until_its_deadline(self) -> None:
        """Both Studio slots busy: the open waits inside its deadline and starts once one frees (RL6)."""
        starts = [self.lease(STUDIO_CLASS, plan_project(self, 'short', 45.0), declares_launch=True)
                  for _ in range(policy.STUDIO_SLOTS)]
        clock = SimpleNamespace(monotonic=time.monotonic, sleep=lambda _seconds: starts.pop().complete())
        with mock.patch.object(pool, 'time', clock):
            self.assertIn(self.open(0, wait_seconds=5).pid, self.identities)
        self.assertEqual(len(starts), policy.STUDIO_SLOTS - 1)  # exactly one wait freed exactly one slot

    def test_failures_before_spawning_release_the_studio_slot(self) -> None:
        """Two consecutive starts that fail before spawning (cleanup verified) quarantine nothing (X97)."""
        def before_spawn(*_args: object, **_options: object) -> None:
            """The launcher failing before any child exists, tagged as studio_server tags it."""
            error = StudioServerError('TEST startup failed before spawning')
            error.preview_spawned = False  # studio_server's tag: no child exists
            raise error
        self.mocks[3].side_effect = before_spawn
        for index in (0, 1):
            with self.assertRaisesRegex(StudioServerError, 'before spawning'):
                self.open(index, wait_seconds=0)
            self.assertEqual(json.loads(self.record(index).read_text())['state'], 'stopped')
        self.assertEqual(self.records(self.pool_root), [])  # both Studio slots are free
        self.mocks[3].side_effect = self.launch
        self.assertIn(self.open(2, wait_seconds=0).pid, self.identities)

    def test_second_quarantined_studio_slot_refuses_by_name(self) -> None:
        """Once both Studio slots are quarantined the next open is refused, naming them and the recovery."""
        nonces = sorted([self.failed_open(0), self.failed_open(1)])
        with self.assertRaises(NativeWorkQuarantined) as caught:
            self.open(2, wait_seconds=0)
        message = str(caught.exception)
        self.assertIn(f"all {policy.STUDIO_SLOTS} studio slot(s) are quarantined: {', '.join(nonces)}", message)
        self.assertIn('recover with native_work_recovery.py <nonce>', message)
        self.lease('heavy', self.short).complete()  # renders are untouched

    def test_quarantined_studio_member_is_recoverable_by_nonce(self) -> None:
        """Recovering the member by nonce frees its Studio slot for the next open."""
        nonces = [self.failed_open(0), self.failed_open(1)]
        result = self.recover_as_crashed(self.pool_root, nonces[0])
        self.assertEqual(result['memberClass'], STUDIO_CLASS)
        self.assertIn(self.open(2, wait_seconds=0).pid, self.identities)


if __name__ == '__main__':
    unittest.main()
