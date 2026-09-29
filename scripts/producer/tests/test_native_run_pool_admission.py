"""NativeRun admission through the real TEST pool: queue, refusal, class and reservation.

Only telemetry, the child and its registry are TEST doubles; the pool, locks, owner
receipts and lifecycle are real. The namespace is private (never the host pool).
"""
from __future__ import annotations

import fcntl
import json
import os
import signal
import subprocess
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import native_work_lease as work
import native_work_pool_disk as disk
from native_render_processes import ProcessIdentity, ProcessRequest
from native_render_resources import GIB, parse_snapshot
from studio.native_owner_queue import pipeline_owner, queued_owner
from studio.native_run import NativeRun
import studio.native_run_disk as served
from native_work_pool_expand import expand_disk
from studio.native_run_disk import disk_request_path
from studio.native_run_config import NativeRunConfig
from studio.native_runtime import digest
from test_native_render_resources import START, raw_sample
from _native_pool_fixture import isolate_pool, members, qualify_fixture_host


class NativeRunPoolAdmissionTests(unittest.TestCase):
    """Real pool admission for a NativeRun whose child and telemetry are doubles."""

    def setUp(self) -> None:
        """Private namespace, owner fixtures and restored signal handlers."""
        self.root = isolate_pool(self)
        temporary = tempfile.TemporaryDirectory(prefix='native-run-pool-')
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name).resolve()
        self.project, self.output = base / 'project', base / 'output'
        self.project.mkdir()
        self.output.mkdir()
        cli, sandbox = base / 'cli.js', base / 'sandbox.sb'
        cli.write_text('TEST executable fixture')
        sandbox.write_text('TEST sandbox fixture')
        self.settings = NativeRunConfig(self.project, self.output, cli, ['TEST-NO-LAUNCH'], {},
            {'output': str(self.output / 'result.bin'), 'sdkSha256': digest(cli), 'sandboxSha256': digest(sandbox)},
            sandbox=sandbox, success_status='TEST mocked lifecycle completed', deadline=60, capacity_wait_seconds=30)
        self.snapshot = parse_snapshot(raw_sample(), ProcessRequest(), 40 * GIB)
        for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            self.addCleanup(signal.signal, number, signal.getsignal(number))

    def execute(self, run: NativeRun, sleep: object, request: str | None = None, poll: object = None) -> bool:
        """Run the real owner lifecycle with a TEST child that writes a non-media output.

        With `request`, the TEST child also writes that disk-expansion request at launch and
        stays alive for two monitor polls (or while `poll` returns None) so its owner can answer.
        """
        child = Mock(pid=100, returncode=0)
        child.poll.return_value = 0
        if request is not None or getattr(self, 'live_child', False):
            child.poll.side_effect = poll or ([None, None] + [0] * 16)
        registry = Mock(known={100: ProcessIdentity(100, START, 100)})
        registry.identities.return_value = [{'pid': 100, 'started': START, 'pgid': 100}]
        registry.cleanup.return_value = {'verified': True, 'TEST': 'mocked child absent'}
        def launched(*_args: object, **_kwargs: object) -> Mock:
            """Create the TEST output the owner requires (and the TEST disk request)."""
            Path(run.result['output']).write_bytes(b'TEST output; not media')
            if request is not None:
                disk_request_path(run.path).write_text(request)
            return child
        # Replace only native_run's own subprocess/time references: the pool itself still
        # runs real sysctl/ps reads through the untouched subprocess module.
        process_module = SimpleNamespace(Popen=Mock(side_effect=launched), DEVNULL=subprocess.DEVNULL,
                                         STDOUT=subprocess.STDOUT, TimeoutExpired=subprocess.TimeoutExpired)
        clock = SimpleNamespace(monotonic=time.monotonic, sleep=sleep)
        with patch('studio.native_measurement_retry.read_snapshot', return_value=self.snapshot), \
                patch('studio.native_run.subprocess', process_module), \
                patch('studio.native_run.OwnedRegistry', return_value=registry), \
                patch.object(NativeRun, 'sample', **getattr(self, 'sample_patch', {})), \
                patch('studio.native_run_admission.time', clock), patch('builtins.print'):
            return run.execute()

    def receipt(self, run: NativeRun) -> dict:
        """The owner's durable receipt."""
        return json.loads(run.path.read_text())

    def test_busy_slot_queues_one_ticket_and_records_queue_time(self) -> None:
        """A busy slot is a persisted wait, then admission; nothing fails or retries elsewhere."""
        holder = work.NativeWorkLease.acquire('heavy', str(self.project))
        run = NativeRun('queued', self.settings)
        seen = []
        def release(_seconds: float) -> None:
            """Record the persisted state, then let the holder finish cleanly."""
            seen.append(self.receipt(run)['status'])
            holder.complete()
            holder.close()
        self.assertTrue(self.execute(run, release))
        receipt = self.receipt(run)
        self.assertEqual(seen, ['waiting-for-capacity'])
        self.assertEqual((receipt['queue']['attempts'], receipt['queue']['admitted']), (2, True))
        self.assertEqual(receipt['queue']['ticket'], receipt['pool']['ticket'])
        self.assertGreaterEqual(receipt['queueSeconds'], 0)
        self.assertEqual((receipt['pool']['mode'], receipt['policy']['maximum_owned_gib']), ('exclusive', 16))
        self.assertTrue(receipt['leaseCleanupVerified'])
        self.assertEqual(members(self.root), [])

    def test_quarantine_refuses_immediately_without_waiting(self) -> None:
        """Unverified cleanup is never waited on; the owner fails before any launch."""
        lost = work.NativeWorkLease.acquire('heavy', str(self.project))
        lost.close()
        run = NativeRun('refused', self.settings)
        sleep = Mock()
        self.assertFalse(self.execute(run, sleep))
        sleep.assert_not_called()
        receipt = self.receipt(run)
        self.assertIn('cleanup is unverified', receipt['abortReason'])
        self.assertEqual(receipt['cleanup'], {'verified': True, 'childNeverLaunched': True})
        self.assertFalse(receipt['queue']['admitted'])

    def test_zero_wait_owner_still_refuses_at_its_bound(self) -> None:
        """Queueing stays bounded: capacity_wait_seconds=0 refuses on the first busy answer."""
        holder = work.NativeWorkLease.acquire('heavy', str(self.project))
        self.addCleanup(holder.close)
        run = NativeRun('bounded', replace(self.settings, capacity_wait_seconds=0, lane='audio'))
        self.assertFalse(self.execute(run, Mock()))
        self.assertIn('Admission refused: Native audio work is already active', self.receipt(run)['abortReason'])
        holder.complete()

    def test_qualified_reservation_bounds_the_guard_and_launch_is_declared(self) -> None:
        """The owner's stop limit equals its 6 GiB reservation; launches are declared first."""
        qualify_fixture_host(self, {'heavy': 2, 'audio': 1})
        run = NativeRun('bound', self.settings)
        phases = []
        original = work.NativeWorkLease.acquire
        def spy(*args: object, **kwargs: object) -> object:
            """Observe the real member's phase right after admission."""
            lease = original(*args, **kwargs)
            phases.append(lease.record['phase'])
            return lease
        with patch.object(work.NativeWorkLease, 'acquire', side_effect=spy):
            self.assertTrue(self.execute(run, Mock()))
        receipt = self.receipt(run)
        self.assertEqual(phases, ['admitted'])
        archived = json.loads((self.root / 'pool-v1' / 'last-heavy.json').read_text())
        self.assertEqual((archived['phase'], archived['cleanupVerified']), ('launching', True))
        self.assertEqual((receipt['policy']['maximum_owned_gib'], receipt['policy']['maximum_process_gib']), (6, 4.5))
        self.assertEqual(receipt['poolReservationBound']['derivedOwnedGib'], 16)
        self.assertEqual(receipt['resourcePolicyDerivation']['budgets']['maximum_owned_gib'], 6)

    def disk_request(self, cache_bytes: int, output_bytes: int) -> str:
        """The request a Long child writes before extracting (native_long_sources.mjs shape)."""
        cache = self.output.parent / 'cache'
        cache.mkdir(exist_ok=True)
        return json.dumps({'schemaVersion': 1, 'id': 'TEST-request', 'directories': [
            {'role': 'cache', 'path': str(cache), 'bytes': cache_bytes},
            {'role': 'output', 'path': str(self.output), 'bytes': output_bytes}]})

    def volumes(self, free: int) -> None:
        """TEST volumes: the cache on device 7, everything else on device 8, both with `free` bytes."""
        self.enterContext(patch.object(disk, 'filesystem', side_effect=lambda path: disk.Filesystem(
            *((7, 'TEST-volume-7') if Path(path).name == 'cache' else (8, 'TEST-volume-8')), free)))

    def test_long_owner_grows_its_reservation_before_the_child_writes(self) -> None:
        """The grant is recorded only after the member's per-filesystem reservation is durable."""
        qualify_fixture_host(self, {'heavy': 2, 'audio': 1})
        self.volumes(60 * GIB)
        run = NativeRun('capture', replace(self.settings, disk_expansion=True))
        durable, original = [], NativeRun.persist
        def persist(owner: NativeRun, initial: bool = False) -> None:
            """Read the pool record at the moment the grant first becomes visible to the child."""
            if 'diskGrant' in owner.result and not durable:
                durable.append(json.loads((self.root / 'pool-v1' / owner.lease.marker).read_text()))
            original(owner, initial)
        with patch.object(NativeRun, 'persist', persist):
            self.assertTrue(self.execute(run, Mock(), self.disk_request(40 * GIB, 5 * GIB)))
        grown = [{'device': 7, 'space': 'TEST-volume-7', 'bytes': 40 * GIB},
                 {'device': 8, 'space': 'TEST-volume-8', 'bytes': 8 * GIB}]  # 3 admitted + 5 requested
        self.assertEqual(durable[0]['diskReservations'], grown)
        receipt = self.receipt(run)
        self.assertEqual(receipt['diskExpansion'], {'status': 'available', 'request': str(disk_request_path(run.path))})
        self.assertEqual((receipt['diskGrant']['status'], receipt['diskGrant']['id']), ('granted', 'TEST-request'))
        self.assertEqual([row['reservationBytes'] for row in receipt['diskGrant']['filesystems']], [40 * GIB, 8 * GIB])
        archived = json.loads((self.root / 'pool-v1' / 'last-heavy.json').read_text())
        self.assertEqual(archived['diskReservations'], grown)
        self.assertTrue(receipt['leaseCleanupVerified'])

    def refused(self, run: NativeRun, request: str, category: str = 'disk-space') -> dict:
        """Execute an owner whose request must be refused; the owner fails after verified cleanup."""
        self.assertFalse(self.execute(run, Mock(), request))
        receipt = self.receipt(run)
        self.assertEqual(receipt['diskGrant']['status'], 'refused')
        self.assertEqual((receipt['status'], receipt['failureCategory']), ('failed', category))
        self.assertIn('Disk reservation refused', receipt['abortReason'])
        self.assertTrue(receipt['leaseCleanupVerified'])
        self.assertFalse((self.root / 'pool-v1' / f"m-{receipt['pool']['member']}.json").exists())
        return receipt['diskGrant']

    def test_refused_request_aborts_the_owner(self) -> None:
        """No child keeps writing against cache bytes another running Long already reserved."""
        qualify_fixture_host(self, {'heavy': 2, 'audio': 1})
        self.volumes(45 * GIB)
        holder = work.NativeWorkLease.acquire('heavy', str(self.project))
        self.addCleanup(holder.close)
        cache = self.output.parent / 'cache'
        cache.mkdir()
        expand_disk(holder, {str(cache): 20 * GIB})
        self.enterContext(patch.object(served, 'DISK_WAIT_SECONDS', 0))  # the window closes on the first try
        grant = self.refused(NativeRun('refused', replace(self.settings, disk_expansion=True)),
                             self.disk_request(30 * GIB, 5 * GIB))
        self.assertIn('reserved by running members', grant['reason'])
        self.assertIn('TEST-volume-7:', grant['reason'])
        holder.complete()

    def waiter(self, run: NativeRun, release: object) -> object:
        """TEST child poll: alive until the owner answers; `release` runs once when it first waits."""
        released = []
        def poll() -> int | None:
            """Report the child alive while its request is unanswered."""
            grant = run.result.get('diskGrant') or {}
            if grant.get('status') == 'waiting' and not released:
                released.append(release())
            return None if grant.get('status') in (None, 'waiting') else 0
        return poll

    def test_waitable_refusal_is_retried_until_the_holder_releases(self) -> None:
        """Running members' bytes are waited for on later ticks; the grant follows their release."""
        qualify_fixture_host(self, {'heavy': 2, 'audio': 1})
        self.volumes(45 * GIB)
        holder = work.NativeWorkLease.acquire('heavy', str(self.project))
        self.addCleanup(holder.close)
        cache = self.output.parent / 'cache'
        cache.mkdir()
        expand_disk(holder, {str(cache): 20 * GIB})
        run = NativeRun('retried', replace(self.settings, disk_expansion=True))
        self.assertTrue(self.execute(run, Mock(), self.disk_request(30 * GIB, 0), self.waiter(run, holder.complete)))
        grant = self.receipt(run)['diskGrant']
        self.assertEqual((grant['status'], grant['filesystems'][0]['reservedByOthersBytes']), ('granted', 0))
        self.assertGreater(grant['attempts'], 1)
        self.assertIn('reserved by running members', grant['lastWaitReason'])

    def test_busy_ledger_is_a_wait_not_an_abort(self) -> None:
        """A ledger held past one tick's bound leaves the request waiting; the next free tick grants it."""
        self.volumes(60 * GIB)
        import native_work_pool_state as state
        state.open_namespace().close()
        lock = os.open(self.root / 'pool-v1' / 'ledger.lock', os.O_CREAT | os.O_RDWR, 0o600)
        self.addCleanup(os.close, lock)
        run = NativeRun('busy', replace(self.settings, disk_expansion=True))
        original, attempts = served.expand_disk, []
        def expand_while_locked(*args: object) -> dict:
            """Hold the ledger (as another process would) only for the first attempt."""
            if not attempts:
                fcntl.flock(lock, fcntl.LOCK_EX)
            attempts.append(args)
            return original(*args)
        self.enterContext(patch.object(served, 'TICK_LEDGER_SECONDS', .2))
        self.enterContext(patch.object(served, 'expand_disk', side_effect=expand_while_locked))
        unlock = lambda: fcntl.flock(lock, fcntl.LOCK_UN)
        self.assertTrue(self.execute(run, Mock(), self.disk_request(GIB, 0), self.waiter(run, unlock)))
        grant = self.receipt(run)['diskGrant']
        self.assertEqual((grant['status'], grant['attempts']), ('granted', 2))
        self.assertIn('ledger is busy', grant['lastWaitReason'])

    def test_host_identity_timeout_is_a_wait_then_a_disk_error(self) -> None:
        """A timed-out sysctl inside expansion never escapes the monitor loop: it waits, then fails as a disk error."""
        self.volumes(60 * GIB)
        original, calls = served.expand_disk, []
        def slow_sysctl(*args: object) -> dict:
            """The TEST host-identity read times out on the first attempt only."""
            calls.append(args)
            if len(calls) == 1:
                raise subprocess.TimeoutExpired(['/usr/sbin/sysctl'], 3)
            return original(*args)
        with patch.object(served, 'expand_disk', side_effect=slow_sysctl):
            run = NativeRun('sysctl', replace(self.settings, disk_expansion=True))
            self.assertTrue(self.execute(run, Mock(), self.disk_request(GIB, 0), self.waiter(run, lambda: None)))
        grant = self.receipt(run)['diskGrant']
        self.assertEqual((grant['status'], grant['attempts']), ('granted', 2))
        self.assertIn('TimeoutExpired', grant['lastWaitReason'])
        self.enterContext(patch.object(served, 'DISK_WAIT_SECONDS', 0))
        self.enterContext(patch.object(served, 'expand_disk', side_effect=subprocess.TimeoutExpired(['sysctl'], 3)))
        self.assertFalse(self.execute(NativeRun('timeout', replace(self.settings, disk_expansion=True)), Mock(),
                                      self.disk_request(GIB, 0)))
        receipt = json.loads((self.output / 'timeout.render.json').read_text())
        self.assertEqual((receipt['diskGrant']['status'], receipt['failureCategory']),
                         ('error', 'disk-reservation-error'))
        self.assertTrue(receipt['abortReason'].startswith('Disk reservation error: TimeoutExpired'))
        self.assertTrue(receipt['leaseCleanupVerified'])

    def test_unaccountable_and_unsupported_refusals_have_their_own_categories(self) -> None:
        """A filesystem the pool cannot charge and an unsupported mix are not reported as disk space."""
        from native_work_pool_fence import NativeWorkUnsupportedMix
        from native_work_pool_storage import DiskUnaccountable
        cases = ((DiskUnaccountable('Disk accounting refused for /TEST: nfs is not a local filesystem'),
                  'disk-unaccountable'),
                 (NativeWorkUnsupportedMix('TEST no qualification profile covers this mix'), 'pool-unsupported-mix'))
        for index, (error, category) in enumerate(cases):
            with self.subTest(category=category), patch.object(served, 'expand_disk', side_effect=error):
                grant = self.refused(NativeRun(f'category-{index}', replace(self.settings, disk_expansion=True)),
                                     self.disk_request(GIB, 0), category)
                self.assertTrue(grant['reason'].startswith(type(error).__name__))

    def test_admission_refusals_that_are_not_render_failures_are_named(self) -> None:
        """A disk-image project and an unsupported mix refused at admission keep their own categories."""
        from native_work_pool_fence import NativeWorkUnsupportedMix
        from native_work_pool_storage import DiskUnaccountable
        cases = ((DiskUnaccountable('Disk accounting refused for /TEST: disk9s1 is not a real disk'),
                  'disk-unaccountable'),
                 (NativeWorkUnsupportedMix('Native heavy work cannot join the pool work present: TEST'),
                  'pool-unsupported-mix'))
        for index, (error, category) in enumerate(cases):
            with self.subTest(category=category), patch.object(disk, 'filesystem', side_effect=error):
                self.assertFalse(self.execute(NativeRun(f'refused-{index}', self.settings), Mock()))
                receipt = json.loads((self.output / f'refused-{index}.render.json').read_text())
                self.assertEqual((receipt['failureCategory'], receipt['leaseCleanupVerified']), (category, False))
                self.assertTrue(receipt['abortReason'].startswith(type(error).__name__))

    def test_host_inspection_timeouts_are_retried_then_named(self) -> None:
        """A sysctl/ps timeout at admission is retried twice with backoff, then fails as its own category."""
        timeout = subprocess.TimeoutExpired(['/usr/sbin/sysctl'], 3)
        real, calls = work.NativeWorkLease.acquire, []
        def flaky(*args: object, **kwargs: object) -> object:
            """Two TEST timeouts, then the real pool."""
            calls.append(args)
            if len(calls) < 3:
                raise timeout
            return real(*args, **kwargs)
        sleeps = Mock()
        with patch.object(work.NativeWorkLease, 'acquire', side_effect=flaky):
            self.assertTrue(self.execute(NativeRun('retried', self.settings), sleeps))
        self.assertEqual([call.args[0] for call in sleeps.call_args_list[:2]], [0.5, 1.0])
        retried = json.loads((self.output / 'retried.render.json').read_text())
        self.assertEqual((len(retried['admissionInspectionTimeouts']), retried['leaseCleanupVerified']), (2, True))
        with patch.object(work.NativeWorkLease, 'acquire', side_effect=timeout):
            self.assertFalse(self.execute(NativeRun('timedout', self.settings), Mock()))
        receipt = json.loads((self.output / 'timedout.render.json').read_text())
        self.assertEqual((receipt['failureCategory'], receipt['leaseCleanupVerified'], receipt['leaseCleanupReason']),
                         ('host-inspection-timeout', False, 'no pool member was admitted'))
        self.assertTrue(receipt['abortReason'].startswith('HostInspectionTimeout: Host inspection timed out 3 times'))

    def test_inspection_backoff_never_sleeps_past_the_admission_deadline(self) -> None:
        """With 0.3 s of admission left the backoff sleeps at most that long, and no retry starts after it."""
        clock = SimpleNamespace(now=100.0)
        def sleep(seconds: float) -> None:
            """TEST clock: sleeping advances monotonic time."""
            clock.now += seconds
        owner = SimpleNamespace(result={}, settings=SimpleNamespace(lane='heavy'), project=self.project)
        timed = SimpleNamespace(monotonic=lambda: clock.now, sleep=Mock(side_effect=sleep))
        with patch('studio.native_run_admission.time', timed), \
                patch.object(work.NativeWorkLease, 'acquire', side_effect=subprocess.TimeoutExpired(['ps'], 3)):
            from studio.native_run_admission import HostInspectionTimeout, _acquire
            with self.assertRaisesRegex(HostInspectionTimeout, 'timed out 1 times'):
                _acquire(owner, Mock(), 100.3)
        self.assertEqual([round(call.args[0], 6) for call in timed.sleep.call_args_list], [0.3])
        self.assertEqual(owner.result['failureCategory'], 'host-inspection-timeout')

    def test_malformed_request_aborts_the_owner(self) -> None:
        """A request without an id and directories is never interpreted as zero demand."""
        grant = self.refused(NativeRun('malformed', replace(self.settings, disk_expansion=True)),
                             '{"schemaVersion": 1}', 'disk-reservation-error')
        self.assertEqual((grant['id'], grant['reason']), (None, 'ValueError: Malformed native disk expansion request'))

    def test_unreadable_request_is_an_error_not_a_refusal(self) -> None:
        """A request the owner cannot safely read (here a link) is an integrity error and still aborts."""
        run = NativeRun('linked', replace(self.settings, disk_expansion=True))
        target = self.output.parent / 'elsewhere.json'
        target.write_text(self.disk_request(0, GIB))
        original = Path.write_text
        def link(path: Path, value: str) -> None:
            """The TEST child plants a symlink instead of its request."""
            if path == disk_request_path(run.path):
                path.symlink_to(target)
                return
            original(path, value)
        with patch.object(Path, 'write_text', link):
            self.assertFalse(self.execute(run, Mock(), 'unused'))
        receipt = self.receipt(run)
        self.assertEqual(receipt['diskGrant']['status'], 'error')
        self.assertEqual(receipt['failureCategory'], 'disk-reservation-error')
        self.assertTrue(receipt['abortReason'].startswith('Disk reservation error: OSError'))
        self.assertTrue(receipt['leaseCleanupVerified'])

    def test_owner_without_disk_expansion_never_reads_a_request(self) -> None:
        """Short owners keep today's protocol exactly: no channel, no grant, no grown record."""
        qualify_fixture_host(self, {'heavy': 2, 'audio': 1})
        self.volumes(60 * GIB)
        run = NativeRun('short', self.settings)
        self.assertTrue(self.execute(run, Mock(), self.disk_request(40 * GIB, 5 * GIB)))
        receipt = self.receipt(run)
        self.assertNotIn('diskExpansion', receipt)
        self.assertNotIn('diskGrant', receipt)
        archived = json.loads((self.root / 'pool-v1' / 'last-heavy.json').read_text())
        self.assertNotIn('diskReservations', archived)
        self.assertEqual(archived['diskReservationBytes'], 3 * GIB)

    def test_owner_queue_settings(self) -> None:
        """Immediate owners gain the bounded queue; queued owners keep their bounds."""
        immediate = replace(self.settings, capacity_wait_seconds=0, deadline=600)
        queued = queued_owner(immediate)
        self.assertEqual((queued.deadline, queued.capacity_wait_seconds, queued.lane), (1200, 600, 'heavy'))
        self.assertIs(queued_owner(queued).deadline, queued.deadline)
        self.assertEqual(pipeline_owner(immediate, 'preview-package-3').lane, 'audio')
        budgeted = pipeline_owner(immediate, 'pipeline', remaining=250.0)
        self.assertEqual((budgeted.deadline, budgeted.capacity_wait_seconds), (250.0, 250.0))
        with self.assertRaisesRegex(RuntimeError, 'budget is exhausted'):
            queued_owner(immediate, remaining=0)
        self.assertEqual(pipeline_owner(immediate, 'preview-picture-3').lane, 'heavy')
        with self.assertRaisesRegex(ValueError, 'pool class'):
            replace(self.settings, lane='preview-control')
        with self.assertRaisesRegex(ValueError, 'disk reservation'):
            replace(self.settings, disk_reservation_bytes=-1)
        with self.assertRaisesRegex(ValueError, 'disk expansion'):
            replace(self.settings, disk_expansion='yes')


if __name__ == '__main__':
    unittest.main()
