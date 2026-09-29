"""An exited owned process's PID may be recycled by any host process during a long owner.

F0 spike: a ten-window owner (424 s, load 17-157) stopped with "owned root start
identity was not bound" because two of its 189 exited identities' PIDs were reused by
unrelated processes. A retired identity is not a violation; a live identity change is.
"""
from __future__ import annotations

import ctypes as c
import errno
import json
import os
import signal
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import native_render_process_table as table_reader
from native_render_processes import ProcessIdentity, ProcessRequest, ResourceMeasurementError, process_selection
from native_render_resources import GIB, parse_snapshot, stop_reasons
from studio.native_owned_processes import OwnedProcess, OwnedRegistry
from studio.native_run import NativeRun
from studio.native_run_config import NativeRunConfig
from studio.native_runtime import digest
from test_native_render_policy import policy_snapshot
from test_native_render_resources import START, direct_sample, raw_sample
from _native_pool_fixture import pool_lease_double

LATER = 'Sun Sep 27 18:23:15 2026'  # A start after START: the PID was reassigned.
ROOT = ProcessIdentity(100, START, 100)
EXITED = ProcessIdentity(101, START, 101)
LIVE = f'100 1 100 {START}\n500 1 500 {START}\n'


def snapshot(ps: str, top: str, request: ProcessRequest):
    """Parse one complete reading through the shared selection authority."""
    return parse_snapshot(raw_sample() | {'ps': ps, 'top': top}, request, 40 * GIB)


class RetiredIdentityTests(unittest.TestCase):
    """Table-level classification; the root keeps its strict identity check."""

    def test_exited_child_pid_held_by_an_unrelated_process_is_retired(self) -> None:
        """The spike's failure: 189 exited identities, two PIDs reused by other processes."""
        exited = tuple(ProcessIdentity(pid, START, pid) for pid in range(200, 389))
        recycled = (ProcessIdentity(31460, START, 31425), ProcessIdentity(31462, START, 31425))
        foreign = f'31460 1 31460 {LATER}\n31462 31460 31460 {LATER}\n'
        request = ProcessRequest(ROOT, (ROOT,) + exited + recycled)
        result = snapshot(LIVE + foreign, 'PhysMem: 2G compressor, 34G unused.\n100 2G 0B\n', request)
        self.assertEqual((result.owned_pids, result.owned_footprint_bytes), ((100,), 2 * GIB))
        self.assertEqual(result.recycled_registered_pids, (31460, 31462))
        self.assertEqual((len(result.missing_registered_pids), result.reused_registered_pids), (189, ()))
        self.assertTrue(result.identity_verified)
        self.assertEqual(stop_reasons(result, result), ())

    def test_new_child_of_an_owned_process_at_a_retired_pid_is_owned(self) -> None:
        """Ancestry, not the old record, owns a new process that reuses an owned PID."""
        ps = LIVE + f'101 100 100 {LATER}\n'
        result = snapshot(ps, 'PhysMem: 2G compressor, 34G unused.\n100 2G 0B\n101 1G 0B\n',
                          ProcessRequest(ROOT, (EXITED,)))
        self.assertEqual((result.owned_pids, result.recycled_registered_pids), ((100, 101), (101,)))
        self.assertEqual(result.processes[1].started, LATER)
        self.assertTrue(result.identity_verified)

    def test_unrelated_holder_never_anchors_its_own_children(self) -> None:
        """A foreign process at a retired PID and its descendants stay unowned."""
        ps = LIVE + f'101 1 101 {LATER}\n102 101 101 {LATER}\n'
        selected = process_selection(ps, ProcessRequest(ROOT, (EXITED,)))
        self.assertEqual((selected['owned'], selected['recycled']), ({100}, (101,)))

    def test_live_identity_changes_and_root_changes_still_stop(self) -> None:
        """Same PID and start in another group, a changed root and an unbound root fail."""
        regrouped = snapshot(LIVE + f'101 1 999 {START}\n', 'PhysMem: 2G compressor, 34G unused.\n100 2G 0B\n',
                             ProcessRequest(ROOT, (EXITED,)))
        root = snapshot(f'100 1 100 {LATER}\n', 'PhysMem: 2G compressor, 34G unused.\n',
                        ProcessRequest(ROOT, (ROOT,)))
        unbound = snapshot(LIVE, 'PhysMem: 2G compressor, 34G unused.\n100 2G 0B\n',
                           ProcessRequest(ProcessIdentity(100)))
        for result, reused in ((regrouped, (101,)), (root, (100,)), (unbound, ())):
            with self.subTest(reused=reused):
                self.assertEqual((result.reused_registered_pids, result.identity_verified), (reused, False))
                self.assertIn('owned root start identity was not bound', stop_reasons(result, result))
        self.assertEqual(root.recycled_registered_pids, ())  # A root row is judged as the root, never retired.


class OtherUserHolderTests(unittest.TestCase):
    """libproc refuses another user's process; kinfo_proc decides by kernel start."""

    def library(self, denied: dict[int, int], exited: set[int] = frozenset()) -> SimpleNamespace:
        """Fake libproc/sysctl: ``denied`` maps an EPERM PID to its kinfo start second."""
        def pidinfo(pid: int, _flavor: int, _arg: int, pointer: object, *_size: int) -> int:
            """proc_pidinfo: EPERM for ``denied``; otherwise a same-user row started at START."""
            if pid in denied:
                c.set_errno(errno.EPERM)
                return 0
            value = c.cast(pointer, c.POINTER(table_reader.BsdInfo)).contents
            value.pid, value.ppid, value.pgid, value.status = pid, 1, pid, 2
            value.start_seconds = int(time.mktime(time.strptime(START, '%a %b %d %H:%M:%S %Y')))
            return c.sizeof(table_reader.BsdInfo)

        def sysctl(name: object, _count: int, pointer: object, size: object, *_new: object) -> int:
            """KERN_PROC_PID: no row for ``exited``; otherwise the denied PID's kinfo_proc."""
            pid = c.cast(name, c.POINTER(c.c_int))[3]
            if pid in exited:
                c.cast(size, c.POINTER(c.c_size_t)).contents.value = 0
                return 0
            value = c.cast(pointer, c.POINTER(table_reader.KinfoProc)).contents
            value.pid, value.ppid, value.pgid, value.state, value.start_seconds = pid, 1, pid, 2, denied[pid]
            return 0
        return SimpleNamespace(proc_pidinfo=pidinfo, proc_listchildpids=lambda *_: 0, sysctl=sysctl)

    def read(self, library: SimpleNamespace, request: ProcessRequest) -> dict:
        """Run the real identity table and shared selection over the fake kernel."""
        with patch.object(table_reader, 'process_bindings', return_value=library), \
                patch.object(table_reader.os, 'getpid', return_value=999):
            return process_selection(table_reader.identity_table(request), request)

    def test_recorded_pid_held_by_another_user_is_retired_not_terminal(self) -> None:
        """A root daemon at an exited owned PID is foreign; the helper keeps measuring."""
        later = int(time.mktime(time.strptime(LATER, '%a %b %d %H:%M:%S %Y')))
        selected = self.read(self.library({101: later}), ProcessRequest(ROOT, (ROOT, EXITED)))
        self.assertEqual((selected['owned'], selected['recycled'], selected['verified']), ({100}, (101,), True))
        exited = self.read(self.library({101: later}, {101}), ProcessRequest(ROOT, (ROOT, EXITED)))
        self.assertEqual((exited['missing'], exited['recycled']), ((101,), ()))

    def test_refused_read_of_the_recorded_process_itself_fails_closed(self) -> None:
        """Same kernel start, an unbound identity or a refused root is never guessed foreign."""
        same = int(time.mktime(time.strptime(START, '%a %b %d %H:%M:%S %Y')))
        for request in (ProcessRequest(ROOT, (EXITED,)), ProcessRequest(ROOT, (ProcessIdentity(101),))):
            with self.subTest(request=request), self.assertRaises(ResourceMeasurementError):
                self.read(self.library({101: same}), request)
        with self.assertRaises(table_reader.ProcessInfoDenied):
            self.read(self.library({100: same + 60}), ProcessRequest(ROOT, (ROOT,)))

    def test_kinfo_layout_and_live_read_match_libproc(self) -> None:
        """The declaration keeps the clang offsetof layout; bindings refuse a disagreeing read."""
        self.assertEqual(table_reader.kinfo_layout(), (648, 0, 36, 40, 560, 564))
        library = table_reader.process_bindings()  # Runs the live self-row check.
        self.assertEqual(table_reader.public_row(library, os.getpid()),
                         table_reader.process_row(library, os.getpid()))
        row = table_reader.process_row(library, os.getpid())
        with patch.object(table_reader, 'public_row', return_value=(row[0], row[1], LATER)), \
                self.assertRaisesRegex(ResourceMeasurementError, 'kinfo_proc and libproc disagree'):
            table_reader.process_bindings()


class OwnerRecyclingTests(unittest.TestCase):
    """Drive NativeRun.sample through the real sampler parse, registry and adaptive guard."""

    def setUp(self) -> None:
        """Admit a TEST owner without a lease, launch or signal."""
        root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        project, output = root / 'project', root / 'output'
        project.mkdir(); output.mkdir()
        cli, sandbox = root / 'cli.js', root / 'sandbox.sb'
        cli.write_text('TEST executable'); sandbox.write_text('TEST sandbox')
        settings = NativeRunConfig(project, output, cli, ['TEST-NO-LAUNCH'], {},
            {'output': str(output / 'result.bin'), 'sdkSha256': digest(cli), 'sandboxSha256': digest(sandbox)},
            sandbox=sandbox)
        self.enterContext(patch('studio.native_run.NativeWorkLease.acquire', return_value=pool_lease_double()))
        self.enterContext(patch('studio.native_owned_processes.os.kill', side_effect=AssertionError('no signal')))
        self.enterContext(patch('builtins.print'))
        self.owner = NativeRun('TEST', settings)
        self.addCleanup(self.close_owner)
        with patch.object(self.owner, 'measure_resources',
                          return_value=replace(policy_snapshot(), measured_at=time.time() - 20)):
            self.owner.prepare()
        self.owner.child = Mock(pid=100)
        self.owner.child.poll.return_value = None
        self.owner.registry = OwnedRegistry.__new__(OwnedRegistry)
        self.owner.registry.root_pid, self.owner.registry.groups, self.owner.registry.signal_events = 100, {100}, []
        self.owner.registry.known = {100: OwnedProcess(100, os.getpid(), 100, START),
                                     101: OwnedProcess(101, 100, 101, START)}

    def close_owner(self) -> None:
        """Release TEST files and handlers; the real registry never signals here."""
        self.owner.result['cleanup'] = {'verified': True, 'TEST': 'no process was launched'}
        self.owner.release_lease()
        for handle in (self.owner.log, self.owner.samples):
            if handle is not None:
                handle.close()
        self.owner.signal_handlers.restore()

    def sample(self, registry_rows: dict, sampled: str, top: str) -> dict:
        """Run one owner sample; the registry and the sampler each see their own table."""
        raw = direct_sample(raw_sample() | {'ps': sampled, 'top': top})
        envelope = {'before': sampled, 'after': sampled, 'direct': json.loads(raw['direct'])}
        rows = {pid: OwnedProcess(pid, *row) for pid, row in registry_rows.items()}
        with patch('studio.native_owned_processes.read_processes', return_value=rows), \
                patch('native_render_sampling.shutil.disk_usage', return_value=SimpleNamespace(free=40 * GIB)), \
                patch('native_render_sampling._read_command',
                      side_effect=[raw['sysctl'], raw['pressure'], json.dumps(envelope)]):
            self.owner.sample()
        return json.loads(self.owner.path.read_text())

    def test_owner_keeps_running_when_an_exited_childs_pid_is_recycled(self) -> None:
        """The F0 stop: a recycled PID of an exited child no longer aborts a healthy owner."""
        receipt = self.sample({100: (1, 100, START), 101: (1, 101, LATER)},
                              f'100 1 100 {START}\n101 1 101 {LATER}\n', '100 2G 0B\n101 9G 0B\n')
        self.assertIsNone(self.owner.abort_reason)
        latest = receipt['latestResourceSnapshot']
        self.assertEqual((latest['owned_pids'], latest['recycled_registered_pids']), ([100], [101]))
        self.assertEqual(receipt['resourcePolicyEvaluation']['stopReasons'], [])
        self.assertNotIn(101, self.owner.registry.known)  # Retired after the verified sample.
        self.assertEqual(receipt['identityRetirement']['registry'], 1)

    def test_owner_adopts_a_new_child_that_reuses_a_retired_pid(self) -> None:
        """A child born after the registry's last read replaces the retired record."""
        receipt = self.sample({100: (1, 100, START)}, f'100 1 100 {START}\n101 100 100 {LATER}\n',
                              '100 2G 0B\n101 1G 0B\n')
        self.assertIsNone(self.owner.abort_reason)
        self.assertEqual(receipt['latestResourceSnapshot']['owned_pids'], [100, 101])
        self.assertIn({'pid': 101, 'parent_pid': 100, 'pgid': 100, 'started': LATER}, receipt['ownerIdentities'])

    def test_owner_still_stops_when_a_live_identity_changes(self) -> None:
        """A recorded live process seen in another group is the unchanged violation."""
        self.sample({100: (1, 100, START), 101: (1, 101, START)},
                    f'100 1 100 {START}\n101 1 999 {START}\n', '100 2G 0B\n101 1G 0B\n')
        self.assertEqual(self.owner.abort_reason, 'owned root start identity was not bound')

    def test_registry_refuses_a_measured_group_change_but_retires_an_exit(self) -> None:
        """remember_measured: another start retires the record; another group is refused."""
        registry = self.owner.registry
        registry.remember_measured((SimpleNamespace(pid=101, parent_pid=100, pgid=100, started=LATER),))
        self.assertEqual(registry.known[101], OwnedProcess(101, 100, 100, LATER))
        with self.assertRaisesRegex(RuntimeError, 'conflicts with recorded cleanup identity'):
            registry.remember_measured((SimpleNamespace(pid=101, parent_pid=100, pgid=555, started=LATER),))
        with patch('studio.native_owned_processes.read_processes',
                   return_value={100: OwnedProcess(100, 1, 100, START), 101: OwnedProcess(101, 1, 101, 'NEWER')}), \
                patch('studio.native_owned_processes.os.kill') as kill:
            registry.signal_owned(signal.SIGINT)
        self.assertEqual([call.args[0] for call in kill.call_args_list], [-100])


if __name__ == '__main__':
    unittest.main()
