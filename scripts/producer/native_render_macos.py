"""One-shot public macOS memory reader, bounded by its owner's3s subprocess limit.

Apple top-144 uses HOST_VM_INFO64 and vm_kernel_page_size for unused/compressor
memory. ri_phys_footprint is the inclusive process footprint, never RSS plus
compression. No public unprivileged exact per-process compressed reader is used.
Paired absolute start/exit observations bind one helper call. Cross-sample
ownership remains the existing ps lstart/PGID registry and identity bracketing.
"""
from __future__ import annotations

import ctypes as c
import json
import platform
import sys
import time

SAMPLER = 'darwin-public-libproc-host-statistics64-v1'
COMPRESSED_UNAVAILABLE = 'not-collected-public-unprivileged-api-unavailable'


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


def abi_layout() -> dict:
    """Expose offsets for a separate SDK-compiled layout-only verifier."""
    return {cls.__name__: {'size': c.sizeof(cls), 'alignment': c.alignment(cls),
        'offsets': {name: getattr(cls, name).offset for name, _ in cls._fields_}}
        for cls in (RusageV0, VMStatistics64)}


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
        'processStartAbstime': usage.ri_proc_start_abstime,
        'processExitAbstime': usage.ri_proc_exit_abstime, 'compressedBytes': None,
        'compressedStatus': COMPRESSED_UNAVAILABLE,
        'footprintSource': 'proc_pid_rusage:RUSAGE_INFO_V0:ri_phys_footprint'}


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
    after = [process_memory(libproc, pid) for pid in pids]
    return {'schemaVersion': 1, 'sampler': SAMPLER, 'status': 'measured', 'host': host,
        'processes': [consistent_process(first, second) for first, second in zip(before, after)]}


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
        result = {'schemaVersion': 1, 'sampler': SAMPLER, 'status': 'unavailable',
                  'errorType': type(error).__name__, 'error': str(error)}
    result['elapsedSeconds'] = time.monotonic() - started
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
