"""Supervisor-side memory and CPU ceilings for one jailed process that survive exec.

The jetsam limit the launcher attaches is enforced by the kernel but reset by any
later exec, and ``RLIMIT_CPU`` on macOS only raises one SIGXCPU. This watchdog
reads the jailed pid (from its attestation) and polls the kernel's accounting
for that pid (``proc_pid_rusage``: physical footprint, user + system CPU time)
every few milliseconds. Above either ceiling it SIGKILLs the process (and its
group when it leads one) and records why. The pid stays the same across exec, so
a decoder that re-executes itself is still watched. A sampled limit can be
exceeded briefly between polls.

The watched process is pinned by its kernel start time: it must have started
after this watchdog was created, and a later sample with a different start time
(a reused pid) or an exit time ends the watch without signalling anything.
"""
from __future__ import annotations

import ctypes
import json
import os
import signal
import struct
import threading
import time

_LIBC = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
_RUSAGE_INFO_V2 = 2
_POLL_SECONDS = 0.01


class _Timebase(ctypes.Structure):
    _fields_ = [("numer", ctypes.c_uint32), ("denom", ctypes.c_uint32)]


def _ticks_to_seconds() -> float:
    base = _Timebase()
    _LIBC.mach_timebase_info(ctypes.byref(base))
    return base.numer / base.denom / 1e9


_TICK_SECONDS = _ticks_to_seconds()


def _now() -> int:
    """The kernel's absolute clock, in the units of ``proc_start_abstime``."""
    _LIBC.mach_absolute_time.restype = ctypes.c_uint64
    return _LIBC.mach_absolute_time()


def _rusage(pid: int) -> tuple[int, float, int, int] | None:
    """Footprint, CPU seconds, start and exit abstime of ``pid`` (rusage_info_v2), or None."""
    buffer = ctypes.create_string_buffer(512)
    if _LIBC.proc_pid_rusage(pid, _RUSAGE_INFO_V2, buffer) != 0:
        return None
    user, system = struct.unpack_from("<QQ", buffer.raw, 16)
    footprint, started, exited = struct.unpack_from("<QQQ", buffer.raw, 72)
    return footprint, (user + system) * _TICK_SECONDS, started, exited


def usage(pid: int) -> tuple[int, float] | None:
    """Physical footprint (bytes) and user+system CPU seconds of ``pid``, or None when gone."""
    sample = _rusage(pid)
    return None if sample is None else sample[:2]


class JailWatchdog:
    """Kill the jailed process group above its memory or CPU ceiling.

    It owns a daemon thread rather than subclassing ``threading.Thread``: private
    names such as ``_stop`` or ``_started`` are Thread internals on some Python
    versions (3.12 calls ``self._stop()`` from ``join``), so a subclass attribute can
    silently replace them.
    """

    def __init__(self, attest_fd: int, memory_bytes: int, cpu_seconds: float) -> None:
        self._fd, self._memory, self._cpu = attest_fd, memory_bytes, cpu_seconds
        self._stop_event = threading.Event()
        self._created = _now()
        self._pinned_start: int | None = None
        self._thread = threading.Thread(target=self._watch, name="sniper-jail-watchdog", daemon=True)
        self.exceeded: str | None = None
        self.peak_bytes = 0

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=2)

    def _pid(self) -> int | None:
        """The jailed pid from its attestation, once written."""
        try:
            raw = os.pread(self._fd, 65536, 0)
            return int(json.loads(raw.decode("utf-8"))["pid"]) if raw.endswith(b"\n") else None
        except (OSError, ValueError, KeyError, UnicodeDecodeError):
            return None

    def _same_process(self, started: int, exited: int) -> bool:
        """Whether a sample still describes the process first seen (not exited, pid not reused)."""
        if self._pinned_start is None:
            if started < self._created:
                return False  # an older process holds this pid: never ours
            self._pinned_start = started
        return started == self._pinned_start and exited == 0

    def _kill(self, pid: int) -> None:
        """SIGKILL the jailed pid, and its process group when it leads one (its own session)."""
        targets = [os.kill]
        try:
            if os.getpgid(pid) == pid:
                targets.append(os.killpg)
        except (ProcessLookupError, PermissionError):
            pass
        for kill in targets:
            try:
                kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

    def _check(self, pid: int) -> bool:
        """True while the same process is alive and within its ceilings."""
        sample = _rusage(pid)
        if sample is None or not self._same_process(sample[2], sample[3]):
            return False
        footprint, cpu = sample[0], sample[1]
        self.peak_bytes = max(self.peak_bytes, footprint)
        reason = "MEMORY_LIMIT" if footprint > self._memory else "CPU_LIMIT" if cpu > self._cpu else None
        if reason and not self._stop_event.is_set():
            self.exceeded = reason
            self._kill(pid)
            return False
        return True

    def _watch(self) -> None:
        pid = None
        while not self._stop_event.is_set() and pid is None:
            pid = self._pid()
            time.sleep(_POLL_SECONDS)
        while pid is not None and not self._stop_event.is_set() and self._check(pid):
            time.sleep(_POLL_SECONDS)
