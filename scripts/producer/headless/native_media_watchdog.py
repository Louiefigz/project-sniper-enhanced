"""Supervisor-side memory and CPU ceilings for one jailed process that survive exec.

The jetsam limit the launcher attaches is enforced by the kernel but reset by any
later exec, and ``RLIMIT_CPU`` on macOS only raises one SIGXCPU. This watchdog
reads the jailed pid (from its attestation) and polls the kernel's accounting
for that pid (``proc_pid_rusage``: physical footprint, user + system CPU time)
every few milliseconds. Above either ceiling it SIGKILLs the process group and
records why. The pid stays the same across exec, so a decoder that re-executes
itself is still watched. A sampled limit can be exceeded briefly between polls.
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


def usage(pid: int) -> tuple[int, float] | None:
    """Physical footprint (bytes) and user+system CPU seconds of ``pid``, or None when gone."""
    buffer = ctypes.create_string_buffer(512)
    if _LIBC.proc_pid_rusage(pid, _RUSAGE_INFO_V2, buffer) != 0:
        return None
    user, system = struct.unpack_from("<QQ", buffer.raw, 16)
    footprint = struct.unpack_from("<Q", buffer.raw, 72)[0]
    return footprint, (user + system) * _TICK_SECONDS


class JailWatchdog(threading.Thread):
    """Kill the jailed process group above its memory or CPU ceiling."""

    def __init__(self, attest_fd: int, memory_bytes: int, cpu_seconds: float) -> None:
        super().__init__(daemon=True)
        self._fd, self._memory, self._cpu = attest_fd, memory_bytes, cpu_seconds
        self._stop = threading.Event()
        self.exceeded: str | None = None
        self.peak_bytes = 0

    def stop(self) -> None:
        self._stop.set()
        self.join(timeout=2)

    def _pid(self) -> int | None:
        """The jailed pid from its attestation, once written."""
        try:
            raw = os.pread(self._fd, 65536, 0)
            return int(json.loads(raw.decode("utf-8"))["pid"]) if raw.endswith(b"\n") else None
        except (OSError, ValueError, KeyError, UnicodeDecodeError):
            return None

    def _check(self, pid: int) -> bool:
        """True while the process is alive and within its ceilings."""
        sample = usage(pid)
        if sample is None:
            return False
        footprint, cpu = sample
        self.peak_bytes = max(self.peak_bytes, footprint)
        reason = "MEMORY_LIMIT" if footprint > self._memory else "CPU_LIMIT" if cpu > self._cpu else None
        if reason and not self._stop.is_set():
            self.exceeded = reason
            for kill in (os.kill, os.killpg):  # the jailed pid itself, then its own process group
                try:
                    kill(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
            return False
        return True

    def run(self) -> None:
        pid = None
        while not self._stop.is_set() and pid is None:
            pid = self._pid()
            time.sleep(_POLL_SECONDS)
        while pid is not None and not self._stop.is_set() and self._check(pid):
            time.sleep(_POLL_SECONDS)
