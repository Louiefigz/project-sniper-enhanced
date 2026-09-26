"""Windows subprocess ownership for the shared bounded process runner."""
from __future__ import annotations

import ctypes
import subprocess
import threading
import time
from ctypes import wintypes
from typing import Callable


class _IoCounters:
    """Thread-safe output capture state shared by the two pipe readers."""

    def __init__(self, maximum: int) -> None:
        self.maximum = maximum
        self.total = 0
        self.output = {"stdout": bytearray(), "stderr": bytearray()}
        self.overflow = threading.Event()
        self.lock = threading.Lock()

    def add(self, name: str, chunk: bytes) -> bool:
        """Append within the aggregate bound; false means the cap was crossed."""
        with self.lock:
            if self.total + len(chunk) > self.maximum:
                self.overflow.set()
                return False
            self.total += len(chunk)
            self.output[name].extend(chunk)
            return True


class _WindowsJob:
    """A kill-on-close Job Object that owns the child and every descendant."""

    def __init__(self, proc: subprocess.Popen) -> None:
        self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self._configure_api()
        self.handle = self._kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            self._set_kill_on_close()
            if not self._kernel.AssignProcessToJobObject(
                    self.handle, wintypes.HANDLE(proc._handle)):
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            self.close()
            raise

    def _configure_api(self) -> None:
        kernel = self._kernel
        kernel.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = (
            wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD)
        kernel.SetInformationJobObject.restype = wintypes.BOOL
        kernel.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
        kernel.TerminateJobObject.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.CloseHandle.restype = wintypes.BOOL

    def _set_kill_on_close(self) -> None:
        info = _JobExtendedLimitInformation()
        info.BasicLimitInformation.LimitFlags = 0x00002000
        ok = self._kernel.SetInformationJobObject(
            self.handle, 9, ctypes.byref(info), ctypes.sizeof(info))
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())

    def terminate(self) -> None:
        """Terminate the complete owned tree; an already-empty job is success."""
        if self.handle and not self._kernel.TerminateJobObject(self.handle, 1):
            error = ctypes.get_last_error()
            if error != 5:
                raise ctypes.WinError(error)

    def close(self) -> None:
        """Close the native handle exactly once."""
        if self.handle:
            self._kernel.CloseHandle(self.handle)
            self.handle = None


class _IoCountersStruct(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _JobExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimitInformation),
        ("IoInfo", _IoCountersStruct),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def _reader(stream, name: str, state: _IoCounters) -> None:
    """Drain one binary pipe until EOF or aggregate overflow."""
    while True:
        chunk = stream.read(65_536)
        if not chunk or not state.add(name, chunk):
            return


def _capture(proc: subprocess.Popen, request: object) -> tuple[str | bytes, str | bytes]:
    """Capture two Windows pipes concurrently under one byte and time bound."""
    state = _IoCounters(request.max_output_bytes)
    proc.stdin.close()
    threads = tuple(threading.Thread(
        target=_reader, args=(getattr(proc, name), name, state), daemon=True)
        for name in ("stdout", "stderr"))
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + request.timeout_seconds
    while proc.poll() is None and not state.overflow.is_set():
        if time.monotonic() >= deadline:
            raise subprocess.TimeoutExpired(request.command, request.timeout_seconds)
        time.sleep(0.01)
    if state.overflow.is_set():
        from .process_runner import ProcessOutputLimitError
        raise ProcessOutputLimitError("child process exceeded its output byte bound")
    for thread in threads:
        thread.join(max(0.001, deadline - time.monotonic()))
    if any(thread.is_alive() for thread in threads):
        raise subprocess.TimeoutExpired(request.command, request.timeout_seconds)
    values = tuple(bytes(state.output[name]) for name in ("stdout", "stderr"))
    return values if not request.decode_output else tuple(
        value.decode("utf-8") for value in values)


def _stop(job: _WindowsJob, proc: subprocess.Popen, grace: float) -> None:
    """Terminate and reap the complete Job Object within the caller's grace."""
    job.terminate()
    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired as error:
        from .process_runner import ProcessReapError
        raise ProcessReapError("Windows child job could not be reaped") from error


def _stop_after_setup_failure(proc: subprocess.Popen, grace: float) -> None:
    """Reap the direct child when Job Object acquisition itself failed."""
    if proc.poll() is None:
        proc.kill()
    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired as error:
        from .process_runner import ProcessReapError
        raise ProcessReapError("unowned Windows child could not be reaped") from error


def run_text_windows(request: object, validate: Callable, ledger_note: Callable):
    """Run one Windows child in a bounded, descendant-owning Job Object."""
    validate(request)
    ledger_note("intent", None, request.command)
    proc = subprocess.Popen(
        list(request.command), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=request.max_output_bytes is None,
        cwd=request.cwd, env=request.environment, close_fds=True)
    job = None
    try:
        job = _WindowsJob(proc)
        ledger_note("spawned", proc, request.command)
        output = (_capture(proc, request) if request.max_output_bytes is not None
                  else proc.communicate(request.stdin_text, timeout=request.timeout_seconds))
        job.terminate()
    except subprocess.TimeoutExpired as error:
        if job is not None:
            _stop(job, proc, request.termination_grace_seconds)
        ledger_note("reaped", proc, request.command)
        from .process_runner import ProcessDeadlineError
        raise ProcessDeadlineError("child process group exceeded its deadline") from error
    except BaseException:
        if job is not None:
            _stop(job, proc, request.termination_grace_seconds)
        else:
            _stop_after_setup_failure(proc, request.termination_grace_seconds)
        ledger_note("reaped", proc, request.command)
        raise
    finally:
        if job is not None:
            job.close()
    return subprocess.CompletedProcess(
        list(request.command), proc.returncode, output[0], output[1])
