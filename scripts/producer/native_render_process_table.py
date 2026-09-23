"""SDK-declared libproc identity reads for a bounded owned tree, without spawning ps.

ABI: macOS SDK sys/proc_info.h proc_bsdinfo and libproc.h. The supervisor still
authorizes roots through its independent ps registry. This helper only reads.
"""
from __future__ import annotations

import ctypes as c
import errno
import os
import time

from native_render_macos import validate_abi
from native_render_processes import ProcessIdentity, ProcessRequest, ResourceMeasurementError, MissingProcessFootprint

MAX_PROCESSES = 4096


class BsdInfo(c.Structure):
    """SDK-declared PROC_PIDTBSDINFO layout; checked before any kernel buffer write."""

    _fields_ = [(name, c.c_uint32) for name in (
        'flags', 'status', 'xstatus', 'pid', 'ppid', 'uid', 'gid', 'ruid', 'rgid', 'svuid', 'svgid', 'reserved')]
    _fields_ += [('comm', c.c_char * 16), ('name', c.c_char * 32)]
    _fields_ += [(name, c.c_uint32) for name in ('nfiles', 'pgid', 'jobc', 'tdev', 'tpgid')]
    _fields_ += [('nice', c.c_int32), ('start_seconds', c.c_uint64), ('start_microseconds', c.c_uint64)]


def process_bindings() -> c.CDLL:
    """Bind supported SDK signatures and reject incompatible structure layouts."""
    validate_abi()
    if (c.sizeof(BsdInfo), BsdInfo.pgid.offset, BsdInfo.start_seconds.offset) != (136, 100, 120):
        raise ResourceMeasurementError('Unsupported proc_bsdinfo layout')
    library = c.CDLL('/usr/lib/libproc.dylib', use_errno=True)
    library.proc_pidinfo.argtypes = [c.c_int, c.c_int, c.c_uint64, c.c_void_p, c.c_int]
    library.proc_pidinfo.restype = c.c_int
    library.proc_listchildpids.argtypes = [c.c_int, c.c_void_p, c.c_int]
    library.proc_listchildpids.restype = c.c_int
    return library


def process_row(library: c.CDLL, pid: int) -> tuple | None:
    """Only confirmed absence or kernel zombie state excludes an exited process."""
    value = BsdInfo()
    c.set_errno(0)
    size = library.proc_pidinfo(pid, 3, 0, c.byref(value), c.sizeof(value))
    error = c.get_errno()
    if size == 0 and error == errno.ESRCH:
        return None
    if size != c.sizeof(value) or value.pid != pid or value.start_seconds == 0:
        raise ResourceMeasurementError(f'Owned process identity unavailable: pid={pid}, size={size}, errno={error}')
    if value.status == 5:  # SZOMB, sys/proc.h; exited, awaiting parent reaping.
        return None
    started = time.strftime('%a %b %e %H:%M:%S %Y', time.localtime(value.start_seconds))
    return value.ppid, value.pgid, started


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
    identities = request.remembered + ((request.root,) if request.root else ())
    table, pending = {}, []
    for identity in identities:
        row = process_row(library, identity.pid)
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
    """Require a fresh read when child ancestry changes during enumeration."""
    for pid in child_pids(library, parent):
        row = process_row(library, pid)
        if row is None:
            continue
        if row[0] != parent:
            raise MissingProcessFootprint((ProcessIdentity(pid, row[2], row[1]),),
                                          'parent-changed-during-child-discovery')
        table[pid] = row
        pending.append(pid)
