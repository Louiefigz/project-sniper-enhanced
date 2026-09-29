"""Honest task-local IO observations; fixtures do not establish service rates."""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import copy
import ctypes as c
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import native_proof_io as io
from native_work_service_cache import logical_bytes, physical_bytes


MEASURE_IN_CHILD = '''import json, sys
sys.path.insert(0, sys.argv[2])
import native_proof_io as io
pin = json.loads(sys.argv[1])
print(json.dumps([io.measure_read_pass([pin]), io.measure_read_pass([pin, pin])]))
'''


def measured_in_fresh_process(case: unittest.TestCase, pin: dict) -> list[dict]:
    """The first and repeated read passes, measured by a fresh single-threaded Python child.

    The collector refuses a process with more than one kernel thread. In a whole-suite process an
    earlier module can leave native threads behind (X126), so the real counters are read in a
    child that starts with none. The child inherits this process's environment, so the T0 child
    tripwire arms it and its report fails the run. It imports only native_proof_io (no owner).
    """
    producer = str(Path(io.__file__).resolve().parent)
    child = subprocess.run([sys.executable, '-B', '-c', MEASURE_IN_CHILD, json.dumps(pin), producer],
                           capture_output=True, text=True, timeout=60, check=False)
    case.assertEqual(child.returncode, 0, child.stderr)
    return json.loads(child.stdout)


def kernel_sample() -> dict:
    """Provide a clearly synthetic successful snapshot for refusal arithmetic."""
    return {'pid': os.getpid(), 'result': 0, 'errno': 0, 'status': 'measured',
            'absoluteTime': 10, 'processStart': 5, 'processExit': 0,
            'diskReadBytes': 100, 'diskWriteBytes': 200}


class ProofIOTests(unittest.TestCase):
    """Check input integrity and counter semantics without substituting host IO."""

    def setUp(self) -> None:
        """Create one explicitly bounded private test input."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.data = b'technical proof input only\n' * 128
        self.path = self.root / 'input.bin'
        self.path.write_bytes(self.data)
        self.pin = {'path': str(self.path), 'sha256': hashlib.sha256(self.data).hexdigest(),
                    'bytes': len(self.data)}
        self.identity = {'pid': os.getpid(), 'pgid': os.getpgrp(), 'started': 'TEST owned identity'}
        self.bsd = {'status': 'measured', 'parentPid': os.getppid(), 'identity': self.identity}

    def mocked_pass(self, inputs: list[dict]) -> dict:
        """Run real bounded reads with explicitly synthetic counter boundaries."""
        before = kernel_sample()
        after = before | {'absoluteTime': 20}
        with patch.object(io, 'bindings', return_value=object()), \
                patch.object(io, 'topology', return_value={'accepted': True}), \
                patch.object(io, 'process_identity', return_value=self.bsd), \
                patch.object(io, 'snapshot', side_effect=[before, after]):
            return io.measure_read_pass(inputs)

    def test_repeated_reads_count_actual_returned_bytes_and_zero_is_observed(self) -> None:
        """Repeated proof work is not collapsed to unique working-set size."""
        value = self.mocked_pass([self.pin, self.pin])
        identity = self.identity
        observation = io.cache_pass(value, identity)
        self.assertEqual(value['status'], 'measured')
        self.assertEqual(logical_bytes(observation['logicalReads'], [self.pin]), 2 * len(self.data))
        self.assertEqual(physical_bytes(observation['kernelSamples'], [identity]), 0)

    def test_read_failure_preserves_raw_brackets_without_success(self) -> None:
        """Wrong digests preserve observed reads but cannot become cache evidence."""
        value = self.mocked_pass([self.pin | {'sha256': 'a' * 64}])
        self.assertEqual(value['status'], 'failed')
        self.assertEqual(value['logicalReads'][0]['returnedBytes'], len(self.data))
        self.assertIsNotNone(value['after'])
        with self.assertRaisesRegex(RuntimeError, 'Failed proof'):
            io.cache_pass(value, {'pid': os.getpid()})

    def test_symlink_and_file_growth_refuse(self) -> None:
        """Existing no-follow and declared-size bounds stay active inside measurement."""
        linked = self.root / 'linked.bin'
        linked.symlink_to(self.path)
        self.assertEqual(self.mocked_pass([self.pin | {'path': str(linked)}])['status'], 'failed')
        self.path.write_bytes(self.data + b'excess')
        self.assertEqual(self.mocked_pass([self.pin])['status'], 'failed')

    def test_bounds_refuse_before_bindings_or_reads(self) -> None:
        """Unknown or unbounded declarations never reach the measured operation."""
        invalid = [[], [self.pin] * 129, [self.pin | {'bytes': True}],
                   [self.pin | {'bytes': io.MAX_JSON + 1}], [self.pin | {'extra': 1}]]
        with patch.object(io, 'bindings') as library:
            for rows in invalid:
                self.assert_invalid(rows)
        library.assert_not_called()

    def assert_invalid(self, rows: list[dict]) -> None:
        """Assert declaration refusal independently of the outer no-IO guard."""
        with self.assertRaises(ValueError):
            io.measure_read_pass(rows)

    def test_raw_failed_api_does_not_expose_initialized_zero_counters(self) -> None:
        """Preserve actual nonzero return and errno separately from unavailable fields."""
        library = Mock()
        library.proc_pid_rusage.side_effect = self.failed_rusage
        value = io.snapshot(library, os.getpid())
        self.assertEqual((value['result'], value['errno']), (-1, 1))
        self.assertEqual(value['status'], 'unavailable')
        self.assertIsNone(value['diskReadBytes'])
        self.assertIsNone(value['diskWriteBytes'])
        self.assertIsNone(value['processStart'])

    def failed_rusage(self, pid: int, flavor: int, buffer: object) -> int:
        """Model a documented API refusal without pretending it returned counters."""
        self.assertEqual((pid, flavor), (os.getpid(), 2))
        c.set_errno(1)
        return -1

    def test_unsupported_binding_retains_unavailable_state(self) -> None:
        """Unsupported platforms do not synthesize counters or logical work."""
        with patch.object(io, 'bindings', side_effect=RuntimeError('unsupported')), \
                patch.object(io, 'read_inputs') as read:
            value = io.measure_read_pass([self.pin])
        read.assert_not_called()
        self.assertEqual(value['reason'], 'kernel-binding-unavailable')
        self.assertEqual(io.cache_pass(value, {'pid': os.getpid()}),
                         {'logicalReads': None, 'kernelSamples': None})

    def test_unavailable_api_preserves_actual_logical_reads(self) -> None:
        """A failed kernel call cannot turn initialized counters into zero observations."""
        before = kernel_sample() | {'status': 'unavailable', 'result': -1, 'errno': 1,
                                    'diskReadBytes': None, 'diskWriteBytes': None}
        with patch.object(io, 'bindings', return_value=object()), \
                patch.object(io, 'topology', return_value={'accepted': True}), \
                patch.object(io, 'process_identity', return_value=self.bsd), \
                patch.object(io, 'snapshot', side_effect=[before, kernel_sample()]):
            value = io.measure_read_pass([self.pin])
        observation = io.cache_pass(value, {'pid': os.getpid()})
        self.assertEqual(value['reason'], 'kernel-counter-unavailable')
        self.assertEqual(value['before']['errno'], 1)
        self.assertEqual(logical_bytes(observation['logicalReads'], [self.pin]), len(self.data))
        self.assertIsNone(observation['kernelSamples'])

    def test_topology_refuses_reads_or_invalidates_completed_pass(self) -> None:
        """Extra threads, children, or unavailable topology cannot claim process coverage."""
        with patch.object(io, 'bindings', return_value=object()), \
                patch.object(io, 'topology', return_value={'accepted': False}), \
                patch.object(io, 'read_inputs') as read:
            value = io.measure_read_pass([self.pin])
        read.assert_not_called()
        self.assertEqual(value['reason'], 'requires-one-thread-and-no-children')
        with patch.object(io, 'bindings', return_value=object()), \
                patch.object(io, 'topology', side_effect=[{'accepted': True}, {'accepted': False}]), \
                patch.object(io, 'process_identity', return_value=self.bsd), \
                patch.object(io, 'snapshot', side_effect=[kernel_sample(), kernel_sample() | {'absoluteTime': 20}]):
            changed = io.measure_read_pass([self.pin])
        self.assertIsNone(io.cache_pass(changed, {'pid': os.getpid()})['kernelSamples'])

    def test_identity_exit_clock_and_counter_rollback_refuse(self) -> None:
        """Every process and clock dimension must agree across the actual bracket."""
        before = kernel_sample()
        after = before | {'absoluteTime': 20}
        for changed in ({'pid': 1}, {'processStart': 6}, {'processExit': 1},
                        {'absoluteTime': 10}, {'diskReadBytes': 99}, {'diskWriteBytes': 199}):
            self.assertIsNotNone(io.counter_reason(before, after | changed))
        value = self.mocked_pass([self.pin])
        with self.assertRaises(ValueError):
            io.cache_pass(value, {'pid': os.getpid() + 1})
        bad = copy.deepcopy(value)
        bad['after']['processStart'] += 1
        with self.assertRaises(ValueError):
            io.cache_pass(bad, {'pid': os.getpid()})

    def test_pid_alone_or_changed_bsd_start_cannot_bind_owner(self) -> None:
        """Bridge actual BSD owner identity and Mach start without converting clocks."""
        value = self.mocked_pass([self.pin])
        for identity in ({'pid': os.getpid()}, self.identity | {'started': 'another start'},
                         self.identity | {'pgid': os.getpgrp() + 1}):
            self.assert_invalid_identity(value, identity)
        bad = copy.deepcopy(value)
        bad['identityAfter']['identity']['started'] = 'later process'
        self.assert_invalid_identity(bad, self.identity)
        with patch.object(io, 'process_row', side_effect=RuntimeError('identity unavailable')):
            self.assertEqual(io.process_identity(object(), os.getpid())['status'], 'unavailable')

    def assert_invalid_identity(self, value: dict, identity: dict) -> None:
        """Refuse an unbound supplied registry row in the cold cache adapter."""
        with self.assertRaises(ValueError):
            io.cache_pass(value, identity)

    @unittest.skipUnless(sys.platform == 'darwin', 'macOS public libproc ABI only')
    def test_sdk_layout_matches_ctypes_independently(self) -> None:
        """Compile SDK headers separately; never accept a self-consistent wrong layout."""
        source = self.root / 'layout.c'
        binary = self.root / 'layout'
        source.write_text('#include <stdio.h>\n#include <stddef.h>\n#include <sys/resource.h>\n'
            '#include <sys/proc_info.h>\nint main(void) {\n'
            'printf("%zu %zu %zu %zu %zu %zu %zu %zu\\n", sizeof(struct rusage_info_v2), '
            '_Alignof(struct rusage_info_v2), offsetof(struct rusage_info_v2,ri_diskio_bytesread), '
            'offsetof(struct rusage_info_v2,ri_diskio_byteswritten), '
            'offsetof(struct rusage_info_v2,ri_proc_start_abstime), '
            'offsetof(struct rusage_info_v2,ri_proc_exit_abstime), '
            'sizeof(struct proc_taskinfo), offsetof(struct proc_taskinfo,pti_threadnum)); return 0; }\n')
        subprocess.run(['/usr/bin/clang', '-std=c11', str(source), '-o', str(binary)],
                       check=True, capture_output=True, timeout=30)
        actual = subprocess.run([str(binary)], check=True, capture_output=True, text=True, timeout=5)
        expected = [c.sizeof(io.RusageV2), c.alignment(io.RusageV2), io.RusageV2.ri_diskio_bytesread.offset,
                    io.RusageV2.ri_diskio_byteswritten.offset, io.RusageV2.ri_proc_start_abstime.offset,
                    io.RusageV2.ri_proc_exit_abstime.offset, c.sizeof(io.TaskInfo), io.TaskInfo.pti_threadnum.offset]
        self.assertEqual([int(value) for value in actual.stdout.split()], expected)

    @unittest.skipUnless(sys.platform == 'darwin', 'macOS public libproc counters only')
    def test_actual_small_local_first_and_repeated_reads(self) -> None:
        """Exercise real kernel counters without assuming cold IO or positive deltas."""
        first, second = measured_in_fresh_process(self, self.pin)
        self.assertEqual(first['status'], 'measured', json.dumps(first))
        self.assertEqual(second['status'], 'measured', json.dumps(second))
        self.assertEqual(first['before']['processStart'], second['after']['processStart'])
        actual_identity = first['identityBefore']['identity']
        self.assertEqual(first['identityAfter']['identity'], actual_identity)
        self.assertIsNotNone(io.cache_pass(first, actual_identity)['kernelSamples'])
        self.assertEqual(first['topologyBefore']['threadCount'], 1)
        self.assertEqual(second['topologyAfter']['childResult'], 0)
        self.assertEqual(sum(row['returnedBytes'] for row in second['logicalReads']), len(self.data) * 2)
        for value in (first, second):
            self.assertGreater(value['after']['absoluteTime'], value['before']['absoluteTime'])
            self.assertGreaterEqual(value['after']['diskReadBytes'], value['before']['diskReadBytes'])
            self.assertGreaterEqual(value['after']['diskWriteBytes'], value['before']['diskWriteBytes'])

    @unittest.skipUnless(sys.platform == 'darwin', 'macOS public libproc topology only')
    def test_actual_extra_thread_and_child_refuse(self) -> None:
        """Real kernel topology checks reject live siblings before reading any file."""
        release = threading.Event()
        thread = threading.Thread(target=release.wait)
        thread.start()
        try:
            threaded = io.measure_read_pass([self.pin])
        finally:
            release.set()
            thread.join(timeout=5)
        self.assertEqual(threaded['reason'], 'requires-one-thread-and-no-children')
        self.assertGreater(threaded['topologyBefore']['threadCount'], 1)
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        try:
            parented = io.measure_read_pass([self.pin])
        finally:
            child.terminate()
            child.wait(timeout=5)
        self.assertEqual(parented['reason'], 'requires-one-thread-and-no-children')
        self.assertGreater(parented['topologyBefore']['childResult'], 0)
        self.assertEqual(parented['logicalReads'], [])


if __name__ == '__main__':
    unittest.main()
