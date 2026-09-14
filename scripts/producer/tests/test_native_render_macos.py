"""Public macOS sampler ABI and failure tests; every system API is mocked."""
from __future__ import annotations

import ctypes as c
import errno
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import native_render_macos as sampler
from native_render_measurements import DirectMeasurementError, parse_direct
from native_render_processes import MissingProcessFootprint
from studio.native_measurement_retry import MeasurementWindow
from test_native_measurement_retry import owner_fixture
from test_native_render_resources import REQUEST, direct_sample


def process_row(pid: int = 100) -> dict:
    """Return one synthetic live rusage observation with inclusive footprint."""
    return {'pid': pid, 'status': 'measured', 'footprintBytes': 214041128,
            'processStartAbstime': 1234, 'processExitAbstime': 0,
            'compressedBytes': None, 'compressedStatus': sampler.COMPRESSED_UNAVAILABLE,
            'footprintSource': 'proc_pid_rusage:RUSAGE_INFO_V0:ri_phys_footprint'}


def host_system(count: int = 38, result: int = 0) -> SimpleNamespace:
    """Fill the real ctypes destination using the public host-statistics signature."""
    def statistics(host: int, flavor: int, buffer: object, returned_count: object) -> int:
        if (host, flavor, c.cast(returned_count, c.POINTER(c.c_uint32))[0]) != (91, 4, 38):
            raise AssertionError('Wrong host port, flavor or initial integer count')
        vm = c.cast(buffer, c.POINTER(sampler.VMStatistics64)).contents
        vm.free_count, vm.speculative_count, vm.compressor_page_count = 200, 40, 10
        vm.total_uncompressed_pages_in_compressor = 900
        c.cast(returned_count, c.POINTER(c.c_uint32))[0] = count
        return result
    return SimpleNamespace(mach_host_self=Mock(return_value=91),
                           host_statistics64=Mock(side_effect=statistics))


class NativeRenderMacosTests(unittest.TestCase):
    """Use SDK-backed ABI invariants without loading host libraries or probing PIDs."""

    def test_installed_sdk_layout_and_supported_64_bit_hosts(self) -> None:
        """A kernel write needs the verified sizes, alignments and counter offsets."""
        layout = sampler.abi_layout()
        self.assertEqual((layout['RusageV0']['size'], layout['RusageV0']['alignment']), (96, 8))
        self.assertEqual(layout['RusageV0']['offsets']['ri_phys_footprint'], 72)
        self.assertEqual(layout['RusageV0']['offsets']['ri_proc_exit_abstime'], 88)
        self.assertEqual((layout['VMStatistics64']['size'], layout['VMStatistics64']['alignment']), (152, 8))
        self.assertEqual(layout['VMStatistics64']['offsets']['compressor_page_count'], 128)
        for machine in ('arm64', 'x86_64'):
            with self.subTest(machine=machine), patch.object(sampler.sys, 'platform', 'darwin'), \
                    patch.object(sampler.sys, 'byteorder', 'little'), \
                    patch.object(sampler.platform, 'machine', return_value=machine):
                sampler.validate_abi()

    def test_unsupported_platform_endianness_and_architecture_fail_before_binding(self) -> None:
        """An unsupported host must not load a library or permit a kernel write."""
        for system, byteorder, machine in [('linux', 'little', 'arm64'),
                                          ('darwin', 'big', 'arm64'), ('darwin', 'little', 'i386')]:
            with self.subTest(host=(system, byteorder, machine)), \
                    patch.object(sampler.sys, 'platform', system), \
                    patch.object(sampler.sys, 'byteorder', byteorder), \
                    patch.object(sampler.platform, 'machine', return_value=machine), \
                    patch.object(sampler, 'bindings') as bindings:
                with self.assertRaisesRegex(RuntimeError, 'ABI'):
                    sampler.collect([100])
                bindings.assert_not_called()

    def test_narrow_pointer_or_misaligned_rusage_layout_is_rejected(self) -> None:
        """Neither a 32-bit pointer ABI nor packed structures may reach the APIs."""
        original_sizeof = c.sizeof
        with patch.object(sampler.sys, 'platform', 'darwin'), \
                patch.object(sampler.platform, 'machine', return_value='arm64'), \
                patch.object(c, 'sizeof', side_effect=lambda item: 4 if item is c.c_size_t else original_sizeof(item)):
            with self.assertRaisesRegex(RuntimeError, 'ABI'):
                sampler.validate_abi()
        class PackedRusage(c.Structure):
            """Deliberately incompatible packing must fail the ABI fence."""
            _layout_ = 'ms'
            _pack_ = 1
            _fields_ = sampler.RusageV0._fields_
        with patch.object(sampler.sys, 'platform', 'darwin'), \
                patch.object(sampler.platform, 'machine', return_value='arm64'), \
                patch.object(sampler, 'RusageV0', PackedRusage):
            with self.assertRaisesRegex(RuntimeError, 'ABI'):
                sampler.validate_abi()

    def test_public_bindings_use_explicit_buffer_and_count_pointers(self) -> None:
        """ctypes must not truncate host handles or use an implicit rusage signature."""
        libproc = SimpleNamespace(proc_pid_rusage=Mock())
        system = SimpleNamespace(mach_host_self=Mock(), host_statistics64=Mock())
        with patch.object(c, 'CDLL', side_effect=[libproc, system]) as load:
            self.assertEqual(sampler.bindings(), (libproc, system))
        self.assertEqual(load.call_args_list, [call('/usr/lib/libproc.dylib', use_errno=True),
                                             call('/usr/lib/libSystem.B.dylib', use_errno=True)])
        self.assertEqual(libproc.proc_pid_rusage.argtypes, [c.c_int, c.c_int, c.c_void_p])
        self.assertEqual(system.host_statistics64.argtypes,
                         [c.c_uint32, c.c_int, c.c_void_p, c.POINTER(c.c_uint32)])
        self.assertIs(system.mach_host_self.restype, c.c_uint32)

    def test_host_uses_kernel_page_size_without_adding_speculative_pages(self) -> None:
        """Free pages already include speculative; compressor means physical pages."""
        for page_size in (4096, 16384):
            system = host_system()
            symbol = Mock(return_value=SimpleNamespace(value=page_size))
            with self.subTest(page_size=page_size), \
                    patch.object(c, 'c_size_t', SimpleNamespace(in_dll=symbol)):
                result = sampler.host_memory(system)
            symbol.assert_called_once_with(system, 'vm_kernel_page_size')
            self.assertEqual(result['unusedPhysicalBytes'], 200 * page_size)
            self.assertEqual(result['compressorBytes'], 10 * page_size)
            self.assertEqual(result['raw']['speculative_count'], 40)
            self.assertEqual(result['returnedIntegerCount'], 38)

    def test_host_rejects_incomplete_count_and_kernel_api_denial(self) -> None:
        """An API return or short structure is not a partial healthy sample."""
        for count, result in [(37, 0), (0, 0), (39, 0), (38, 5)]:
            with self.subTest(count=count, result=result), \
                    patch.object(c, 'c_size_t', SimpleNamespace(in_dll=Mock(return_value=SimpleNamespace(value=16384)))):
                with self.assertRaisesRegex(RuntimeError, 'Incomplete host'):
                    sampler.host_memory(host_system(count, result))

    def test_host_rejects_unknown_or_unavailable_kernel_page_size(self) -> None:
        """No user-page-size or guessed constant may replace the public data symbol."""
        for value in (0, 8192, 65536):
            with self.subTest(value=value), \
                    patch.object(c, 'c_size_t', SimpleNamespace(in_dll=Mock(return_value=SimpleNamespace(value=value)))):
                with self.assertRaises(RuntimeError):
                    sampler.host_memory(host_system())
        with patch.object(c, 'c_size_t', SimpleNamespace(in_dll=Mock(side_effect=ValueError('missing symbol')))):
            with self.assertRaisesRegex(ValueError, 'missing symbol'):
                sampler.host_memory(host_system())

    def test_process_uses_exact_physical_footprint_and_explicit_unavailable_compression(self) -> None:
        """A small resident count cannot replace inclusive phys_footprint."""
        def rusage(pid: int, version: int, buffer: object) -> int:
            self.assertEqual((pid, version), (100, 0))
            usage = c.cast(buffer, c.POINTER(sampler.RusageV0)).contents
            usage.ri_resident_size, usage.ri_phys_footprint = 4096, 214041128
            usage.ri_proc_start_abstime = 1234
            return 0
        result = sampler.process_memory(SimpleNamespace(proc_pid_rusage=Mock(side_effect=rusage)), 100)
        self.assertEqual(result, process_row())
        self.assertIsNone(result['compressedBytes'])

    def test_api_permission_denial_and_exited_pid_keep_errno_without_zero_footprint(self) -> None:
        """Both EPERM and ESRCH are unavailable readings, never zero-valued tasks."""
        for code in (errno.EPERM, errno.ESRCH):
            with self.subTest(errno=code), patch.object(c, 'get_errno', return_value=code):
                result = sampler.process_memory(SimpleNamespace(proc_pid_rusage=Mock(return_value=-1)), 100)
            self.assertEqual(result, {'pid': 100, 'status': 'unavailable', 'result': -1, 'errno': code})
            self.assertNotIn('footprintBytes', result)

    def test_process_start_change_zero_start_or_exit_cannot_be_measured(self) -> None:
        """The paired rusage reads must describe the same live kernel identity."""
        cases = [('processStartAbstime', 1235), ('processStartAbstime', 0), ('processExitAbstime', 1)]
        for field, value in cases:
            before, after = process_row(), process_row()
            after[field] = value
            result = sampler.consistent_process(before, after)
            with self.subTest(field=field, value=value):
                self.assertEqual(result['status'], 'unavailable')
                self.assertEqual(result['before'], before)
                self.assertEqual(result['after'], after)
                self.assertNotIn('footprintBytes', result)
        before = process_row() | {'processExitAbstime': 1}
        self.assertEqual(sampler.consistent_process(before, process_row())['status'], 'unavailable')

    def test_either_unavailable_observation_remains_unavailable(self) -> None:
        """A successful second call cannot erase an earlier denial or exit."""
        unavailable = {'pid': 100, 'status': 'unavailable', 'result': -1, 'errno': errno.ESRCH}
        for before, after in [(unavailable, process_row()), (process_row(), unavailable)]:
            result = sampler.consistent_process(before, after)
            self.assertEqual(result, {'pid': 100, 'status': 'unavailable', 'reason': 'rusage-api-failed',
                                     'before': before, 'after': after})

    def test_nested_api_failures_retry_only_proven_disappearance(self) -> None:
        """Actual paired helper rows retain terminal permission/unsupported failures."""
        raw = direct_sample()
        for code in (errno.ESRCH, errno.EPERM, errno.EACCES, 0, 95, 999):
            for side in ('before', 'after'):
                failed = {'pid': 100, 'status': 'unavailable', 'result': -1, 'errno': code}
                pair = (failed, process_row()) if side == 'before' else (process_row(), failed)
                value = json.loads(raw['direct'])
                value['processes'][0] = sampler.consistent_process(*pair)
                error = MissingProcessFootprint if code == errno.ESRCH else DirectMeasurementError
                with self.subTest(errno=code, side=side), self.assertRaises(error) as caught:
                    parse_direct(json.dumps(value), raw['ps'], REQUEST)
                evidence_key = 'directReadings' if code == errno.ESRCH else 'payload'
                self.assertEqual(caught.exception.evidence[evidence_key], value)

    def test_paired_identity_races_need_positive_matching_pid_evidence(self) -> None:
        """Real start/exit races retry; errorless or mismatched claims are malformed."""
        raw = direct_sample()
        cases = [('processStartAbstime', 1235, MissingProcessFootprint),
                 ('processExitAbstime', 1, MissingProcessFootprint),
                 ('processStartAbstime', 0, DirectMeasurementError),
                 ('pid', 101, DirectMeasurementError), ('processStartAbstime', 1234, DirectMeasurementError)]
        for field, changed, error in cases:
            before, after = process_row(), process_row() | {field: changed}
            value = json.loads(raw['direct'])
            value['processes'][0] = {'pid': 100, 'status': 'unavailable',
                'reason': 'rusage-identity-not-stable-and-live', 'before': before, 'after': after}
            with self.subTest(field=field, changed=changed), self.assertRaises(error):
                parse_direct(json.dumps(value), raw['ps'], REQUEST)

    def test_permission_parse_error_stops_owner_window_without_retry(self) -> None:
        """The real owner window must fail after one sample on per-task EPERM."""
        raw, owner = direct_sample(), owner_fixture()
        value = json.loads(raw['direct'])
        value['processes'][0] = sampler.consistent_process(process_row(),
            {'pid': 100, 'status': 'unavailable', 'result': -1, 'errno': errno.EPERM})
        with self.assertRaises(DirectMeasurementError) as caught:
            parse_direct(json.dumps(value), raw['ps'], REQUEST)
        with patch('studio.native_measurement_retry.read_snapshot', side_effect=caught.exception) as read:
            with self.assertRaises(DirectMeasurementError) as terminal:
                MeasurementWindow(owner, REQUEST).run()
        self.assertIs(terminal.exception, caught.exception)
        self.assertEqual(read.call_count, 1)
        self.assertEqual(owner.result.get('processExitMeasurementRetries', 0), 0)
        self.assertEqual(owner.result.get('commandTimeoutMeasurementRetries', 0), 0)

    def test_malformed_failure_evidence_cannot_select_disappearance_retry(self) -> None:
        """Mixed denial/disappearance and invalid return values remain terminal."""
        raw = direct_sample()
        failed = {'pid': 100, 'status': 'unavailable', 'errno': errno.ESRCH}
        invalid = [failed | {'result': result} for result in (None, 0, 1, True, -1.0)] + [failed]
        cases = invalid + [sampler.consistent_process(process_row(), row) for row in invalid]
        mixed = sampler.consistent_process(process_row(), failed | {'errno': errno.EPERM, 'result': -1})
        cases.append(mixed | {'errno': errno.ESRCH, 'result': -1})
        for index, row in enumerate(cases):
            value = json.loads(raw['direct'])
            value['processes'][0] = row
            with self.subTest(case=index), self.assertRaises(DirectMeasurementError) as caught:
                parse_direct(json.dumps(value), raw['ps'], REQUEST)
            self.assertEqual(caught.exception.evidence['payload'], value)

    def test_collect_brackets_host_read_with_all_requested_process_observations(self) -> None:
        """The second inclusive reading wins only after the first identity is retained."""
        order = []
        def process(_library: object, pid: int) -> dict:
            order.append(pid)
            return process_row(pid) | {'footprintBytes': len(order) * 4096}
        def host(_library: object) -> dict:
            order.append('host')
            return {'test': 'host'}
        with patch.object(sampler, 'validate_abi'), patch.object(sampler, 'bindings', return_value=('proc', 'sys')), \
                patch.object(sampler, 'process_memory', side_effect=process), \
                patch.object(sampler, 'host_memory', side_effect=host):
            result = sampler.collect([100, 101])
        self.assertEqual(order, [100, 101, 'host', 100, 101])
        self.assertEqual([row['footprintBytes'] for row in result['processes']], [16384, 20480])
        self.assertTrue(all(row['processStartAbstimeBefore'] == 1234 for row in result['processes']))

    def test_main_reports_unavailable_api_as_typed_json(self) -> None:
        """The owner receives provenance and an error, not an invented host sample."""
        stdout = io.StringIO()
        with patch.object(sampler.sys, 'argv', ['sampler', '100']), \
                patch.object(sampler, 'collect', side_effect=OSError('API denied')), \
                patch.object(sampler.time, 'monotonic', side_effect=[10, 10.25]), \
                patch('sys.stdout', stdout):
            sampler.main()
        result = json.loads(stdout.getvalue())
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['sampler'], sampler.SAMPLER)
        self.assertEqual(result['errorType'], 'OSError')
        self.assertEqual(result['elapsedSeconds'], .25)
        self.assertNotIn('host', result)

    def test_main_rejects_unbounded_duplicate_or_invalid_pid_arguments_before_collect(self) -> None:
        """The one-shot helper has bounded explicit ownership inputs."""
        cases = [['100', '100'], ['0'], ['1'], ['-5'], ['1.5'], ['True'],
                 [str(pid) for pid in range(2, 4099)]]
        for args in cases:
            with self.subTest(count=len(args), first=args[0]), \
                    patch.object(sampler.sys, 'argv', ['sampler', *args]), patch.object(sampler, 'collect') as collect:
                with self.assertRaises(ValueError):
                    sampler.main()
                collect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
