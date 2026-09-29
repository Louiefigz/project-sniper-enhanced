"""Bounded no-child proof reads with task-local macOS disk counters.

This collector measures only its calling process. It invokes no callbacks or
children, requires one kernel thread, and retains both raw kernel observations.
Zero disk bytes is an observation, never evidence of cold storage. Kernel start
identity uses Mach absolute ticks; interval timestamps use monotonic nanoseconds.
The parent must bind this result to its real owned process and captured output.
"""
from __future__ import annotations

import ctypes as c
import hashlib
import os
import platform
import re
import sys
import time
from pathlib import Path

from cut_preview_io import MAX_JSON, read_bytes
from native_render_macos import RusageV0
from native_render_process_table import process_bindings, process_row

COLLECTOR = 'darwin-no-child-proof-read-v1'
MAX_PASS_BYTES = 128 * MAX_JSON


class RusageV2(c.Structure):
    """Public SDK resource.h V2 layout; child CPU fields are not disk counters."""

    _fields_ = RusageV0._fields_ + [(name, c.c_uint64) for name in (
        'ri_child_user_time', 'ri_child_system_time', 'ri_child_pkg_idle_wkups',
        'ri_child_interrupt_wkups', 'ri_child_pageins', 'ri_child_elapsed_abstime',
        'ri_diskio_bytesread', 'ri_diskio_byteswritten')]


class TaskInfo(c.Structure):
    """Public SDK proc_info.h PROC_PIDTASKINFO layout."""

    _fields_ = [(name, c.c_uint64) for name in (
        'pti_virtual_size', 'pti_resident_size', 'pti_total_user', 'pti_total_system',
        'pti_threads_user', 'pti_threads_system')]
    _fields_ += [(name, c.c_int32) for name in (
        'pti_policy', 'pti_faults', 'pti_pageins', 'pti_cow_faults', 'pti_messages_sent',
        'pti_messages_received', 'pti_syscalls_mach', 'pti_syscalls_unix', 'pti_csw',
        'pti_threadnum', 'pti_numrunning', 'pti_priority')]


def abi_layout() -> dict:
    """Expose all layouts for the independent SDK-compiled regression."""
    return {cls.__name__: {'size': c.sizeof(cls), 'alignment': c.alignment(cls),
            'offsets': {name: getattr(cls, name).offset for name, _ in cls._fields_}}
            for cls in (RusageV2, TaskInfo)}


def bindings() -> c.CDLL:
    """Reject unsupported ABI before declaring public libproc signatures."""
    supported = (sys.platform == 'darwin' and sys.byteorder == 'little'
                 and platform.machine() in {'arm64', 'x86_64'} and c.sizeof(c.c_void_p) == 8)
    shape = (c.sizeof(RusageV2), c.alignment(RusageV2), RusageV2.ri_diskio_bytesread.offset,
             RusageV2.ri_diskio_byteswritten.offset, c.sizeof(TaskInfo), TaskInfo.pti_threadnum.offset)
    if not supported or shape != (160, 8, 144, 152, 96, 84):
        raise RuntimeError('Unsupported macOS proof IO ABI')
    library = process_bindings()
    library.proc_pid_rusage.argtypes = [c.c_int, c.c_int, c.c_void_p]
    library.proc_pid_rusage.restype = c.c_int
    return library


def topology(library: c.CDLL, pid: int) -> dict:
    """Keep raw topology returns; accept only zero children and one kernel thread."""
    task, children = TaskInfo(), (c.c_int * 1)()
    c.set_errno(0)
    task_result = library.proc_pidinfo(pid, 4, 0, c.byref(task), c.sizeof(task))
    task_errno = c.get_errno()
    c.set_errno(0)
    child_result = library.proc_listchildpids(pid, children, c.sizeof(children))
    child_errno = c.get_errno()
    accepted = (task_result == c.sizeof(task) and task_errno == 0
                and task.pti_threadnum == 1 and child_result == 0 and child_errno == 0)
    return {'accepted': accepted, 'taskResult': task_result, 'taskErrno': task_errno,
            'threadCount': task.pti_threadnum if task_result == c.sizeof(task) else None,
            'childResult': child_result, 'childErrno': child_errno}


def snapshot(library: c.CDLL, pid: int) -> dict:
    """Collect exact task-local disk counters, start/exit identity, and raw errors."""
    usage = RusageV2()
    c.set_errno(0)
    result = library.proc_pid_rusage(pid, 2, c.byref(usage))
    error = c.get_errno()
    measured = result == 0 and error == 0
    return {'pid': pid, 'result': result, 'errno': error,
            'status': 'measured' if measured else 'unavailable',
            'absoluteTime': time.monotonic_ns(),
            'processStart': usage.ri_proc_start_abstime if measured else None,
            'processExit': usage.ri_proc_exit_abstime if measured else None,
            'diskReadBytes': usage.ri_diskio_bytesread if measured else None,
            'diskWriteBytes': usage.ri_diskio_byteswritten if measured else None}


def process_identity(library: c.CDLL, pid: int) -> dict:
    """Observe the existing owner-registry identity without spawning a ps child."""
    try:
        row = process_row(library, pid)
    except (OSError, RuntimeError) as error:
        return {'status': 'unavailable', 'errorType': type(error).__name__, 'error': str(error)}
    if row is None:
        return {'status': 'unavailable', 'reason': 'process-not-live'}
    return {'status': 'measured', 'parentPid': row[0],
            'identity': {'pid': pid, 'pgid': row[1], 'started': row[2]}}


def validate_inputs(inputs: list[dict]) -> None:
    """Validate bounded pin declarations without performing an unmeasured file read."""
    if type(inputs) is not list or not 0 < len(inputs) <= 128:
        raise ValueError('Proof read requires 1..128 pinned reads')
    for row in inputs:
        valid = (type(row) is dict and set(row) == {'path', 'sha256', 'bytes'}
                 and type(row['path']) is str and 0 < len(row['path']) <= 4096
                 and Path(row['path']).is_absolute() and type(row['sha256']) is str
                 and re.fullmatch('[0-9a-f]{64}', row['sha256']) is not None
                 and type(row['bytes']) is int and 0 < row['bytes'] <= MAX_JSON)
        if not valid:
            raise ValueError('Invalid bounded proof input pin')
    if sum(row['bytes'] for row in inputs) > MAX_PASS_BYTES:
        raise ValueError('Proof pass exceeds byte limit')


def read_inputs(inputs: list[dict], reads: list[dict]) -> None:
    """Count bytes actually returned by the existing stable no-follow reader once."""
    for row in inputs:
        data = read_bytes(Path(row['path']), maximum=row['bytes'])
        reads.append({'input': dict(row), 'returnedBytes': len(data)})
        if len(data) != row['bytes'] or hashlib.sha256(data).hexdigest() != row['sha256']:
            raise RuntimeError('Proof input bytes differ from admitted pin')


def counter_reason(before: dict, after: dict) -> str | None:
    """Reject identity churn, exited tasks, reversed intervals, or counter rollback."""
    if before['status'] != 'measured' or after['status'] != 'measured':
        return 'kernel-counter-unavailable'
    if (before['pid'] != after['pid'] or before['processStart'] <= 0
            or before['processStart'] != after['processStart']
            or before['processExit'] != 0 or after['processExit'] != 0):
        return 'kernel-process-identity-not-live-and-stable'
    if before['absoluteTime'] >= after['absoluteTime']:
        return 'monotonic-interval-invalid'
    if any(before[key] > after[key] for key in ('diskReadBytes', 'diskWriteBytes')):
        return 'kernel-counter-rollback'
    return None


def measure_read_pass(inputs: list[dict]) -> dict:
    """Bracket no-child bounded reads; unsupported counters never become fake zeros."""
    validate_inputs(inputs)
    value = {'schemaVersion': 1, 'collector': COLLECTOR, 'pid': os.getpid(),
             'clock': 'monotonic-nanoseconds', 'kernelStartClock': 'mach-absolute-ticks',
             'method': 'proc_pid_rusage-v2', 'status': 'unavailable', 'logicalReads': [],
             'before': None, 'after': None, 'topologyBefore': None, 'topologyAfter': None,
             'identityBefore': None, 'identityAfter': None}
    try:
        library = bindings()
    except (OSError, RuntimeError, AttributeError) as error:
        return value | {'reason': 'kernel-binding-unavailable', 'error': str(error)}
    value['topologyBefore'] = topology(library, value['pid'])
    if not value['topologyBefore']['accepted']:
        return value | {'reason': 'requires-one-thread-and-no-children'}
    value['before'] = snapshot(library, value['pid'])
    value['identityBefore'] = process_identity(library, value['pid'])
    try:
        read_inputs(inputs, value['logicalReads'])
    except (OSError, RuntimeError, ValueError) as error:
        value.update(status='failed', reason='input-read-failed', errorType=type(error).__name__, error=str(error))
    finally:
        value['identityAfter'] = process_identity(library, value['pid'])
        value['after'] = snapshot(library, value['pid'])
        value['topologyAfter'] = topology(library, value['pid'])
    if value['status'] == 'failed':
        return value
    reason = counter_reason(value['before'], value['after'])
    if not value['topologyAfter']['accepted']:
        reason = 'requires-one-thread-and-no-children'
    if (value['identityBefore']['status'] != 'measured'
            or value['identityBefore'] != value['identityAfter']):
        reason = 'owner-registry-identity-unavailable-or-changed'
    return value | {'status': 'unavailable' if reason else 'measured', 'reason': reason}


def cache_pass(measurement: dict, identity: dict) -> dict:
    """Match both BSD observations to the captured owner, inside its Mach bracket.

    The parent supplies exactly its real {pid, pgid, started} registry row and
    verifies the captured output digest/provenance. A matching local observation
    is an identity bridge, not permission to invent an owner or adopt a rate.
    """
    if (measurement.get('collector') != COLLECTOR or measurement.get('schemaVersion') != 1
            or measurement.get('clock') != 'monotonic-nanoseconds'
            or measurement.get('kernelStartClock') != 'mach-absolute-ticks'
            or measurement.get('method') != 'proc_pid_rusage-v2'
            or measurement.get('status') not in {'measured', 'unavailable', 'failed'}
            or type(identity.get('pid')) is not int or identity['pid'] != measurement.get('pid')):
        raise ValueError('Proof pass lacks matching collector and owned process identity')
    if measurement['status'] == 'failed':
        raise RuntimeError('Failed proof input read cannot support a cache pass')
    samples = None
    if measurement['status'] == 'measured':
        if (counter_reason(measurement['before'], measurement['after'])
                or measurement['before']['pid'] != measurement['pid']
                or measurement['identityBefore'].get('status') != 'measured'
                or measurement['identityBefore'] != measurement['identityAfter']
                or measurement['identityBefore'].get('identity') != identity
                or not all(measurement[key]['accepted'] for key in ('topologyBefore', 'topologyAfter'))):
            raise ValueError('Invalid measured kernel proof')
        keys = ('processStart', 'absoluteTime', 'diskReadBytes')
        samples = [{'method': 'proc_pid_rusage-v2', 'identity': dict(identity),
                    **{side: {key: measurement[side][key] for key in keys} for side in ('before', 'after')}}]
    return {'logicalReads': measurement['logicalReads'] or None, 'kernelSamples': samples}
