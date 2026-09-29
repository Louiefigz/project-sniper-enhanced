"""A long owner's recorded identities stay bounded, and an overflow never strands its slot.

Review of R1: an owner that retained every exited identity passed the 4,096-row lease
bound after about 150 minutes (~27 exits/min in the F0 journal), failed as
renderer-failure, and left its pool slot quarantined although cleanup was verified.
Every test here uses a private pool namespace and a TEST process table; nothing is
launched or signalled.
"""
from __future__ import annotations

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
from native_render_resources import GIB, parse_snapshot
from native_render_processes import ProcessRequest
from native_render_sampling import read_compact_snapshot
from studio.native_owned_processes import OwnedProcess, OwnedRegistry
from studio.native_run import NativeRun
from studio.native_run_config import NativeRunConfig
from studio.native_run_lifecycle import failure_category
from studio.native_runtime import digest
from test_native_render_policy import policy_snapshot
from test_native_render_resources import START, direct_sample, raw_sample
from _native_pool_fixture import isolate_pool, members

EPOCH = time.mktime(time.strptime(START, '%a %b %d %H:%M:%S %Y'))


def lstart(second: float) -> str:
    """A ps lstart string for a TEST process started ``second`` after START."""
    return time.strftime('%a %b %e %H:%M:%S %Y', time.localtime(EPOCH + second))


class ChurnTable:
    """A TEST process table: one root whose short children exit every step.

    Child PIDs come from a small ring. On even steps new children take the PIDs that
    just exited, whose identities are still recorded (the registry replaces them; the
    lease must retire the old rows). Every fifth step an exited PID goes to an
    unrelated process instead.
    """

    def __init__(self, children: int, ring: int = 16) -> None:
        """Start with the live root (parent: this test process) and one unrelated process."""
        self.children, self.ring, self.next = children, range(1000, 1000 + ring), 0
        self.rows = {100: (os.getpid(), 100, START), 500: (1, 500, START)}
        self.spawned, self.foreign = 0, 0

    def allocate(self, reuse: list[int]) -> int:
        """A just-exited PID when offered, else the next ring PID no live process holds."""
        if reuse:
            return reuse.pop(0)
        while True:
            pid = self.ring[self.next % len(self.ring)]
            self.next += 1
            if pid not in self.rows:
                return pid

    def step(self, number: int) -> None:
        """Exit every child and foreign process, then start this step's processes."""
        exited = [pid for pid, row in self.rows.items() if pid >= 1000]
        for pid in exited:
            del self.rows[pid]
        if number % 5 == 0 and exited:
            self.rows[exited[0]] = (1, exited[0], lstart(number * 10 + 1))  # unrelated holder
            self.foreign += 1
        reuse = [pid for pid in exited if pid not in self.rows] if number % 2 == 0 else []
        for _ in range(self.children):
            self.rows[self.allocate(reuse)] = (100, 100, lstart(number * 10 + 2))
            self.spawned += 1

    def ps(self) -> str:
        """The table in `ps -axo pid=,ppid=,pgid=,lstart=` form."""
        return ''.join(f'{pid} {row[0]} {row[1]} {row[2]}\n' for pid, row in sorted(self.rows.items()))

    def owned(self) -> dict[int, OwnedProcess]:
        """The table as the registry's own ps reader returns it."""
        return {pid: OwnedProcess(pid, *row) for pid, row in self.rows.items()}

    def envelope(self) -> str:
        """One bracketed sampler reading with a small footprint for every owned process."""
        top = ''.join(f'{pid} 10M 0B\n' for pid, row in sorted(self.rows.items())
                      if pid == 100 or row[0] == 100)
        raw = direct_sample(raw_sample() | {'ps': self.ps(), 'top': top})
        return json.dumps({'before': self.ps(), 'after': self.ps(), 'direct': json.loads(raw['direct'])})


class IdentityRetirementTests(unittest.TestCase):
    """Real pool lease, owner receipt, registry and sampler parse over a TEST table."""

    def setUp(self) -> None:
        """Admit one heavy owner through the private pool; bind a real registry."""
        self.pool = isolate_pool(self)
        base = Path(self.enterContext(tempfile.TemporaryDirectory(prefix='native-retire-'))).resolve()
        self.project, output = base / 'project', base / 'output'
        self.project.mkdir(); output.mkdir()
        cli, sandbox = base / 'cli.js', base / 'sandbox.sb'
        cli.write_text('TEST executable'); sandbox.write_text('TEST sandbox')
        self.settings = NativeRunConfig(self.project, output, cli, ['TEST-NO-LAUNCH'], {},
            {'output': str(output / 'result.bin'), 'sdkSha256': digest(cli), 'sandboxSha256': digest(sandbox)},
            sandbox=sandbox, deadline=60, capacity_wait_seconds=30)
        for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            self.addCleanup(signal.signal, number, signal.getsignal(number))
        self.enterContext(patch('builtins.print'))
        self.table = ChurnTable(children=6)

    def owner(self) -> NativeRun:
        """A prepared owner holding a real pool member, with the registry bound to the table."""
        owner = NativeRun('TEST', self.settings)
        with patch.object(owner, 'measure_resources',
                          return_value=replace(policy_snapshot(), measured_at=time.time() - 20)):
            owner.prepare()
        self.addCleanup(owner.signal_handlers.restore)
        for handle in (owner.log, owner.samples):
            self.addCleanup(handle.close)
        owner.child = Mock(pid=100, returncode=0)
        owner.child.poll.return_value = None
        with patch('studio.native_owned_processes.read_processes', return_value=self.table.owned()):
            owner.registry = OwnedRegistry(100)
        return owner

    def kernel(self) -> tuple:
        """Route the registry, sampler and lease absence checks to the TEST table."""
        def ps_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess:
            """The lease's own `ps` absence check reads the TEST table."""
            return subprocess.CompletedProcess(['/bin/ps'], 0, self.table.ps(), '')
        return (patch('studio.native_owned_processes.read_processes', side_effect=lambda: self.table.owned()),
                patch.object(work, 'subprocess', SimpleNamespace(run=ps_run)),
                patch('native_render_sampling.shutil.disk_usage', return_value=SimpleNamespace(free=40 * GIB)),
                patch('studio.native_owned_processes.os.kill', side_effect=AssertionError('TEST: no signal')))

    def sample(self, owner: NativeRun) -> None:
        """One monitor iteration: discover, record, then a real parsed sample."""
        raw = raw_sample()
        def measured(request: ProcessRequest) -> object:
            """The real compact sampler over this step's table."""
            with patch('native_render_sampling._read_command',
                       side_effect=[raw['sysctl'], raw['pressure'], self.table.envelope()]):
                return read_compact_snapshot(self.project, request)
        owner.registry.live()
        owner.record_lease_processes()
        with patch.object(owner, 'measure_resources', side_effect=measured):
            owner.sample()

    def test_three_hour_churn_stays_bounded_and_releases_its_slot(self) -> None:
        """6,480 exited identities (1,080 samples, 10 s apart) never approach the bound."""
        owner, largest = self.owner(), {'lease': 0, 'registry': 0}
        patches = self.kernel()
        for active in patches:
            self.enterContext(active)
        for number in range(1, 1081):
            self.table.step(number)
            self.sample(owner)
            self.assertIsNone(owner.abort_reason, f'step {number}')
            largest['lease'] = max(largest['lease'], len(owner.lease.record['processes']))
            largest['registry'] = max(largest['registry'], len(owner.registry.known))
        self.assertGreaterEqual(self.table.spawned - self.table.children, 6000)
        self.assertGreater(self.table.spawned, work.MAX_RECORDED_IDENTITIES)  # Old retention overflowed.
        self.assertGreaterEqual(self.table.foreign, 200)
        self.assertLessEqual(largest['lease'], 3 * self.table.children + 2)
        self.assertLessEqual(largest['registry'], 2 * self.table.children + 1)
        retirement = json.loads(owner.path.read_text())['identityRetirement']
        self.assertGreaterEqual(retirement['lease'], 6000)
        self.assertLess(retirement['registry'], retirement['lease'] - 2500)  # Replaced, not missing.
        self.assertEqual(retirement['leaseDeferred'], 0)
        self.table.rows = {500: self.table.rows[500]}  # The render exits; nothing owned remains.
        owner.result['cleanup'] = owner.registry.cleanup(owner.child)
        owner.release_lease()
        self.assertEqual((owner.result['cleanup']['verified'], owner.result['leaseCleanupVerified']), (True, True))
        self.assertEqual(members(self.pool), [])
        work.NativeWorkLease.acquire('heavy', str(self.project)).close()

    def test_overflow_is_named_and_a_verified_cleanup_releases_the_slot(self) -> None:
        """More than 4,096 live identities stop the owner by name; the slot is not stranded."""
        owner = self.owner()
        for pid in range(2000, 2000 + work.MAX_RECORDED_IDENTITIES):
            owner.registry.known[pid] = OwnedProcess(pid, 100, 100, START)
        with self.assertRaises(work.ProcessRegistryOverflow):
            owner.record_lease_processes()
        self.assertEqual(owner.result['failureCategory'], 'process-registry-overflow')
        owner.abort_reason = 'ProcessRegistryOverflow: Native process registry must be a bounded list'
        owner.result['cleanup'] = {'verified': True, 'TEST': 'registry cleanup proved every identity absent'}
        with patch.object(work, '_live_identities', return_value=[]):
            owner.release_lease()
        self.assertTrue(owner.result['leaseCleanupVerified'])
        self.assertIn('bounded list', owner.result['leaseRecordOverflowAtRelease'])
        self.assertEqual(failure_category(dict(owner.result, status='failed', abortReason=owner.abort_reason)),
                         'process-registry-overflow')
        self.assertEqual(members(self.pool), [])
        work.NativeWorkLease.acquire('heavy', str(self.project)).close()

    def test_unverified_cleanup_after_overflow_still_quarantines(self) -> None:
        """Only a verified cleanup releases the slot; an overflow alone never does."""
        owner = self.owner()
        owner.registry.known.update({pid: OwnedProcess(pid, 100, 100, START)
                                     for pid in range(2000, 2000 + work.MAX_RECORDED_IDENTITIES)})
        owner.result['cleanup'] = {'verified': False, 'survivors': [{'pid': 2000}]}
        owner.release_lease()
        self.assertEqual((owner.result['leaseCleanupVerified'], owner.result['leaseCleanupReason']),
                         (False, 'owned-process cleanup was not verified; the member stays quarantined'))
        self.assertEqual(len(members(self.pool)), 1)
        with self.assertRaises(Exception):
            work.NativeWorkLease.acquire('heavy', str(self.project)).close()


class LeaseRetirementTests(unittest.TestCase):
    """Both lease kinds drop a row only after their own process table read shows it absent."""

    def setUp(self) -> None:
        """Private namespace; the absence check reads a TEST table."""
        self.pool = isolate_pool(self)
        self.project = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.rows = {'live': {'pid': 101, 'started': START, 'pgid': 100},
                     'exited': {'pid': 102, 'started': START, 'pgid': 100},
                     'reassigned': {'pid': 103, 'started': START, 'pgid': 100}}
        table = f'101 100 100 {START}\n103 1 103 {lstart(60)}\n'
        run = Mock(return_value=subprocess.CompletedProcess(['/bin/ps'], 0, table, ''))
        self.enterContext(patch.object(work, 'subprocess', SimpleNamespace(run=run)))

    def test_only_absent_rows_are_retired_for_every_lease_kind(self) -> None:
        """A live row survives retirement; exited and reassigned rows are dropped durably."""
        for lane in ('preview-control', 'heavy'):
            with self.subTest(lane=lane):
                lease = work.NativeWorkLease.acquire(lane, str(self.project))
                lease.record_processes(list(self.rows.values()))
                self.assertEqual(lease.retire_processes(list(self.rows.values())), [self.rows['live']])
                self.assertEqual(lease.record['processes'], [self.rows['live']])
                lease._assert_owner()  # The durable record equals the retained one.
                with self.assertRaises(work.ProcessRegistryOverflow):
                    lease.record_processes([dict(self.rows['exited'], pid=pid) for pid in range(2, 4100)])
                self.assertTrue(issubclass(work.ProcessRegistryOverflow, ValueError))
                lease.retire_processes([self.rows['live']])
                self.assertEqual(lease.record['processes'], [self.rows['live']])
                lease.close()
                with self.assertRaisesRegex(RuntimeError, 'no longer active'):
                    lease.retire_processes([self.rows['live']])



class LeaseModuleWiringTests(unittest.TestCase):
    """M4 regression (P0): NativeRun delegates lease recording and release to studio.native_run_lease."""

    def test_native_run_uses_the_lease_module(self) -> None:
        """Both lease methods call the R1 module exactly once with the owner."""
        owner = SimpleNamespace()
        with patch('studio.native_run.native_run_lease') as lease_module:
            NativeRun.record_lease_processes(owner)
            NativeRun.release_lease(owner)
        lease_module.record_lease_processes.assert_called_once_with(owner)
        lease_module.release_lease.assert_called_once_with(owner)

if __name__ == '__main__':
    unittest.main()
