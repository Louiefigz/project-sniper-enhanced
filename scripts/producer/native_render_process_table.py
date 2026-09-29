"""SDK-declared libproc identity reads for a bounded owned tree, without spawning ps.

ABI: macOS SDK sys/proc_info.h proc_bsdinfo, libproc.h and sys/sysctl.h kinfo_proc.
The supervisor still authorizes roots through its independent ps registry. This
helper only reads. libproc refuses (EPERM) to describe another user's process, so a
recorded PID that another user's process now holds is read through the kinfo_proc
row that ps itself uses: a different kernel start proves the recorded process exited.
"""
from __future__ import annotations

import ctypes as c
import errno
import os
import time

from native_render_macos import validate_abi
from native_render_processes import ProcessIdentity, ProcessRequest, ResourceMeasurementError, MissingProcessFootprint

MAX_PROCESSES = 4096
KINFO_LAYOUT = (648, 0, 36, 40, 560, 564)  # size; start, p_stat, p_pid, e_ppid, e_pgid offsets
KERN_PROC_PID_MIB = (1, 14, 1)  # CTL_KERN, KERN_PROC, KERN_PROC_PID: sys/sysctl.h
SZOMB = 5  # sys/proc.h: exited, awaiting parent reaping.


class ProcessInfoDenied(ResourceMeasurementError):
    """libproc refused an identity read (EPERM); fails closed unless kinfo_proc shows a new process."""


class BsdInfo(c.Structure):
    """SDK-declared PROC_PIDTBSDINFO layout; checked before any kernel buffer write."""

    _fields_ = [(name, c.c_uint32) for name in (
        'flags', 'status', 'xstatus', 'pid', 'ppid', 'uid', 'gid', 'ruid', 'rgid', 'svuid', 'svgid', 'reserved')]
    _fields_ += [('comm', c.c_char * 16), ('name', c.c_char * 32)]
    _fields_ += [(name, c.c_uint32) for name in ('nfiles', 'pgid', 'jobc', 'tdev', 'tpgid')]
    _fields_ += [('nice', c.c_int32), ('start_seconds', c.c_uint64), ('start_microseconds', c.c_uint64)]


class KinfoProc(c.Structure):
    """SDK kinfo_proc read by PID for any user; only start, state, PID, parent and group.

    Padding reproduces the offsets clang ``offsetof`` reported for the macOS SDK on arm64
    and x86_64 (KINFO_LAYOUT). Comparing KINFO_LAYOUT only catches an edit to this
    declaration; the runtime guards are the kernel's returned size, the returned PID and
    process_bindings' check that this process's own row matches libproc's.
    """

    _fields_ = [('start_seconds', c.c_int64), ('start_microseconds', c.c_int32), ('_before_state', c.c_uint8 * 24),
                ('state', c.c_uint8), ('_before_pid', c.c_uint8 * 3), ('pid', c.c_int32),
                ('_before_parent', c.c_uint8 * 516), ('ppid', c.c_int32), ('pgid', c.c_int32),
                ('_after_group', c.c_uint8 * 80)]


def process_bindings() -> c.CDLL:
    """Bind supported SDK signatures and reject incompatible structure layouts."""
    validate_abi()
    if (c.sizeof(BsdInfo), BsdInfo.pgid.offset, BsdInfo.start_seconds.offset) != (136, 100, 120):
        raise ResourceMeasurementError('Unsupported proc_bsdinfo layout')
    if kinfo_layout() != KINFO_LAYOUT:
        raise ResourceMeasurementError('kinfo_proc declaration differs from the measured SDK layout')
    library = c.CDLL('/usr/lib/libproc.dylib', use_errno=True)
    library.proc_pidinfo.argtypes = [c.c_int, c.c_int, c.c_uint64, c.c_void_p, c.c_int]
    library.proc_pidinfo.restype = c.c_int
    library.proc_listchildpids.argtypes = [c.c_int, c.c_void_p, c.c_int]
    library.proc_listchildpids.restype = c.c_int
    kernel = c.CDLL('/usr/lib/libSystem.B.dylib', use_errno=True)
    kernel.sysctl.argtypes = [c.POINTER(c.c_int), c.c_uint, c.c_void_p, c.POINTER(c.c_size_t), c.c_void_p,
                              c.c_size_t]
    kernel.sysctl.restype = c.c_int
    library.sysctl = kernel.sysctl  # One handle carries every declared read.
    if public_row(library, os.getpid()) != process_row(library, os.getpid()):
        raise ResourceMeasurementError('kinfo_proc and libproc disagree about this process')
    return library


def kinfo_layout() -> tuple[int, ...]:
    """Size and the offsets of every kinfo_proc field this helper reads."""
    return (c.sizeof(KinfoProc), KinfoProc.start_seconds.offset, KinfoProc.state.offset, KinfoProc.pid.offset,
            KinfoProc.ppid.offset, KinfoProc.pgid.offset)


def lstart(seconds: int) -> str:
    """Format a kernel start second exactly as ps lstart does."""
    return time.strftime('%a %b %e %H:%M:%S %Y', time.localtime(seconds))


def process_row(library: c.CDLL, pid: int) -> tuple | None:
    """Only confirmed absence or kernel zombie state excludes an exited process."""
    value = BsdInfo()
    c.set_errno(0)
    size = library.proc_pidinfo(pid, 3, 0, c.byref(value), c.sizeof(value))
    error = c.get_errno()
    if size == 0 and error == errno.ESRCH:
        return None
    detail = f'Owned process identity unavailable: pid={pid}, size={size}, errno={error}'
    if size == 0 and error == errno.EPERM:
        raise ProcessInfoDenied(detail)
    if size != c.sizeof(value) or value.pid != pid or value.start_seconds == 0:
        raise ResourceMeasurementError(detail)
    if value.status == SZOMB:
        return None
    return value.ppid, value.pgid, lstart(value.start_seconds)


def public_row(library: c.CDLL, pid: int) -> tuple | None:
    """Read any user's PID, parent, group and start from kinfo_proc; None once exited."""
    value, size = KinfoProc(), c.c_size_t(c.sizeof(KinfoProc))
    name = (c.c_int * 4)(*KERN_PROC_PID_MIB, pid)
    c.set_errno(0)
    result = library.sysctl(name, 4, c.byref(value), c.byref(size), None, 0)
    if result != 0:
        raise ResourceMeasurementError(f'Process table row unavailable: pid={pid}, errno={c.get_errno()}')
    if size.value == 0:
        return None
    if size.value != c.sizeof(KinfoProc) or value.pid != pid or value.start_seconds <= 0:
        raise ResourceMeasurementError(f'Process table row malformed: pid={pid}, size={size.value}')
    return None if value.state == SZOMB else (value.ppid, value.pgid, lstart(value.start_seconds))


def recorded_row(library: c.CDLL, identity: ProcessIdentity) -> tuple | None:
    """Read a recorded PID; another user's process there is foreign only by its start.

    The same start (or an unbound identity) means libproc refused the recorded
    process itself, which fails closed exactly as before.
    """
    try:
        return process_row(library, identity.pid)
    except ProcessInfoDenied:
        row = public_row(library, identity.pid)
        if identity.started is None or (row is not None and row[2] == identity.started):
            raise
        return row


def child_pids(library: c.CDLL, pid: int) -> list[int]:
    """Refuse full/truncated child buffers rather than silently dropping descendants."""
    buffer = (c.c_int * (MAX_PROCESSES + 1))()
    c.set_errno(0)
    count = library.proc_listchildpids(pid, buffer, c.sizeof(buffer))
    error = c.get_errno()
    if count == 0 and error in {0, errno.ESRCH}:
        return []
    if count < 0 or count > MAX_PROCESSES:
        raise ResourceMeasurementError('Owned child enumeration failed or exceeded its bound')
    if count == 0 or error:
        raise ResourceMeasurementError(f'Owned child enumeration unavailable: errno={error}')
    return [pid for pid in buffer[:count] if pid > 1]


def matches(row: tuple, identity: ProcessIdentity) -> bool:
    """Expand only caller-bound live identities; reused PIDs remain unowned rows."""
    return row[1:] == (identity.pgid, identity.started)


def identity_table(request: ProcessRequest) -> str:
    """Read remembered orphans and current descendants without creating helper children."""
    library = process_bindings()
    rows = [(identity, recorded_row(library, identity)) for identity in request.remembered]
    if request.root:  # A root is never retired while sampled; libproc must describe it.
        rows.append((request.root, process_row(library, request.root.pid)))
    table, pending = {}, []
    for identity, row in rows:
        if row is None:
            continue
        table[identity.pid] = row
        if matches(row, identity):
            pending.append(identity.pid)
    expand_children(library, table, pending)
    # Keep the parser's nonempty-table contract for host-only admission/exited roots.
    own = process_row(library, os.getpid())
    if own is None:
        raise ResourceMeasurementError('Identity sampler cannot observe itself')
    table[os.getpid()] = own
    return ''.join(f'{pid} {row[0]} {row[1]} {row[2]}\n' for pid, row in sorted(table.items()))


def expand_children(library: c.CDLL, table: dict, pending: list[int]) -> None:
    """Bound traversal and retain actual parent relationships for the shared selector."""
    visited = set()
    while pending:
        parent = pending.pop()
        if parent in visited:
            continue
        visited.add(parent)
        add_children(library, parent, table, pending)
        if len(table) > MAX_PROCESSES:
            raise ResourceMeasurementError('Owned process tree exceeds its bound')


def add_children(library: c.CDLL, parent: int, table: dict, pending: list[int]) -> None:
    """Require a fresh read when child ancestry changes during enumeration.

    Children are listed by PID, so the parent is read again afterwards: if that PID
    no longer holds the process read into the table (it exited, possibly reassigned
    to a process with its own children), none of the listed children is accepted.
    """
    children = []
    for pid in child_pids(library, parent):
        row = process_row(library, pid)
        if row is None:
            continue
        if row[0] != parent:
            raise MissingProcessFootprint((ProcessIdentity(pid, row[2], row[1]),),
                                          'parent-changed-during-child-discovery')
        children.append((pid, row))
    if not same_process(library, parent, table[parent]):
        raise MissingProcessFootprint((ProcessIdentity(parent, table[parent][2], table[parent][1]),),
                                      'parent-changed-during-child-discovery')
    for pid, row in children:
        table[pid] = row
        pending.append(pid)


def same_process(library: c.CDLL, pid: int, row: tuple) -> bool:
    """Whether the PID still holds the process read as ``row``; a refused read is a change."""
    try:
        return process_row(library, pid) == row
    except ProcessInfoDenied:
        return False
