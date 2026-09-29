"""Public macOS sampler ABI and failure tests; every system API is mocked."""
from __future__ import annotations

import ctypes as c
import errno
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused
import native_render_macos as sampler
from native_render_measurements import DirectMeasurementError, parse_direct
from native_render_processes import MissingProcessFootprint
from studio.native_measurement_retry import MeasurementWindow
from test_native_measurement_retry import owner_fixture
from test_native_render_resources import REQUEST, direct_sample


def process_row(pid: int = 100) -> dict:
    """Return one synthetic live rusage observation with inclusive footprint."""
    return {'pid': pid, 'status': 'measured', 'footprintBytes': 214041128,
            'userTimeAbstime': 7200, 'systemTimeAbstime': 2400,
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


def processor_system(values: list[int], count: int = 2, size: int = 8, result: int = 0) -> SimpleNamespace:
    """Fill host_processor_info's out-of-line array exactly as the kernel's MIG reply does."""
    array = (c.c_int32 * len(values))(*values)
    def info(host: int, flavor: int, processors: object, pointer: object, integers: object) -> int:
        if (host, flavor) != (91, sampler.PROCESSOR_CPU_LOAD_INFO):
            raise AssertionError('Wrong host port or processor flavor')
        c.cast(processors, c.POINTER(c.c_uint32))[0] = count
        c.cast(pointer, c.POINTER(c.POINTER(c.c_int32)))[0] = c.cast(array, c.POINTER(c.c_int32))
        c.cast(integers, c.POINTER(c.c_uint32))[0] = size
        return result
    return SimpleNamespace(mach_host_self=Mock(return_value=91), host_processor_info=Mock(side_effect=info),
                           vm_deallocate=Mock(return_value=0), array=array)


def translation(value: int, result: int = 0, code: int = 0) -> Mock:
    """sysctlbyname('sysctl.proc_translated'): 0 natively, 1 under Rosetta, or a failure."""
    def sysctl(name: bytes, pointer: object, _size: object, _new: object, _length: int) -> int:
        if name != b'sysctl.proc_translated':
            raise AssertionError(f'Unexpected sysctl {name!r}')
        c.cast(pointer, c.POINTER(c.c_int))[0] = value
        c.set_errno(code)
        return result
    return Mock(side_effect=sysctl)


def cpu_system(values: list[int], numer: int = 125, read: int = 1000) -> SimpleNamespace:
    """A native (untranslated) host with a 125/3 timebase and the given processor ticks."""
    system = processor_system(values)
    def timebase(pointer: object) -> int:
        target = c.cast(pointer, c.POINTER(sampler.MachTimebase)).contents
        target.numer, target.denom = numer, 3
        return 0
    system.mach_timebase_info = Mock(side_effect=timebase)
    system.mach_absolute_time = Mock(return_value=read)
    system.sysctlbyname = translation(0)
    return system


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
            usage.ri_user_time, usage.ri_system_time = 7200, 2400
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


    def test_rusage_cpu_is_raw_mach_ticks_and_v0_has_no_child_totals(self) -> None:
        """Each process reports only its own CPU, so descendants are never counted twice."""
        names = [name for name, _ in sampler.RusageV0._fields_]
        self.assertFalse([name for name in names if 'child' in name])
        self.assertEqual(sampler.abi_layout()['RusageV0']['offsets']['ri_user_time'], 16)
        self.assertEqual(process_row()['userTimeAbstime'], 7200)  # Mach ticks, never nanoseconds

    def test_processor_ticks_copy_natural_t_counters_and_release_the_kernel_array(self) -> None:
        """Signed integer_t storage is read as unsigned ticks; the MIG array is freed."""
        system = processor_system([10, 20, 30, 0, -1, 5, 6, 7])
        rows = sampler.processor_ticks(system, 7)
        self.assertEqual(rows, [[10, 20, 30, 0], [2 ** 32 - 1, 5, 6, 7]])
        system.vm_deallocate.assert_called_once_with(7, c.addressof(system.array), 32)

    def test_incomplete_processor_arrays_fail_and_are_still_released(self) -> None:
        """A short or oversized reply is refused; only a failed call has nothing to free."""
        for count, size in [(2, 7), (0, 0), (sampler.MAXIMUM_PROCESSORS + 1, 8)]:
            system = processor_system([1] * 8, count, size)
            with self.subTest(count=count, size=size), self.assertRaisesRegex(RuntimeError, 'Incomplete'):
                sampler.processor_ticks(system, 7)
            system.vm_deallocate.assert_called_once()
        failed = processor_system([1] * 8, result=5)
        with self.assertRaisesRegex(RuntimeError, 'host_processor_info failed'):
            sampler.processor_ticks(failed, 7)
        failed.vm_deallocate.assert_not_called()
        leaked = processor_system([1] * 8)
        leaked.vm_deallocate.return_value = 4
        with self.assertRaisesRegex(RuntimeError, 'not released'):
            sampler.processor_ticks(leaked, 7)

    def test_cpu_bindings_declare_clock_processor_and_translation_signatures(self) -> None:
        """Out-of-line pointers, 64-bit clocks and the sysctl probe need explicit signatures."""
        system = SimpleNamespace(mach_absolute_time=Mock(), mach_timebase_info=Mock(),
                                 host_processor_info=Mock(), vm_deallocate=Mock(), sysctlbyname=Mock())
        with patch.object(c.c_uint32, 'in_dll', return_value=SimpleNamespace(value=259), create=True) as task:
            self.assertEqual(sampler.cpu_bindings(system), 259)
        task.assert_called_once_with(system, 'mach_task_self_')
        self.assertIs(system.mach_absolute_time.restype, c.c_uint64)
        self.assertEqual(system.host_processor_info.argtypes[3], c.POINTER(c.POINTER(c.c_int32)))
        self.assertEqual(system.vm_deallocate.argtypes, [c.c_uint32, c.c_size_t, c.c_size_t])
        self.assertEqual(system.sysctlbyname.argtypes[:3], [c.c_char_p, c.c_void_p, c.POINTER(c.c_size_t)])

    def test_host_cpu_reads_timebase_ticks_then_clock(self) -> None:
        """The Mach read time follows the copied ticks; SC_CLK_TCK is recorded, not assumed."""
        system = cpu_system([10, 20, 30, 0, 1, 2, 3, 4])
        system.mach_absolute_time = Mock(side_effect=lambda: system.vm_deallocate.call_count * 1000)
        with patch.object(sampler, 'cpu_bindings', return_value=7), \
                patch.object(sampler.os, 'sysconf', return_value=100) as clock:
            result = sampler.host_cpu(system)
        clock.assert_called_once_with('SC_CLK_TCK')
        self.assertEqual(result, {'status': 'measured', 'source': sampler.CPU_SOURCE, 'readAbstime': 1000,
                                  'timebase': {'numer': 125, 'denom': 3}, 'clockTicksPerSecond': 100,
                                  'processorTicks': [[10, 20, 30, 0], [1, 2, 3, 4]]})
        self.assertIsNone(sampler.cpu_problem(result))

    def test_rosetta_translation_reports_cpu_unavailable(self) -> None:
        """Translated Mach time is nanoseconds while rusage stays native ticks: never measured."""
        cases = [(translation(1), 'Rosetta translation'), (translation(0, -1, errno.EPERM), 'errno=1'),
                 (translation(7), 'Unexpected Rosetta')]
        for probe, message in cases:
            system = cpu_system([1] * 8)
            system.sysctlbyname = probe
            with self.subTest(message=message), patch.object(sampler, 'cpu_bindings', return_value=7), \
                    patch.object(sampler.os, 'sysconf', return_value=100):
                result = sampler.host_cpu(system)
            self.assertEqual(result['status'], 'unavailable')
            self.assertIn(message, result['error'])
            system.host_processor_info.assert_not_called()
        native = cpu_system([1] * 8)
        native.sysctlbyname = translation(0, -1, errno.ENOENT)  # Hosts without translation lack the sysctl.
        with patch.object(sampler, 'cpu_bindings', return_value=7), patch.object(sampler.os, 'sysconf', return_value=100):
            self.assertEqual(sampler.host_cpu(native)['status'], 'measured')

    def test_helper_reports_every_invalid_cpu_value_as_unavailable(self) -> None:
        """The helper applies the parser's rule, so a CPU defect never reaches strict parsing."""
        cases = [('timebase', cpu_system([1] * 8, numer=0), 100), ('tick rate', cpu_system([1] * 8), -1),
                 ('tick rate', cpu_system([1] * 8), 0), ('read time', cpu_system([1] * 8, read=0), 100)]
        for problem, system, clock in cases:
            with self.subTest(problem=problem, clock=clock), patch.object(sampler, 'cpu_bindings', return_value=7), \
                    patch.object(sampler.os, 'sysconf', return_value=clock):
                result = sampler.host_cpu(system)
            self.assertEqual(result['errorType'], 'InvalidCpuReading')
            self.assertIn(problem, result['error'])

    def test_cpu_defect_never_withholds_the_memory_reading(self) -> None:
        """A CPU-only defect parses as unknown CPU; memory and every owned footprint remain."""
        raw = direct_sample()
        with patch.object(sampler, 'cpu_bindings', return_value=7), patch.object(sampler.os, 'sysconf', return_value=-1):
            cpu = sampler.host_cpu(cpu_system([1] * 8))
        value = json.loads(raw['direct']) | {'cpu': cpu}
        result = parse_direct(json.dumps(value), raw['ps'], REQUEST)
        self.assertEqual(result['hostCpu'].status, 'unavailable')
        self.assertEqual([row.footprint_bytes for row in result['selection']['processes']], [2 ** 31, 2 ** 30])
        self.assertTrue(all(row.cpu_user_ns is None for row in result['selection']['processes']))
        with patch.object(sampler, 'validate_abi'), patch.object(sampler, 'bindings', return_value=('proc', 'sys')), \
                patch.object(sampler, 'process_memory', side_effect=lambda _lib, pid: process_row(pid)), \
                patch.object(sampler, 'host_memory', return_value={'test': 'host'}), \
                patch.object(sampler, 'cpu_bindings', side_effect=AttributeError('no symbol')):
            collected = sampler.collect([100])
        self.assertEqual(collected['cpu'], {'status': 'unavailable', 'errorType': 'AttributeError',
                                            'error': 'no symbol'})
        self.assertEqual((collected['status'], collected['schemaVersion']), ('measured', 2))
        self.assertEqual(collected['processes'][0]['footprintBytes'], 214041128)

    def test_collect_reads_cpu_inside_the_memory_identity_bracket(self) -> None:
        """Host CPU is read after the first process pass and before the second."""
        order = []
        def process(_library: object, pid: int) -> dict:
            order.append(pid)
            return process_row(pid)
        with patch.object(sampler, 'validate_abi'), patch.object(sampler, 'bindings', return_value=('proc', 'sys')), \
                patch.object(sampler, 'process_memory', side_effect=process), \
                patch.object(sampler, 'host_memory', side_effect=lambda _sys: order.append('host') or {}), \
                patch.object(sampler, 'host_cpu', side_effect=lambda _sys: order.append('cpu') or {'status': 'x'}):
            result = sampler.collect([100])
        self.assertEqual(order, [100, 'host', 'cpu', 100])
        self.assertEqual(result['cpu'], {'status': 'x'})


if __name__ == '__main__':
    unittest.main()
