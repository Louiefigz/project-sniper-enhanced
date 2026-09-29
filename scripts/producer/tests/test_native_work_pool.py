"""Host pool admission, FIFO queue, reservations and quarantine on real locks and files.

Every test runs in a private temporary namespace (never the host's canonical pool) and
uses TEST fixture host identities/records where a qualified pool is needed.
"""
from __future__ import annotations

import json
import os
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import native_work_lease as work
import native_work_pool as pool
import native_work_pool_disk as disk
import native_work_pool_expand as expand
import native_work_pool_policy as policy
from native_render_resources import GIB, ResourcePolicy
from native_work_pool_state import NativeWorkQuarantined, NativeWorkQueued
from _native_pool_fixture import isolate_pool, members, project_dir, qualify_fixture_host


class ExclusivePoolTests(unittest.TestCase):
    """Without a host record the pool keeps the previous one-job behaviour."""

    def setUp(self) -> None:
        """Isolate the namespace; no record is ever read for a non-canonical root."""
        self.root = isolate_pool(self)
        self.project = str(project_dir(self))

    def acquire(self, lane: str = 'heavy', request: pool.PoolRequest | None = None) -> object:
        """Admit through the public legacy-compatible entry point and always close."""
        lease = work.NativeWorkLease.acquire(lane, self.project, request=request)
        self.addCleanup(lease.close)
        return lease

    def test_one_member_across_classes_with_today_reservation(self) -> None:
        """Heavy and audio share one slot; the reservation equals min(16 GiB, 25% RAM)."""
        lease = self.acquire('heavy')
        physical = policy.host_identity()['memsizeBytes']
        self.assertEqual(lease.reservation_bytes, policy.single_job_bytes(physical))
        self.assertEqual(lease.admission['mode'], 'exclusive')
        for lane in ('heavy', 'audio'):
            with self.assertRaisesRegex(NativeWorkQueued, 'already active'):
                work.NativeWorkLease.acquire(lane, self.project)
        lease.complete()
        self.acquire('audio').complete()

    def test_unverified_close_quarantines_slot_and_is_not_waitable(self) -> None:
        """Closing without verified cleanup keeps the slot and its reservation charged."""
        lease = self.acquire()
        lease.close()
        with self.assertRaisesRegex(NativeWorkQuarantined, 'cleanup is unverified') as caught:
            work.NativeWorkLease.acquire('heavy', self.project)
        self.assertNotIn('already active', str(caught.exception))
        self.assertIn(lease.nonce, str(caught.exception))
        self.assertEqual([path.name for path in members(self.root)], [f'm-{lease.nonce}.json'])

    def test_live_recorded_child_blocks_completion(self) -> None:
        """complete() keeps the record while any recorded identity is live."""
        lease = self.acquire()
        row = dict(pid=23456, pgid=23456, started='Wed Sep  9 11:00:00 2026')
        lease.record_processes([row])
        with mock.patch.object(work, '_live_identities', return_value=[23456]):
            with self.assertRaisesRegex(RuntimeError, 'live recorded'):
                lease.complete()
        self.assertEqual(len(members(self.root)), 1)
        with mock.patch.object(work, '_live_identities', return_value=[]):
            lease.complete()
        self.assertEqual(members(self.root), [])

    def test_process_union_and_launch_phase_are_durable(self) -> None:
        """Identities accumulate; declared owners move admitted -> launching before spawn."""
        request = pool.PoolRequest('heavy', self.project, declares_launch=True)
        lease = self.acquire(request=request)
        self.assertEqual(lease.record['phase'], 'admitted')
        lease.mark_launching()
        one = dict(pid=23456, pgid=23456, started='Wed Sep  9 11:00:00 2026')
        two = dict(pid=23457, pgid=23457, started='Wed Sep  9 11:00:01 2026')
        lease.record_processes([one])
        lease.record_processes([two])
        stored = json.loads(members(self.root)[0].read_text())
        self.assertEqual((stored['phase'], stored['processes']), ('launching', [one, two]))
        with mock.patch.object(work, '_live_identities', return_value=[]):
            lease.complete()

    def test_compat_acquire_records_unknown_launch_state(self) -> None:
        """Callers that never declare launches cannot later claim nothing was launched."""
        lease = self.acquire()
        self.assertEqual(lease.record['phase'], 'launch-state-unknown')
        lease.mark_launching()
        self.assertEqual(lease.record['phase'], 'launch-state-unknown')
        lease.complete()

    def test_changed_record_refuses_release(self) -> None:
        """Ownership drift cannot delete another member's obligation."""
        lease = self.acquire()
        path = members(self.root)[0]
        path.write_text(json.dumps(dict(lease.record, reservationBytes=1)))
        with self.assertRaisesRegex(RuntimeError, 'record changed'):
            lease.complete()
        self.assertTrue(path.exists())

    def test_fifo_head_is_admitted_before_a_later_request(self) -> None:
        """A later ticket waits even when capacity frees while an earlier one waits."""
        holder = self.acquire()
        first = pool.PoolRequest('heavy', self.project)
        second = pool.PoolRequest('audio', self.project)
        self.addCleanup(first.withdraw)
        self.addCleanup(second.withdraw)
        for request in (first, second):
            with self.assertRaises(NativeWorkQueued):
                work.NativeWorkLease.acquire(request.lane, self.project, request=request)
        holder.complete()
        with self.assertRaisesRegex(NativeWorkQueued, 'queued behind 1 earlier'):
            work.NativeWorkLease.acquire('audio', self.project, request=second)
        admitted = self.acquire('heavy', request=first)
        self.assertEqual(admitted.admission['ticket'], first.sequence)
        admitted.complete()
        self.acquire('audio', request=second).complete()

    def test_withdrawn_ticket_is_pruned_with_identity_evidence(self) -> None:
        """A released ticket no longer blocks later requests."""
        holder = self.acquire()
        first = pool.PoolRequest('heavy', self.project)
        with self.assertRaises(NativeWorkQueued):
            work.NativeWorkLease.acquire('heavy', self.project, request=first)
        first.withdraw()
        holder.complete()
        self.acquire().complete()
        self.assertEqual(sorted(self.root.glob('pool-v1/t-*.json')), [])

    def test_request_must_match_class_and_project(self) -> None:
        """A retry cannot reuse another request's queue position."""
        request = pool.PoolRequest('audio', self.project)
        with self.assertRaisesRegex(ValueError, 'does not match'):
            work.NativeWorkLease.acquire('heavy', self.project, request=request)
        with self.assertRaisesRegex(ValueError, 'Unknown native pool class'):
            pool.PoolRequest('preview-control', self.project)


class QualifiedPoolTests(unittest.TestCase):
    """A TEST record for a TEST host enables pooled slots and per-class reservations."""

    def setUp(self) -> None:
        """Three heavy slots and one audio slot on a 64 GiB fixture host."""
        self.root = isolate_pool(self)
        qualify_fixture_host(self, {'heavy': 3, 'audio': 1})
        self.project = str(project_dir(self))

    def acquire(self, lane: str = 'heavy', fixed: float | None = None) -> object:
        """Admit with an optional explicit fixed owned-tree policy."""
        request = pool.PoolRequest(lane, self.project, fixed_owned_gib=fixed)
        try:
            lease = work.NativeWorkLease.acquire(lane, self.project, request=request)
        finally:
            request.withdraw()
        self.addCleanup(lease.close)
        return lease

    def test_slots_and_reservations_follow_the_record(self) -> None:
        """Three heavy members and one audio member run together; a fourth heavy waits."""
        heavy = [self.acquire() for _ in range(3)]
        audio = self.acquire('audio')
        self.assertEqual({lease.admission['mode'] for lease in heavy + [audio]}, {'qualified'})
        self.assertEqual([lease.reservation_bytes for lease in heavy], [6 * GIB] * 3)
        self.assertEqual(audio.reservation_bytes, GIB)
        self.assertEqual(audio.admission['chargedBytes'], 18 * GIB)
        with self.assertRaisesRegex(NativeWorkQueued, 'all 3 heavy slot'):
            work.NativeWorkLease.acquire('heavy', self.project)
        for lease in heavy + [audio]:
            lease.complete()

    def test_quarantine_keeps_its_slot_and_charge_others_continue(self) -> None:
        """One quarantined member leaves the remaining slots usable while budget fits."""
        lost = self.acquire()
        lost.close()
        others = [self.acquire(), self.acquire()]
        self.assertEqual(others[1].admission['quarantinedChargedBytes'], 6 * GIB)
        with self.assertRaisesRegex(NativeWorkQueued, 'all 3 heavy slot'):
            work.NativeWorkLease.acquire('heavy', self.project)
        for lease in others:
            lease.complete()

    def test_five_sixteen_gib_allowances_cannot_be_admitted(self) -> None:
        """Fixed 16 GiB owners are summed against the 32 GiB aggregate budget."""
        big = [self.acquire(fixed=16), self.acquire(fixed=16)]
        with self.assertRaisesRegex(NativeWorkQueued, 'memory budget'):
            self.acquire(fixed=16)
        big[0].close()
        big[1].close()
        with self.assertRaisesRegex(NativeWorkQuarantined, 'no room in the host memory budget'):
            self.acquire(fixed=16)

    def test_guard_policy_is_bound_by_the_reservation(self) -> None:
        """The owner's stop limit never exceeds the bytes it reserved."""
        bounded = policy.reserved_policy(ResourcePolicy(), 6 * GIB)
        self.assertEqual((bounded.maximum_owned_gib, bounded.maximum_process_gib), (6, 4.5))
        unchanged = ResourcePolicy(maximum_owned_gib=4, maximum_process_gib=3)
        self.assertIs(policy.reserved_policy(unchanged, 6 * GIB), unchanged)
        with self.assertRaises(policy.PoolPolicyError):
            policy.reserved_policy(ResourcePolicy(), 0)

    def test_disk_reservations_are_shared_by_the_filesystem(self) -> None:
        """Reserved bytes of running members cannot be spent twice; true shortage is terminal."""
        free = 10 * GIB + 7 * GIB
        with mock.patch.object(disk, 'filesystem', side_effect=lambda path: disk.Filesystem(1, 'TEST-volume', free)):
            first, second = self.acquire(), self.acquire()
            with self.assertRaisesRegex(NativeWorkQueued, 'disk headroom is reserved'):
                self.acquire()
            first.close()
            second.close()
            with self.assertRaisesRegex(NativeWorkQuarantined, 'disk headroom'):
                self.acquire()

    def test_infeasible_or_mismatched_record_means_exclusive(self) -> None:
        """A record for other hardware or policy, or one that overcommits, is not used."""
        import native_work_qualification as qualification
        from _native_pool_fixture import TEST_HOST, fixture_record
        cases = [('host', dict(TEST_HOST, memsizeBytes=32 * GIB)), ('policy', {'layout': 'TEST'}),
                 ('configuration', {'heavySlots': 5, 'audioSlots': 2})]
        for key, value in cases:
            record = dict(fixture_record({'heavy': 3, 'audio': 1}), **{key: value})
            with self.subTest(key=key), self.assertRaises(qualification.PoolRecordError):
                qualification.validate_record(record, TEST_HOST)
        record = fixture_record({'heavy': 3, 'audio': 1})
        record['evidence'] = dict(record['evidence'], peakConcurrentJobs=2)
        with self.assertRaisesRegex(qualification.PoolRecordError, 'did not exercise'):
            qualification.validate_record(record, TEST_HOST)
        with mock.patch.object(policy, 'host_identity', return_value=dict(TEST_HOST, osBuild='TEST1')):
            lease = self.acquire()
        self.assertEqual(lease.admission['mode'], 'exclusive')
        lease.complete()


class DiskExpansionTests(unittest.TestCase):
    """A running member grows its disk reservation against every other member in the same space."""

    def setUp(self) -> None:
        """Three heavy slots; an attempt and a cache directory on TEST volumes with fixed free bytes."""
        self.root = isolate_pool(self)
        qualify_fixture_host(self, {'heavy': 3, 'audio': 1})
        self.project = str(project_dir(self))
        self.attempt, self.cache = str(project_dir(self, 'attempt')), str(project_dir(self, 'cache'))
        self.volume(self.attempt, 8, 45)
        self.volume(self.cache, 8, 45)
        self.enterContext(mock.patch.object(disk, 'filesystem', side_effect=self.filesystem))

    def volume(self, directory: str, device: int, free_gib: int, space: str | None = None) -> None:
        """Place a TEST directory on a TEST device whose space defaults to the device alone."""
        self.volumes = {**getattr(self, 'volumes', {}),
                        directory: disk.Filesystem(device, space or f'TEST-volume-{device}', free_gib * GIB)}

    def filesystem(self, path: str) -> disk.Filesystem:
        """TEST volume table by directory (never the real disk)."""
        for directory, volume in self.volumes.items():
            if path == directory or path.startswith(directory + os.sep):
                return volume
        raise AssertionError(f'TEST volume missing for {path}')

    def acquire(self, disk_bytes: int | None = None, root: str | None = None) -> object:
        """Admit one declared heavy member rooted at the TEST attempt directory (or `root`)."""
        request = pool.PoolRequest('heavy', self.project, root=root or self.attempt, disk_bytes=disk_bytes,
                                   declares_launch=True)
        try:
            lease = work.NativeWorkLease.acquire('heavy', self.project, request=request)
        finally:
            request.withdraw()
        self.addCleanup(lease.close)
        return lease

    def stored(self, lease: object) -> dict:
        """The member record exactly as other transactions read it."""
        return json.loads((self.root / 'pool-v1' / lease.marker).read_text())

    def test_two_long_extractions_on_one_volume_cannot_spend_the_same_bytes(self) -> None:
        """Each Long alone fits the old worker-local check; the second expansion is refused."""
        self.volume(self.attempt, 8, 48)
        self.volume(self.cache, 8, 48)
        first, second = self.acquire(), self.acquire()
        self.assertEqual((self.stored(first)['diskSpace'], self.stored(first)['diskAccounting']),
                         ('TEST-volume-8', disk.ACCOUNTING))
        plan = {self.cache: 25 * GIB, self.attempt: 5 * GIB}  # 3 + 30 GiB + 10 GiB reserve <= 48 - 3
        grant = expand.expand_disk(first, plan)
        self.assertEqual(grant['filesystems'][0]['reservationBytes'], 33 * GIB)
        self.assertEqual(self.stored(first)['diskReservations'],
                         [{'device': 8, 'space': 'TEST-volume-8', 'bytes': 33 * GIB}])
        self.assertEqual(self.stored(first)['diskReservationBytes'], 33 * GIB)
        with self.assertRaisesRegex(NativeWorkQueued, 'Disk expansion refused: disk headroom is reserved') as caught:
            expand.expand_disk(second, plan)
        self.assertNotIn('already active', str(caught.exception))
        self.assertNotIn('diskReservations', self.stored(second))
        with self.assertRaisesRegex(NativeWorkQueued, 'disk headroom is reserved by running members'):
            self.acquire()  # 48 - (33 + 3) < 3 + 10: admission sees the grown reservation
        first.complete()
        self.assertEqual(expand.expand_disk(second, plan)['filesystems'][0]['reservedByOthersBytes'], 0)
        second.complete()

    def test_cache_and_output_volumes_are_charged_separately(self) -> None:
        """Source frames charge the cache volume only; a Short on the output volume sees its share."""
        self.volume(self.cache, 7, 55)
        long = self.acquire()
        expand.expand_disk(long, {self.cache: 40 * GIB, self.attempt: 5 * GIB})
        record = self.stored(long)
        self.assertEqual(record['diskReservations'], [{'device': 7, 'space': 'TEST-volume-7', 'bytes': 40 * GIB},
                                                      {'device': 8, 'space': 'TEST-volume-8', 'bytes': 8 * GIB}])
        self.assertEqual((record['diskDevice'], record['diskReservationBytes']), (8, 8 * GIB))
        short = self.acquire()
        self.assertEqual(short.admission['diskReservedByOthersBytes'], 8 * GIB)
        other = self.acquire()
        with self.assertRaisesRegex(NativeWorkQueued, 'TEST-volume-7:') as caught:
            expand.expand_disk(other, {self.cache: 40 * GIB, self.attempt: 5 * GIB})
        self.assertNotIn('TEST-volume-8:', str(caught.exception))
        grown = expand.expand_disk(other, {self.attempt: 20 * GIB})['filesystems'][0]
        self.assertEqual((grown['space'], grown['reservationBytes']), ('TEST-volume-8', 23 * GIB))
        for lease in (long, short, other):
            lease.complete()

    def test_volumes_sharing_one_apfs_container_share_their_free_bytes(self) -> None:
        """Two devices of one container are one space: a cache there spends the attempt's free bytes."""
        self.volume(self.cache, 7, 45, 'apfs-container:TEST')
        self.volume(self.attempt, 8, 45, 'apfs-container:TEST')
        long = self.acquire()
        grant = expand.expand_disk(long, {self.cache: 25 * GIB, self.attempt: 5 * GIB})
        self.assertEqual([(row['space'], row['reservationBytes']) for row in grant['filesystems']],
                         [('apfs-container:TEST', 33 * GIB)])
        # Keyed by device, device 7 would show only 25 GiB reserved (45 - 25 >= 6 + 10); the container shows 33.
        with self.assertRaisesRegex(NativeWorkQueued, 'disk headroom is reserved by running members'):
            self.acquire(disk_bytes=6 * GIB, root=self.cache)
        self.acquire(disk_bytes=2 * GIB, root=self.cache).complete()
        long.complete()

    def test_admission_committed_first_refuses_a_later_expansion(self) -> None:
        """Order decides: bytes a newer member already reserved are not available to grow into."""
        self.volume(self.attempt, 8, 44)
        self.volume(self.cache, 8, 44)
        long = self.acquire()
        other = self.acquire(disk_bytes=5 * GIB)
        with self.assertRaisesRegex(NativeWorkQueued, 'reserved by running members'):
            expand.expand_disk(long, {self.attempt: 30 * GIB})
        other.complete()
        expand.expand_disk(long, {self.attempt: 30 * GIB})
        long.complete()

    def test_policy_expansion_is_not_queued_behind_or_ahead_of_tickets(self) -> None:
        """Tickets hold no bytes: a grant lands while a Short waits; a refused grant holds nothing back."""
        self.volume(self.attempt, 8, 50)
        self.volume(self.cache, 8, 50)
        long, others = self.acquire(), [self.acquire(), self.acquire()]
        waiting = pool.PoolRequest('heavy', self.project, root=self.attempt, disk_bytes=5 * GIB)
        self.addCleanup(waiting.withdraw)
        with self.assertRaisesRegex(NativeWorkQueued, 'all 3 heavy slot'):
            work.NativeWorkLease.acquire('heavy', self.project, request=waiting)
        expand.expand_disk(long, {self.cache: 30 * GIB})  # 50 - 6 >= 33 + 10 while the ticket waits
        others[0].complete()
        with self.assertRaisesRegex(NativeWorkQueued, 'disk headroom is reserved by running members'):
            work.NativeWorkLease.acquire('heavy', self.project, request=waiting)  # 50 - 36 < 5 + 10
        with self.assertRaisesRegex(NativeWorkQueued, 'reserved by running members'):
            expand.expand_disk(others[1], {self.cache: 20 * GIB})
        waiting.withdraw()
        self.acquire(disk_bytes=GIB).complete()  # nothing is held back for the refused expansion
        for lease in (long, others[1]):
            lease.complete()

    def test_expansion_adds_to_the_admitted_bytes_and_keeps_owner_protocol(self) -> None:
        """Requested bytes add to the admission reservation; records, identities and archive stay exact."""
        lease = self.acquire()
        grant = expand.expand_disk(lease, {self.attempt: GIB})
        self.assertEqual((grant['filesystems'][0]['reservationBytes'], lease.disk_reservation_bytes),
                         (4 * GIB, 4 * GIB))
        lease.mark_launching()
        lease.record_processes([dict(pid=23456, pgid=23456, started='Wed Sep  9 11:00:00 2026')])
        with self.assertRaisesRegex(RuntimeError, 'only the disk reservation'):
            lease.adopt_disk(dict(lease.record, reservationBytes=1))
        with mock.patch.object(work, '_live_identities', return_value=[]):
            lease.complete()
        archived = json.loads((self.root / 'pool-v1' / 'last-heavy.json').read_text())
        self.assertEqual(archived['diskReservations'], [{'device': 8, 'space': 'TEST-volume-8', 'bytes': 4 * GIB}])
        with self.assertRaisesRegex(RuntimeError, 'no longer active'):
            expand.expand_disk(lease, {self.attempt: GIB})

    def test_off_root_requests_pass_the_named_fence_hook(self) -> None:
        """The incompatible-client fence (unit E3) gates exactly the requests that leave the root device."""
        self.volume(self.cache, 7, 55)
        lease = self.acquire()
        with mock.patch.object(expand, 'off_root_fence') as fence:
            expand.expand_disk(lease, {self.attempt: GIB})
            expand.expand_disk(lease, {self.cache: GIB})
        self.assertEqual([call.args[2:] for call in fence.call_args_list], [(lease, False), (lease, True)])
        with mock.patch.object(expand, 'off_root_fence', side_effect=NativeWorkQueued('TEST fence refusal')):
            with self.assertRaisesRegex(NativeWorkQueued, 'TEST fence'):
                expand.expand_disk(lease, {self.cache: GIB})
        self.assertEqual(self.stored(lease)['diskReservations'][0], {'device': 7, 'space': 'TEST-volume-7',
                                                                     'bytes': GIB})
        lease.complete()

    def test_directory_renamed_or_removed_before_the_transaction_is_refused_by_name(self) -> None:
        """Opened before the lock, re-checked inside it: a replaced or removed path is refused, nothing grows."""
        lease = self.acquire()
        original = expand.observe
        def replace(namespace: object) -> object:
            """Rename the requested directory away and recreate it while the ledger is held."""
            os.rename(self.cache, self.cache + '-TEST-away')
            os.mkdir(self.cache)
            return original(namespace)
        def remove(namespace: object) -> object:
            """Remove the requested directory while the ledger is held."""
            os.rmdir(self.cache)
            return original(namespace)
        for change, message in ((replace, 'was renamed or replaced'), (remove, 'was removed')):
            with self.subTest(change=change.__name__), mock.patch.object(expand, 'observe', side_effect=change):
                with self.assertRaisesRegex(ValueError, f'{self.cache} {message} before the transaction'):
                    expand.expand_disk(lease, {self.cache: GIB})
        self.assertNotIn('diskReservations', self.stored(lease))
        lease.complete()

    def test_quarantined_expansion_stays_charged_on_its_filesystem(self) -> None:
        """A lost supervisor's grown cache reservation blocks the cache volume only, until recovery."""
        self.volume(self.cache, 7, 55)
        lost = self.acquire()
        expand.expand_disk(lost, {self.cache: 40 * GIB})
        lost.close()
        other = self.acquire()
        self.assertEqual(other.admission['diskReservedByOthersBytes'], 3 * GIB)
        with self.assertRaisesRegex(NativeWorkQuarantined, 'quarantined reservations'):
            expand.expand_disk(other, {self.cache: 10 * GIB})
        other.complete()

    def test_unreadable_member_refuses_disk_on_every_volume(self) -> None:
        """A damaged record cannot silently release bytes: nothing is admitted or grown until recovery."""
        self.volume(self.cache, 7, 500)
        running = self.acquire()
        lost = self.acquire()
        lost.close()
        path = self.root / 'pool-v1' / lost.marker
        extra = [{'device': 8, 'space': 'TEST-volume-8', 'bytes': 3 * GIB, 'TEST-extra': 1}]
        path.write_text(json.dumps(dict(json.loads(path.read_text()), diskReservations=extra)))
        self.assertIsNone(disk.record_spaces(json.loads(path.read_text())))
        for root in (self.attempt, self.cache):
            with self.subTest(root=root), self.assertRaisesRegex(NativeWorkQuarantined, 'unknown disk reservations'):
                self.acquire(disk_bytes=0, root=root)
        with self.assertRaisesRegex(NativeWorkQuarantined, 'unknown disk reservations'):
            expand.expand_disk(running, {self.cache: GIB})
        bogus = dict(json.loads(path.read_text()), diskReservations=None, **{'class': 'TEST-bogus'})
        path.write_text(json.dumps(bogus))
        with self.assertRaisesRegex(NativeWorkQuarantined, 'unknown disk reservations'):
            self.acquire(disk_bytes=0)
        running.complete()

    def test_record_versions_mix_without_unknowns(self) -> None:
        """Base-engine, first-E2 {device, bytes} and current {device, space, bytes} records all charge."""
        self.volume(self.cache, 7, 500)
        self.volume(self.attempt, 8, 500)
        current, first, base = self.acquire(), self.acquire(), self.acquire()
        for lease in (first, base):
            lease.close()
        stamp = {key: value for key, value in self.stored(first).items() if key not in ('diskSpace', 'diskAccounting')}
        first_e2 = dict(stamp, diskReservationBytes=5 * GIB,
                        diskReservations=[{'device': 7, 'bytes': 40 * GIB}, {'device': 8, 'bytes': 5 * GIB}])
        (self.root / 'pool-v1' / first.marker).write_text(json.dumps(first_e2))
        base_record = {key: value for key, value in self.stored(base).items()
                       if key not in ('diskSpace', 'diskAccounting')}
        (self.root / 'pool-v1' / base.marker).write_text(json.dumps(base_record))
        self.assertEqual(disk.record_spaces(first_e2), {'*': 40 * GIB, 'TEST-volume-8': 5 * GIB})
        self.assertEqual(disk.record_spaces(base_record), {'TEST-volume-8': 3 * GIB})
        self.assertIsNone(disk.record_spaces(dict(first_e2, diskReservations=[
            {'device': 7, 'space': 'TEST-volume-7', 'bytes': 40 * GIB}])), 'current rows need their marker')
        current.complete()  # two quarantined records keep two of the three slots
        cache_side = self.acquire(disk_bytes=0, root=self.cache)
        self.assertEqual(cache_side.admission['diskReservedByOthersBytes'], 40 * GIB)  # unknown-space row
        cache_side.complete()
        attempt_side = self.acquire(disk_bytes=0)
        self.assertEqual(attempt_side.admission['diskReservedByOthersBytes'], (40 + 5 + 3) * GIB)
        attempt_side.complete()

    def test_earlier_engine_record_is_charged_by_its_root_space(self) -> None:
        """Without diskSpace a record uses its root's space; a root off its device is charged everywhere."""
        self.volume(self.cache, 7, 45)
        old = self.acquire()
        old.close()
        path = self.root / 'pool-v1' / old.marker
        record = {key: value for key, value in json.loads(path.read_text()).items()
                  if key not in ('diskSpace', 'diskAccounting')}
        path.write_text(json.dumps(record))
        self.assertEqual(disk.record_spaces(record), {'TEST-volume-8': 3 * GIB})
        self.assertEqual(self.acquire(disk_bytes=0, root=self.cache).admission['diskReservedByOthersBytes'], 0)
        path.write_text(json.dumps(dict(record, diskDevice=99)))
        self.assertEqual(self.acquire(disk_bytes=0, root=self.cache).admission['diskReservedByOthersBytes'], 3 * GIB)

    def test_expansion_requests_are_validated_before_any_write(self) -> None:
        """Relative, missing or negative requests change nothing."""
        lease = self.acquire()
        for directories in ({'relative': GIB}, {self.attempt + '/missing': GIB}, {self.attempt: -1}, {}):
            with self.subTest(directories=directories), self.assertRaises(ValueError):
                expand.expand_disk(lease, directories)
        self.assertNotIn('diskReservations', self.stored(lease))
        lease.complete()


class FilesystemSpaceTests(unittest.TestCase):
    """The real space key: APFS volumes name their container, other filesystems themselves."""

    def test_real_system_volumes_of_one_container_are_one_space(self) -> None:
        """VM, Preboot and Data each report the container's free bytes; together they cannot exceed it."""
        isolate_pool(self)
        volumes = [path for path in ('/System/Volumes/VM', '/System/Volumes/Preboot') if Path(path).is_dir()]
        data = project_dir(self)
        found = [disk.filesystem(path) for path in (*volumes, str(data))]
        self.assertGreaterEqual(len(found), 2, 'this macOS host must expose APFS system volumes')
        self.assertEqual(len({row.space for row in found}), 1, found)
        self.assertGreater(len({row.device for row in found}), 1, found)
        share = (min(row.free for row in found) - 10 * GIB) * 2 // 5  # each alone fits; three do not
        lease = work.NativeWorkLease.acquire('heavy', str(data), request=pool.PoolRequest(
            'heavy', str(data), root=str(data), disk_bytes=0))
        self.addCleanup(lease.close)
        with self.assertRaisesRegex(NativeWorkQuarantined, 'apfs-container:disk[0-9]+: .* cannot|cannot hold'):
            expand.expand_disk(lease, {path: share for path in (*volumes, str(data))})  # keyed by device: granted
        self.assertEqual(expand.expand_disk(lease, {volumes[0]: share})['filesystems'][0]['space'], found[0].space)
        lease.complete()

    def test_apfs_space_is_the_container_diskutil_reports(self) -> None:
        """Every mounted APFS volume on this host maps to diskutil's APFSContainerReference."""
        mounts = subprocess.run(['/sbin/mount'], capture_output=True, text=True, check=True, timeout=10).stdout
        checked = 0
        for line in mounts.splitlines():
            source, _on, rest = line.partition(' on ')
            point, _open, options = rest.rpartition(' (')
            if not options.startswith('apfs,') or not source.startswith('/dev/disk'):
                continue
            info = plistlib.loads(subprocess.run(['/usr/sbin/diskutil', 'info', '-plist', point],
                                                 capture_output=True, check=True, timeout=30).stdout)
            with self.subTest(point=point):
                self.assertEqual(disk.filesystem(point).space, f"apfs-container:{info['APFSContainerReference']}")
            checked += 1
        self.assertGreater(checked, 0, 'no mounted APFS volume on this macOS host')
        self.assertEqual(disk.filesystem(tempfile.gettempdir()).space[:15], 'apfs-container:')

    def test_filesystems_that_cannot_be_charged_are_refused(self) -> None:
        """devfs is outside the accounted types; admission names the refusal instead of guessing a space."""
        with self.assertRaisesRegex(disk.DiskUnaccountable, "type 'devfs' is not accounted"):
            disk.filesystem('/dev')
        isolate_pool(self)
        request = pool.PoolRequest('heavy', '/dev', root='/dev')
        self.addCleanup(request.withdraw)
        with self.assertRaisesRegex(disk.DiskUnaccountable, 'Disk accounting refused for /dev'):
            work.NativeWorkLease.acquire('heavy', '/dev', request=request)


if __name__ == '__main__':
    unittest.main()
