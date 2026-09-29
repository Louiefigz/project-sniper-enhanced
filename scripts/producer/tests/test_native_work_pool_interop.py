"""Multi-process pool behaviour: legacy code, killed waiters/supervisors, sessions, tmp aging.

Separate supervisor processes run tests/fixtures/native_pool_driver.py against the same
private TEST namespace; the unmodified baseline lease code runs from a fixture copy.
"""
from __future__ import annotations

import fcntl
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

import native_work_lease as work
import native_work_pool as pool
import native_work_pool_disk as disk
import native_work_pool_expand as expand
import native_work_pool_state as state
import native_work_recovery as recovery
import native_work_session as session
from native_work_pool_observe import observe
from native_work_pool_state import NativeWorkQuarantined, NativeWorkQueued
from _native_pool_fixture import (
    GIB, TEST_HOST, hold_legacy_exclusive, isolate_pool, legacy_record, members, project_dir,
    qualify_fixture_host, write_legacy_marker,
)

PRODUCER = Path(__file__).resolve().parents[1]
DRIVER = PRODUCER / 'tests/fixtures/native_pool_driver.py'
BASE_DRIVER = PRODUCER / 'tests/fixtures/base_pool_driver.py'  # vendored 4a15560 client, SOURCE.json-checked


def gone(pid: int) -> bool:
    """Whether a process no longer exists (zombies of our own children are reaped first)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


class PoolInteropTests(unittest.TestCase):
    """Real locks, files and processes; never the host's canonical namespace."""

    def setUp(self) -> None:
        """Private namespace and a real project directory for disk accounting."""
        self.root = isolate_pool(self)
        self.project = str(project_dir(self))

    def driver(self, *args: str, record: str = '-', stdin: int | None = None) -> subprocess.Popen:
        """Start one TEST supervisor process; it is always killed at cleanup."""
        process = subprocess.Popen([sys.executable, '-B', str(DRIVER), args[0], str(self.root), record,
                                    *args[1:]], stdout=subprocess.PIPE, stdin=stdin, text=True, cwd=PRODUCER)
        self.addCleanup(self.stop, process)
        return process

    def stop(self, process: subprocess.Popen) -> None:
        """Kill and reap a driver that is still running."""
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
        process.stdout.close()
        if process.stdin:
            process.stdin.close()

    def go(self, process: subprocess.Popen) -> None:
        """Release a TEST driver waiting on stdin and require that it starts its transaction."""
        process.stdin.write('go\n')
        process.stdin.flush()
        self.assertEqual(self.event(process)['event'], 'transacting')

    def event(self, process: subprocess.Popen) -> dict:
        """Read the next JSON event line from a driver."""
        line = process.stdout.readline()
        self.assertTrue(line, 'TEST driver exited without an event')
        return json.loads(line)

    def acquire(self, lane: str = 'heavy') -> object:
        """Admit in this process through the public entry point."""
        lease = work.NativeWorkLease.acquire(lane, self.project)
        self.addCleanup(lease.close)
        return lease

    def test_baseline_lease_code_and_pool_exclude_each_other(self) -> None:
        """Old code refuses while members hold the shared fence and runs when the pool is idle."""
        member = self.acquire()
        refused = self.driver('legacy', self.project)
        self.assertIn('already active', self.event(refused)['reason'])
        member.complete()
        member.close()
        admitted = self.driver('legacy', self.project)
        self.assertEqual(self.event(admitted)['event'], 'legacy-admitted')
        admitted.wait(timeout=10)
        hold_legacy_exclusive(self, self.root)
        with self.assertRaisesRegex(NativeWorkQueued, 'legacy exclusive heavy work is running'):
            work.NativeWorkLease.acquire('audio', self.project)

    def test_running_legacy_job_marker_is_waitable_not_quarantined(self) -> None:
        """An old-code job holding heavy.lock owns its marker: the pool waits, never quarantines."""
        write_legacy_marker(self.root, legacy_record('c' * 32, os.getpid(), []))
        hold_legacy_exclusive(self, self.root)
        with self.assertRaisesRegex(NativeWorkQueued, 'legacy exclusive heavy work is running') as caught:
            work.NativeWorkLease.acquire('heavy', self.project)
        self.assertNotIn('quarantined', str(caught.exception))

    def test_legacy_marker_is_one_quarantined_heavy_slot(self) -> None:
        """Exclusive hosts stop (today's rule); qualified hosts charge one slot and 16 GiB."""
        write_legacy_marker(self.root, legacy_record('b' * 32, 987654321, []))
        with self.assertRaisesRegex(NativeWorkQuarantined, 'legacy-heavy.active.json'):
            work.NativeWorkLease.acquire('audio', self.project)
        qualify_fixture_host(self, {'heavy': 3, 'audio': 1})
        member = self.acquire()
        self.assertEqual((member.admission['occupied'], member.admission['quarantinedChargedBytes']),
                         (1, 16 * GIB))
        member.complete()

    def test_killed_waiter_is_pruned_by_its_released_ticket_lock(self) -> None:
        """A SIGKILLed queued supervisor never blocks the queue; evidence names it."""
        holder = self.acquire()
        waiter = self.driver('queue', 'heavy', self.project)
        queued = self.event(waiter)
        self.assertEqual(queued['event'], 'queued')
        waiter.kill()
        waiter.wait(timeout=10)
        holder.complete()
        admitted = self.acquire()
        pruned = [row for row in admitted.admission['pruned'] if row['ticket']]
        self.assertEqual(len(pruned), 1)
        self.assertIs(pruned[0]['waiterIdentityLive'], False)
        self.assertEqual(pruned[0]['waiter']['pid'], waiter.pid)
        admitted.complete()

    def test_sigkilled_supervisor_quarantines_until_absence_is_proved(self) -> None:
        """Deadline, missing heartbeat or one missing PID never frees; recovery must prove it."""
        holder = self.driver('hold', 'heavy', self.project, '600', '--child')
        admitted = self.event(holder)
        child = admitted['child']
        self.addCleanup(lambda: gone(child) or os.kill(child, signal.SIGKILL))
        holder.send_signal(signal.SIGKILL)
        holder.wait(timeout=10)
        with self.assertRaisesRegex(NativeWorkQuarantined, admitted['nonce']):
            work.NativeWorkLease.acquire('heavy', self.project)
        with self.assertRaisesRegex(work.NativeWorkBusy, 'children are still alive'):
            recovery.recover(admitted['nonce'])
        os.kill(child, signal.SIGKILL)
        deadline = time.monotonic() + 10
        while not gone(child) and time.monotonic() < deadline:
            time.sleep(.05)
        result = recovery.recover(admitted['nonce'])
        self.assertEqual((result['recordedIdentityCount'], result['supervisorAbsent']), (1, True))
        self.acquire().complete()

    def test_acquire_until_waits_in_order_and_honours_its_deadline(self) -> None:
        """A bounded waiter is refused at its deadline and admitted after the holder exits."""
        holder = self.driver('hold', 'heavy', self.project, '1.5')
        self.assertEqual(self.event(holder)['event'], 'admitted')
        started = time.monotonic()
        with self.assertRaises(NativeWorkQueued):
            pool.acquire_until('heavy', self.project, time.monotonic() + .3)
        self.assertLess(time.monotonic() - started, 5)
        lease = pool.acquire_until('heavy', self.project, time.monotonic() + 30)
        self.addCleanup(lease.close)
        self.assertEqual(self.event(holder)['event'], 'completed')
        lease.complete()
        self.assertEqual(sorted((self.root / 'pool-v1').glob('t-*.json')), [])

    def test_session_candidate_applies_only_to_declared_jobs(self) -> None:
        """Declared harness jobs share the candidate size; everything else waits."""
        self.enterContext(mock.patch.object(pool.policy, 'host_identity', return_value=dict(TEST_HOST)))
        declared = [str(project_dir(self, f'attempt-{index}')) for index in range(2)]
        jobs = [{'project': self.project, 'attempt': attempt} for attempt in declared]
        live = session.open_session({'heavySlots': 2, 'audioSlots': 1}, jobs, 600)
        self.addCleanup(live.close)
        leases = []
        for attempt in declared:
            request = pool.PoolRequest('heavy', self.project, root=attempt)
            leases.append(work.NativeWorkLease.acquire('heavy', self.project, request=request))
            self.addCleanup(leases[-1].close)
        self.assertEqual({lease.admission['mode'] for lease in leases}, {'qualification-session'})
        self.assertEqual([lease.reservation_bytes for lease in leases], [6 * GIB] * 2)
        inner = Path(declared[0]) / 'audio-stage'
        inner.mkdir()
        audio = work.NativeWorkLease.acquire('audio', self.project,
                                             request=pool.PoolRequest('audio', self.project, root=str(inner)))
        self.addCleanup(audio.close)
        self.assertEqual(audio.admission['mode'], 'qualification-session')
        audio.complete()
        sibling = Path(declared[0] + '-TEST-sibling')
        sibling.mkdir()
        outside = pool.PoolRequest('audio', self.project, root=str(sibling))
        with self.assertRaisesRegex(NativeWorkQueued, 'qualification session'):
            work.NativeWorkLease.acquire('audio', self.project, request=outside)
        outside.withdraw()
        with self.assertRaisesRegex(NativeWorkQueued, 'qualification session'):
            work.NativeWorkLease.acquire('audio', self.project)
        with self.assertRaisesRegex(RuntimeError, 'idle pool'):
            session.open_session({'heavySlots': 2, 'audioSlots': 1}, jobs, 600)
        for lease in leases:
            lease.complete()
        live.close()
        self.acquire('audio').complete()

    def test_transactions_refresh_state_against_tmp_cleaner(self) -> None:
        """Quarantine records and the legacy fence cannot age past three days while in use."""
        lost = self.acquire()
        lost.close()
        old = time.time() - 4 * 86400
        names = [members(self.root)[0], self.root / 'pool-v1' / f'm-{lost.nonce}.lock', self.root / 'heavy.lock']
        for path in names:
            os.utime(path, (old, old))
        with self.assertRaises(NativeWorkQuarantined):
            work.NativeWorkLease.acquire('heavy', self.project)
        for path in names:
            self.assertGreater(path.stat().st_mtime, time.time() - 60, path.name)

    def test_busy_ledger_refusal_is_bounded_and_waitable(self) -> None:
        """A stopped ledger holder cannot hang admission past its bound."""
        state.open_namespace().close()
        descriptor = os.open(self.root / 'pool-v1' / 'ledger.lock', os.O_CREAT | os.O_RDWR, 0o600)
        self.addCleanup(os.close, descriptor)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        self.enterContext(mock.patch.object(state, 'LEDGER_WAIT_SECONDS', .2))
        started = time.monotonic()
        with self.assertRaisesRegex(NativeWorkQueued, 'ledger is busy'):
            work.NativeWorkLease.acquire('heavy', self.project)
        self.assertLess(time.monotonic() - started, 2)


class DiskExpansionInteropTests(unittest.TestCase):
    """Expansion against separate supervisor processes: races and crashes on real locks and files."""

    FREE = 45 * GIB

    def setUp(self) -> None:
        """Qualified TEST host; every process sees the same fixed free bytes on the real device."""
        self.root = isolate_pool(self)
        self.record = str(qualify_fixture_host(self, {'heavy': 3, 'audio': 1}))
        self.project = str(project_dir(self))
        real = disk.filesystem
        self.enterContext(mock.patch.object(disk, 'filesystem',
                                            side_effect=lambda path: real(path)._replace(free=self.FREE)))

    driver, stop, event, go = (PoolInteropTests.driver, PoolInteropTests.stop, PoolInteropTests.event,
                               PoolInteropTests.go)

    def expander(self, name: str, point: str = 'none') -> tuple[subprocess.Popen, str]:
        """A TEST supervisor admitted with the default 3 GiB that will grow to 30 GiB on 'go'."""
        attempt = str(project_dir(self, name))
        process = self.driver('expand', self.project, attempt, str(30 * GIB), str(self.FREE), point,
                              record=self.record, stdin=subprocess.PIPE)
        admitted = self.event(process)
        self.assertEqual(admitted['event'], 'admitted')
        return process, admitted['nonce']

    def finished(self, process: subprocess.Popen) -> dict:
        """Skip the owner's own status lines until the driver reports the finished owner."""
        while True:
            row = self.event(process)
            if row.get('event') == 'owner-finished':
                return row

    def reserved(self) -> int:
        """Sum of every member record's disk reservation (one TEST volume); pending files are not records."""
        return sum(size for path in members(self.root) if state.MEMBER.fullmatch(path.name)
                   for _space, size in disk.record_disks(json.loads(path.read_text())).values())

    def test_expansion_racing_an_admission_never_overspends_the_volume(self) -> None:
        """Both alone fit; the ledger orders them, the second is refused with the reservation reason."""
        long, _nonce = self.expander('long')
        short = self.driver('admit-disk', self.project, str(project_dir(self, 'short')), str(10 * GIB),
                            str(self.FREE), record=self.record, stdin=subprocess.PIPE)
        lock = os.open(self.root / 'pool-v1' / 'ledger.lock', os.O_RDWR)
        self.addCleanup(os.close, lock)
        fcntl.flock(lock, fcntl.LOCK_EX)
        self.go(long)
        self.go(short)
        time.sleep(.3)  # both transactions now poll the held ledger lock
        fcntl.flock(lock, fcntl.LOCK_UN)
        outcomes = {'long': self.event(long), 'short': self.event(short)}
        winners = [name for name, row in outcomes.items() if row['event'] in ('expanded', 'admitted')]
        self.assertEqual(len(winners), 1, outcomes)
        loser = outcomes['short' if winners == ['long'] else 'long']
        self.assertEqual(loser['event'], 'refused')
        self.assertIn('reserved by running members', loser['reason'])
        self.assertLessEqual(self.reserved() + 10 * GIB, self.FREE)

    def test_crash_during_expansion_keeps_an_exact_record_and_frees_the_ledger(self) -> None:
        """Dying before, part-way through or after publishing leaves the old or the grown record."""
        for point, grown in (('before-publish', False), ('pending-written', False), ('after-publish', True)):
            with self.subTest(point=point):
                process, nonce = self.expander(f'attempt-{point}', point)
                self.go(process)
                self.assertEqual(process.wait(timeout=10), 3)
                stored = json.loads((self.root / 'pool-v1' / f'm-{nonce}.json').read_text())
                self.assertEqual({device: size for device, (_space, size) in disk.record_disks(stored).items()},
                                 {stored['diskDevice']: (33 if grown else 3) * GIB})
                self.assertEqual('diskReservations' in stored, grown)
                pending = self.root / 'pool-v1' / f'm-{nonce}.pending.json'
                self.assertEqual(pending.exists(), point == 'pending-written')  # ignored: never a member record
                started = time.monotonic()
                request = pool.PoolRequest('heavy', self.project, disk_bytes=10 * GIB)
                if grown:  # 45 - 33 quarantined < 10 + 10 reserve: the crashed grant stays charged
                    with self.assertRaisesRegex(NativeWorkQuarantined, 'disk headroom for output'):
                        work.NativeWorkLease.acquire('heavy', self.project, request=request)
                else:
                    work.NativeWorkLease.acquire('heavy', self.project, request=request).complete()
                request.withdraw()
                self.assertLess(time.monotonic() - started, 2, 'the dead expander left the ledger locked')
                proof = json.loads(Path(recovery.recover(nonce)['proof']).read_text())
                self.assertEqual(proof['originalRecord'], stored)
                self.assertEqual(self.reserved(), 0)

    def two_real_owners(self, wait: str) -> list[dict]:
        """Two real Long-style owners on one volume whose children ask for 30 GiB each at once."""
        go, owners = self.root.parent / f'TEST-go-{wait}', []
        for name in ('first', 'second'):
            attempt = project_dir(self, f'{name}-{wait}')
            owners.append((self.driver('disk-owner', str(attempt), str(30 * GIB), str(50 * GIB), str(go), '4',
                                       wait, record=self.record), attempt))
            self.assertEqual(self.event(owners[-1][0])['event'], 'owner-started')
        deadline = time.monotonic() + 120
        while not all((attempt / 'TEST-ready').exists() for _process, attempt in owners):
            self.assertLess(time.monotonic(), deadline, 'TEST children never launched')
            time.sleep(.05)
        go.touch()  # 3 + 30 + 10 fits 50 - 3 once; twice needs 76 GiB
        finished = [self.finished(process) for process, _attempt in owners]
        receipts = [json.loads(Path(row['receipt']).read_text()) for row in finished]
        self.assertTrue(all(receipt.get('leaseCleanupVerified') for receipt in receipts),
                        [(receipt.get('status'), receipt.get('abortReason')) for receipt in receipts])
        self.assertEqual(self.reserved(), 0)
        # Granted before refused, then by attempts: which owner transacts first is the ledger's choice.
        return sorted(receipts, key=lambda receipt: (receipt['diskGrant']['status'] != 'granted',
                                                     receipt['diskGrant']['attempts']))

    def test_two_real_long_owners_cannot_both_grow_into_one_volume(self) -> None:
        """Without a wait window the second owner is refused with the disk category and aborts."""
        granted, refused = self.two_real_owners('0')
        self.assertEqual((granted['diskGrant']['status'], refused['diskGrant']['status']), ('granted', 'refused'))
        self.assertIn('reserved by running members', refused['diskGrant']['reason'])
        self.assertTrue(refused['abortReason'].startswith('Disk reservation refused'))
        self.assertEqual((refused['status'], refused['failureCategory']), ('failed', 'disk-space'))

    def test_second_long_waits_for_the_first_and_is_then_granted(self) -> None:
        """Inside the window a waitable refusal is retried; the grant comes only after the first released."""
        first, second = self.two_real_owners('30')
        self.assertEqual([receipt['diskGrant']['status'] for receipt in (first, second)], ['granted', 'granted'])
        self.assertGreater(second['diskGrant']['attempts'], 1)
        self.assertIn('reserved by running members', second['diskGrant']['lastWaitReason'])
        self.assertEqual(second['diskGrant']['filesystems'][0]['reservedByOthersBytes'], 0)
        self.assertEqual(second['status'], 'TEST synthetic owner complete')

    def test_real_js_request_is_served_by_the_real_owner(self) -> None:
        """The production JS requestLongDiskGrant and Python serve_disk_request agree end to end."""
        node = shutil.which('node')
        self.assertIsNotNone(node, 'node is required for the native JS suite')
        attempt, cache = project_dir(self, 'js-attempt'), project_dir(self, 'js-cache')
        process = self.driver('js-disk-owner', str(attempt), str(cache), node, record=self.record)
        started = self.event(process)
        finished = self.finished(process)
        receipt = json.loads(Path(started['receipt']).read_text())
        self.assertTrue(finished['success'], receipt.get('abortReason'))
        self.assertEqual(json.loads((attempt / 'result.bin').read_text()), receipt['diskGrant'])
        self.assertEqual(receipt['diskGrant']['status'], 'granted')
        request = json.loads((attempt / 'TEST-heavy.disk-request.json').read_text())
        self.assertEqual([(row['role'], row['bytes']) for row in request['directories']], [('cache', 2 * GIB)])
        archived = json.loads((self.root / 'pool-v1' / 'last-heavy.json').read_text())
        self.assertEqual(sum(row['bytes'] for row in archived['diskReservations']), 5 * GIB)  # 3 admitted + 2

    def base_driver(self, *args: str) -> subprocess.Popen:
        """The unmodified base-engine (4a15560) client from its hash-checked vendored copy."""
        process = subprocess.Popen([sys.executable, '-B', str(BASE_DRIVER), args[0], str(self.root), self.record,
                                    *args[1:]], stdout=subprocess.PIPE, stdin=subprocess.PIPE, text=True,
                                   cwd=PRODUCER)
        self.addCleanup(self.stop, process)
        return process

    def test_earlier_engine_admission_sees_only_the_root_mirror(self) -> None:
        """Base-commit pool code charges a grown record's root device, never a sibling volume it grew onto."""
        sibling = next(path for path in ('/System/Volumes/Preboot', '/System/Volumes/VM') if Path(path).is_dir())
        attempt = str(project_dir(self, 'attempt'))
        self.assertEqual(disk.filesystem(sibling).space, disk.filesystem(attempt).space)  # one APFS container
        long = work.NativeWorkLease.acquire('heavy', self.project, request=pool.PoolRequest(
            'heavy', self.project, root=attempt))
        self.addCleanup(long.close)
        expand.expand_disk(long, {sibling: 4 * GIB, attempt: GIB})
        viewer = self.base_driver('disk-view', self.project, attempt, sibling)
        seen = {row['root']: row['reservedByOthersBytes'] for row in (self.event(viewer), self.event(viewer))}
        self.assertEqual(seen[attempt], 4 * GIB)  # 3 admitted + 1 grown, mirrored on the root device
        self.assertEqual(seen[sibling], 0, 'the documented earlier-engine limit: per-device, not per-container')
        long.complete()

    def test_live_base_engine_member_is_charged_and_reaches_the_fence_hook(self) -> None:
        """A real 4a15560 member is charged by root space; the fence hook sees its unmarked record."""
        base = self.base_driver('admit-disk', self.project, str(project_dir(self, 'base')), str(3 * GIB),
                                str(self.FREE))
        self.go(base)
        admitted = self.event(base)
        self.assertEqual(admitted['event'], 'admitted')
        stored = json.loads((self.root / 'pool-v1' / f"m-{admitted['nonce']}.json").read_text())
        self.assertNotIn('diskAccounting', stored)
        attempt = str(project_dir(self, 'current'))
        lease = work.NativeWorkLease.acquire('heavy', self.project, request=pool.PoolRequest(
            'heavy', self.project, root=attempt))
        self.addCleanup(lease.close)
        self.assertEqual(lease.admission['diskReservedByOthersBytes'], 3 * GIB)
        with mock.patch.object(expand, 'off_root_fence') as fence:
            expand.expand_disk(lease, {attempt: GIB})
        _namespace, view, member, off_root = fence.call_args.args
        records = {member['nonce']: member['record'] for member in view.members}
        self.assertEqual((member, off_root), (lease, False))
        self.assertNotIn('diskAccounting', records[admitted['nonce']])
        base.stdin.write('done\n')
        base.stdin.flush()
        self.assertEqual(base.wait(timeout=30), 0)
        lease.complete()

if __name__ == '__main__':
    unittest.main()
