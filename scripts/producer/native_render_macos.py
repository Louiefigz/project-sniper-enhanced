"""One-shot public macOS memory reader, bounded by its owner's3s subprocess limit.

Apple top-144 uses HOST_VM_INFO64 and vm_kernel_page_size for unused/compressor
memory. ri_phys_footprint is the inclusive process footprint, never RSS plus
compression. No public unprivileged exact per-process compressed reader is used.
Paired absolute start/exit observations bind one helper call. Cross-sample
ownership remains the existing ps lstart/PGID registry and identity bracketing.
rusage CPU times are Mach absolute-time ticks (125/3 ns each on Apple Silicon),
never nanoseconds; the parser converts them with this call's own timebase. Under
Rosetta the timebase reads 1/1 while rusage stays in native ticks, so a translated
helper reports CPU unavailable. Host CPU comes from host_processor_info:
host_statistics CPU load is rate limited across unprivileged processes and returns
cached, non-advancing ticks. The helper validates every CPU value it emits with the
parser's own rule (cpu_problem) and reports anything else as unavailable, so a CPU
defect never withholds the memory reading.
"""
from __future__ import annotations

import ctypes as c
import errno
import json
import os
import platform
import sys
import time

SAMPLER = 'darwin-public-libproc-host-statistics64-v1'
COMPRESSED_UNAVAILABLE = 'not-collected-public-unprivileged-api-unavailable'
SCHEMA_VERSION = 2
CPU_SOURCE = 'host_processor_info:PROCESSOR_CPU_LOAD_INFO'
PROCESSOR_CPU_LOAD_INFO = 2  # mach/processor_info.h
CPU_STATES = 4  # mach/machine.h CPU_STATE_MAX: user, system, idle, nice
MAXIMUM_PROCESSORS = 1024
MEASURED_CPU_FIELDS = frozenset({'status', 'source', 'readAbstime', 'timebase', 'clockTicksPerSecond',
                                 'processorTicks'})


class RusageV0(c.Structure):
    """Installed SDK sys/resource.h version-zero public ABI."""

    _fields_ = [('ri_uuid', c.c_uint8 * 16)] + [(name, c.c_uint64) for name in (
        'ri_user_time', 'ri_system_time', 'ri_pkg_idle_wkups', 'ri_interrupt_wkups',
        'ri_pageins', 'ri_wired_size', 'ri_resident_size', 'ri_phys_footprint',
        'ri_proc_start_abstime', 'ri_proc_exit_abstime')]


class VMStatistics64(c.Structure):
    """Installed SDK mach/vm_statistics.h public HOST_VM_INFO64 ABI."""

    _fields_ = [(name, c.c_uint32) for name in (
        'free_count', 'active_count', 'inactive_count', 'wire_count')]
    _fields_ += [(name, c.c_uint64) for name in (
        'zero_fill_count', 'reactivations', 'pageins', 'pageouts', 'faults',
        'cow_faults', 'lookups', 'hits', 'purges')]
    _fields_ += [(name, c.c_uint32) for name in ('purgeable_count', 'speculative_count')]
    _fields_ += [(name, c.c_uint64) for name in (
        'decompressions', 'compressions', 'swapins', 'swapouts')]
    _fields_ += [(name, c.c_uint32) for name in (
        'compressor_page_count', 'throttled_count', 'external_page_count', 'internal_page_count')]
    _fields_ += [('total_uncompressed_pages_in_compressor', c.c_uint64)]


class MachTimebase(c.Structure):
    """Installed SDK mach/mach_time.h mach_timebase_info_data_t."""

    _fields_ = [('numer', c.c_uint32), ('denom', c.c_uint32)]


def abi_layout() -> dict:
    """Expose offsets for a separate SDK-compiled layout-only verifier."""
    return {cls.__name__: {'size': c.sizeof(cls), 'alignment': c.alignment(cls),
        'offsets': {name: getattr(cls, name).offset for name, _ in cls._fields_}}
        for cls in (RusageV0, VMStatistics64, MachTimebase)}


def bindings() -> tuple:
    """Declare public signatures, including the pointer-to-buffer rusage ABI."""
    libproc = c.CDLL('/usr/lib/libproc.dylib', use_errno=True)
    system = c.CDLL('/usr/lib/libSystem.B.dylib', use_errno=True)
    libproc.proc_pid_rusage.argtypes = [c.c_int, c.c_int, c.c_void_p]
    libproc.proc_pid_rusage.restype = c.c_int
    system.mach_host_self.argtypes, system.mach_host_self.restype = [], c.c_uint32
    system.host_statistics64.argtypes = [c.c_uint32, c.c_int, c.c_void_p, c.POINTER(c.c_uint32)]
    system.host_statistics64.restype = c.c_int
    return libproc, system


def validate_abi() -> None:
    """Reject unsupported layouts before a kernel writes into our buffers."""
    supported = (sys.platform == 'darwin' and sys.byteorder == 'little'
        and platform.machine() in {'arm64', 'x86_64'} and c.sizeof(c.c_size_t) == 8)
    expected = (c.sizeof(RusageV0), c.alignment(RusageV0), RusageV0.ri_phys_footprint.offset,
        c.sizeof(VMStatistics64), c.alignment(VMStatistics64), VMStatistics64.compressor_page_count.offset)
    if not supported or expected != (96, 8, 72, 152, 8, 128):
        raise RuntimeError('Unsupported macOS memory sampler ABI')


def host_memory(system: c.CDLL) -> dict:
    """Return measured physical compressor pages and raw free-count semantics."""
    host, vm = system.mach_host_self(), VMStatistics64()
    page_size = c.c_size_t.in_dll(system, 'vm_kernel_page_size').value
    count = c.c_uint32(c.sizeof(vm) // c.sizeof(c.c_int))
    vm_result = system.host_statistics64(host, 4, c.byref(vm), c.byref(count))
    if vm_result or page_size not in {4096, 16384} or count.value != c.sizeof(vm) // 4:
        raise RuntimeError(f'Incomplete host measurement: {vm_result}, {page_size}, {count.value}')
    raw = {name: getattr(vm, name) for name, _ in vm._fields_}
    return {'pageSizeBytes': page_size, 'pageSizeSource': 'vm_kernel_page_size',
        'returnedIntegerCount': count.value, 'raw': raw,
        'compressorBytes': vm.compressor_page_count * page_size,
        'unusedPhysicalBytes': vm.free_count * page_size}


def process_memory(libproc: c.CDLL, pid: int) -> dict:
    """Measure physical footprint; preserve unavailable compressed diagnostic explicitly."""
    usage = RusageV0()
    result = libproc.proc_pid_rusage(pid, 0, c.byref(usage))
    if result:
        return {'pid': pid, 'status': 'unavailable', 'result': result, 'errno': c.get_errno()}
    return {'pid': pid, 'status': 'measured', 'footprintBytes': usage.ri_phys_footprint,
        'userTimeAbstime': usage.ri_user_time, 'systemTimeAbstime': usage.ri_system_time,
        'processStartAbstime': usage.ri_proc_start_abstime,
        'processExitAbstime': usage.ri_proc_exit_abstime, 'compressedBytes': None,
        'compressedStatus': COMPRESSED_UNAVAILABLE,
        'footprintSource': 'proc_pid_rusage:RUSAGE_INFO_V0:ri_phys_footprint'}


def cpu_bindings(system: c.CDLL) -> int:
    """Declare public clock and processor-load signatures; return this task's port."""
    if c.sizeof(MachTimebase) != 8 or c.sizeof(c.c_size_t) != 8:
        raise RuntimeError('Unsupported Mach timebase ABI')
    system.mach_absolute_time.argtypes, system.mach_absolute_time.restype = [], c.c_uint64
    system.mach_timebase_info.argtypes, system.mach_timebase_info.restype = [c.c_void_p], c.c_int
    system.host_processor_info.argtypes = [c.c_uint32, c.c_int, c.POINTER(c.c_uint32),
        c.POINTER(c.POINTER(c.c_int32)), c.POINTER(c.c_uint32)]
    system.host_processor_info.restype = c.c_int
    system.vm_deallocate.argtypes = [c.c_uint32, c.c_size_t, c.c_size_t]
    system.vm_deallocate.restype = c.c_int
    system.sysctlbyname.argtypes = [c.c_char_p, c.c_void_p, c.POINTER(c.c_size_t), c.c_void_p, c.c_size_t]
    system.sysctlbyname.restype = c.c_int
    return c.c_uint32.in_dll(system, 'mach_task_self_').value


def translated(system: c.CDLL) -> bool:
    """Apple's documented Rosetta probe; ENOENT means a host without translation."""
    value, size = c.c_int(-1), c.c_size_t(c.sizeof(c.c_int))
    c.set_errno(0)
    if system.sysctlbyname(b'sysctl.proc_translated', c.byref(value), c.byref(size), None, 0):
        if c.get_errno() == errno.ENOENT:
            return False
        raise RuntimeError(f'Rosetta translation state unavailable: errno={c.get_errno()}')
    if size.value != c.sizeof(c.c_int) or value.value not in (0, 1):
        raise RuntimeError(f'Unexpected Rosetta translation state: {value.value}')
    return value.value == 1


def processor_ticks(system: c.CDLL, task: int) -> list[list[int]]:
    """Copy per-processor natural_t tick counters, then release the kernel's array."""
    count, info, size = c.c_uint32(), c.POINTER(c.c_int32)(), c.c_uint32()
    result = system.host_processor_info(system.mach_host_self(), PROCESSOR_CPU_LOAD_INFO,
                                        c.byref(count), c.byref(info), c.byref(size))
    if result:
        raise RuntimeError(f'host_processor_info failed: {result}')
    address = c.cast(info, c.c_void_p).value
    try:
        if not address or not 0 < count.value <= MAXIMUM_PROCESSORS or size.value != count.value * CPU_STATES:
            raise RuntimeError(f'Incomplete processor load counters: {count.value}, {size.value}')
        values = [info[index] & 0xFFFFFFFF for index in range(size.value)]
    finally:
        released = system.vm_deallocate(task, address, size.value * 4) if address else 0
    if released:
        raise RuntimeError(f'Processor load array was not released: {released}')
    return [values[start:start + CPU_STATES] for start in range(0, len(values), CPU_STATES)]


def _counter(value: object, bits: int, minimum: int = 0) -> bool:
    """An exact integer inside an unsigned counter's range; bools and floats never pass."""
    return type(value) is int and minimum <= value < 2 ** bits


def cpu_problem(value: object) -> str | None:
    """Name the first reason a measured CPU reading is unusable; None when complete.

    The helper applies this before emitting (a failure becomes 'unavailable') and the
    parser applies it again, so only a forged or version-skewed payload fails closed.
    """
    if not isinstance(value, dict) or set(value) != MEASURED_CPU_FIELDS or value['status'] != 'measured':
        return 'unexpected CPU reading fields'
    timebase, rows = value['timebase'], value['processorTicks']
    checks = ((value['source'] == CPU_SOURCE, 'unknown CPU source'),
              (isinstance(timebase, dict) and set(timebase) == {'numer', 'denom'}
               and all(_counter(timebase[key], 32, 1) for key in ('numer', 'denom')), 'invalid Mach timebase'),
              (_counter(value['clockTicksPerSecond'], 32, 1), 'invalid processor tick rate'),
              (_counter(value['readAbstime'], 64, 1), 'invalid CPU read time'),
              (isinstance(rows, list) and 0 < len(rows) <= MAXIMUM_PROCESSORS, 'invalid processor count'))
    for passed, problem in checks:
        if not passed:
            return problem
    if any(not isinstance(row, list) or len(row) != CPU_STATES or not all(_counter(tick, 32) for tick in row)
           for row in rows):
        return 'invalid processor ticks'
    return None


def cpu_unavailable(error_type: str, error: str) -> dict:
    """Explicit CPU unavailability; the memory reading in the same payload still counts."""
    return {'status': 'unavailable', 'errorType': error_type, 'error': error}


def read_host_cpu(system: c.CDLL) -> dict:
    """Refuse translated time, then read the timebase, processor ticks and Mach time."""
    task, timebase = cpu_bindings(system), MachTimebase()
    if translated(system):
        raise RuntimeError('Rosetta translation: Mach time is nanoseconds while rusage CPU stays native ticks')
    if system.mach_timebase_info(c.byref(timebase)):
        raise RuntimeError('Mach timebase unavailable')
    ticks = processor_ticks(system, task)
    read = system.mach_absolute_time()
    return {'status': 'measured', 'source': CPU_SOURCE, 'readAbstime': read,
            'timebase': {'numer': timebase.numer, 'denom': timebase.denom},
            'clockTicksPerSecond': os.sysconf('SC_CLK_TCK'), 'processorTicks': ticks}


def host_cpu(system: c.CDLL) -> dict:
    """Emit only a CPU reading the parser accepts; everything else is explicitly unavailable."""
    try:
        reading = read_host_cpu(system)
    except (OSError, RuntimeError, ValueError, AttributeError, TypeError) as error:
        return cpu_unavailable(type(error).__name__, str(error))
    problem = cpu_problem(reading)
    return cpu_unavailable('InvalidCpuReading', problem) if problem else reading


def consistent_process(before: dict, after: dict) -> dict:
    """Require the same live kernel start identity across the memory collection."""
    if before['status'] != 'measured' or after['status'] != 'measured':
        return {'pid': before['pid'], 'status': 'unavailable', 'reason': 'rusage-api-failed',
                'before': before, 'after': after}
    stable = (before['processStartAbstime'] > 0
        and before['processStartAbstime'] == after['processStartAbstime']
        and before['processExitAbstime'] == after['processExitAbstime'] == 0)
    if not stable:
        return {'pid': before['pid'], 'status': 'unavailable',
            'reason': 'rusage-identity-not-stable-and-live', 'before': before, 'after': after}
    return after | {'processStartAbstimeBefore': before['processStartAbstime']}


def collect(pids: list[int]) -> dict:
    """Read host counters between two physical-footprint identity observations."""
    validate_abi()
    libproc, system = bindings()
    before = [process_memory(libproc, pid) for pid in pids]
    host = host_memory(system)
    cpu = host_cpu(system)
    after = [process_memory(libproc, pid) for pid in pids]
    return {'schemaVersion': SCHEMA_VERSION, 'sampler': SAMPLER, 'status': 'measured', 'host': host,
        'cpu': cpu, 'processes': [consistent_process(first, second) for first, second in zip(before, after)]}


def main() -> None:
    """A parent must enforce the existing three-second subprocess timeout."""
    if sys.argv[1:] == ['--layout']:
        print(json.dumps(abi_layout(), sort_keys=True))
        return
    pids = [int(value) for value in sys.argv[1:]]
    if len(pids) > 4096 or len(set(pids)) != len(pids) or any(pid <= 1 for pid in pids):
        raise ValueError('PID arguments require unique positive explicit process IDs')
    started = time.monotonic()
    try:
        result = collect(pids)
    except (OSError, ValueError, RuntimeError, AttributeError) as error:
        result = {'schemaVersion': SCHEMA_VERSION, 'sampler': SAMPLER, 'status': 'unavailable',
                  'errorType': type(error).__name__, 'error': str(error)}
    result['elapsedSeconds'] = time.monotonic() - started
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
