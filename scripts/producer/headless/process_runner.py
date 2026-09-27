"""Bounded text subprocesses with owned process-group cancellation and reap."""
from __future__ import annotations

import fcntl
import json
import os
import runpy
import selectors
import signal
import stat
import subprocess
import sys
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator

# When the owning controller names a ledger file, every child this runner starts in its
# own session is recorded there (spawned/reaped rows). Those sessions are outside the
# controller's process group, so after an EXTERNAL kill of the worker the controller can
# check exact recorded pids (with start time and argv[0]) instead of guessing.
LEDGER_ENV = "SNIPER_OWNED_PROCESS_LEDGER"


class ProcessDeadlineError(RuntimeError):
    """A child group exceeded its deadline and was reaped."""


class ProcessOutputLimitError(RuntimeError):
    """A byte-capped child exceeded its combined output bound and was reaped."""


class ProcessReapError(RuntimeError):
    """A child process group could not be proved gone after forced termination."""


def _ledger_note(event: str, proc: subprocess.Popen | None, command: tuple[str, ...]) -> None:
    """Append one exact owned-process row when a ledger was declared; a failed write raises.

    ``intent`` is written BEFORE the child exists (no pid yet): an intent with no
    later ``spawned`` row means the worker died between fork and record, and the
    controller must treat that child as unresolved rather than absent.
    """
    path = os.environ.get(LEDGER_ENV)
    if not path:
        return
    owner = event in {"worker-started", "worker-finished"}
    row = {"event": event, "pid": os.getpid() if owner else proc.pid if proc else None, "argv0": command[0],
           "at": time.time(), "returncode": proc.returncode if proc else None}
    data = (json.dumps(row, sort_keys=True) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_APPEND | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
    flags |= os.O_CREAT | os.O_EXCL if event == "worker-started" else os.O_CREAT
    handle = os.open(path, flags, 0o600)
    try:
        info = os.fstat(handle)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
            raise RuntimeError("owned process ledger must be one owned regular file")
        if os.write(handle, data) != len(data):
            raise RuntimeError("owned process ledger row write was incomplete")
        os.fsync(handle)
    finally:
        os.close(handle)


@dataclass(frozen=True)
class ProcessRequest:
    """Closed inputs for one secret-free text subprocess."""

    command: tuple[str, ...]
    stdin_text: str
    cwd: str
    environment: dict[str, str]
    timeout_seconds: float
    termination_grace_seconds: float = 1.0
    max_output_bytes: int | None = None
    pass_fds: tuple[int, ...] = ()  # Internal output capabilities; caller retains closing ownership.
    decode_output: bool = True  # False returns bounded stdout/stderr as bytes (byte-capped runs only).


def _validate_pass_fds(descriptors: tuple[int, ...]) -> None:
    """Admit only bounded, live, owned, single-link regular output descriptors."""
    if type(descriptors) is not tuple or len(descriptors) > 4 \
            or any(type(value) is not int or value <= 2 for value in descriptors) \
            or len(set(descriptors)) != len(descriptors):
        raise RuntimeError("passed output descriptors must be at most four unique integers above stdio")
    for descriptor in descriptors:
        try:
            info = os.fstat(descriptor)
            access = fcntl.fcntl(descriptor, fcntl.F_GETFL) & os.O_ACCMODE
        except OSError as error:
            raise RuntimeError("passed output descriptor is not open") from error
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid() \
                or access not in {os.O_WRONLY, os.O_RDWR}:
            raise RuntimeError("passed descriptor must be an owned single-link regular writable output")


def _validate(request: ProcessRequest) -> None:
    _validate_pass_fds(request.pass_fds)
    if request.max_output_bytes is not None and (
            type(request.max_output_bytes) is not int
            or not 0 < request.max_output_bytes <= 16 * 1024 * 1024
            or request.stdin_text != ""):
        raise RuntimeError("bounded process requires empty stdin and a valid byte cap")
    if request.decode_output is not True and (request.decode_output is not False or request.max_output_bytes is None):
        raise RuntimeError("undecoded output requires a byte-capped process")
    command_ok = (request.command and all(isinstance(item, str) and item
                                          for item in request.command)
                  and os.path.isabs(request.command[0]))
    environment_ok = all(isinstance(key, str) and isinstance(value, str)
                         for key, value in request.environment.items())
    if (not command_ok or not isinstance(request.stdin_text, str)
            or not os.path.isabs(request.cwd) or not os.path.isdir(request.cwd)
            or not environment_ok or not 0 < request.timeout_seconds <= 3600
            or not 0 < request.termination_grace_seconds <= 10):
        raise RuntimeError("process request is invalid")


def _signal_group(group_id: int, value: signal.Signals) -> None:
    try:
        os.killpg(group_id, value)
    except ProcessLookupError:
        pass
    except PermissionError:
        pass


def _group_exists(group_id: int) -> bool:
    try:
        os.killpg(group_id, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _terminate_group(proc: subprocess.Popen, grace: float) -> None:
    group_id = proc.pid
    _signal_group(group_id, signal.SIGTERM)
    try:
        proc.communicate(timeout=grace)
    except subprocess.TimeoutExpired:
        _signal_group(group_id, signal.SIGKILL)
        try:
            proc.communicate(timeout=grace)
        except subprocess.TimeoutExpired as exc:
            raise ProcessReapError("child process group could not be reaped") from exc
    deadline = time.monotonic() + grace
    while _group_exists(group_id) and time.monotonic() < deadline:
        _signal_group(group_id, signal.SIGKILL)
        time.sleep(0.01)
    if _group_exists(group_id):
        raise ProcessReapError("child process group remains after forced reap")


def _reap_success_descendants(proc: subprocess.Popen, grace: float) -> None:
    if _group_exists(proc.pid):
        _terminate_group(proc, grace)


def _capture_chunk(selector: selectors.BaseSelector, event: selectors.SelectorKey,
                   output: dict, maximum: int) -> None:
    """Check aggregate bytes before append; never truncate into valid-looking text."""
    data = os.read(event.fileobj.fileno(), 65536)
    if not data:
        selector.unregister(event.fileobj)
        return
    if sum(len(value) for value in output.values()) + len(data) > maximum:
        raise ProcessOutputLimitError("child process exceeded its output byte bound")
    output[event.data].extend(data)


def _close_capture_pipes(proc: subprocess.Popen) -> None:
    """Cancellation must not call communicate on still-unbounded output pipes."""
    for name in ("stdin", "stdout", "stderr"):
        stream = getattr(proc, name)
        if stream is not None:
            stream.close()
            setattr(proc, name, None)


def _capture_bounded(proc: subprocess.Popen, request: ProcessRequest) -> tuple[str | bytes, str | bytes]:
    """Drain both pipes under one deadline; decode UTF-8 only after full capture."""
    deadline = time.monotonic() + request.timeout_seconds
    output = {"stdout": bytearray(), "stderr": bytearray()}
    try:
        proc.stdin.close()
        proc.stdin = None
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ, "stdout")
            selector.register(proc.stderr, selectors.EVENT_READ, "stderr")
            _capture_events(selector, proc, request, (deadline, output))
        if not request.decode_output:
            return bytes(output["stdout"]), bytes(output["stderr"])
        return tuple(bytes(output[name]).decode("utf-8") for name in ("stdout", "stderr"))
    finally:
        _close_capture_pipes(proc)


def _capture_events(selector: selectors.BaseSelector, proc: subprocess.Popen,
                    request: ProcessRequest, state: tuple[float, dict]) -> None:
    """Bound EOF/leader waiting as well as active output; siblings cannot hold pipes forever."""
    deadline, output = state
    while selector.get_map():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(request.command, request.timeout_seconds)
        for event, _mask in selector.select(min(remaining, 0.1)):
            _capture_chunk(selector, event, output, request.max_output_bytes)
    proc.wait(timeout=max(0.001, deadline - time.monotonic()))
    if time.monotonic() >= deadline:
        raise subprocess.TimeoutExpired(request.command, request.timeout_seconds)


def run_text(request: ProcessRequest) -> subprocess.CompletedProcess:
    """Run one child in a new session and reap its group on every interruption."""
    _validate(request)
    _ledger_note("intent", None, request.command)
    proc = subprocess.Popen(
        list(request.command), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, cwd=request.cwd,
        env=request.environment, close_fds=True, start_new_session=True,
        pass_fds=request.pass_fds)
    try:
        _ledger_note("spawned", proc, request.command)
        stdout, stderr = (_capture_bounded(proc, request)
            if request.max_output_bytes is not None else proc.communicate(
                request.stdin_text, timeout=request.timeout_seconds))
    except subprocess.TimeoutExpired as exc:
        _terminate_group(proc, request.termination_grace_seconds)
        _ledger_note("reaped", proc, request.command)
        raise ProcessDeadlineError("child process group exceeded its deadline") from exc
    except BaseException:
        _terminate_group(proc, request.termination_grace_seconds)
        _ledger_note("reaped", proc, request.command)
        raise
    _reap_success_descendants(proc, request.termination_grace_seconds)
    _ledger_note("reaped", proc, request.command)
    return subprocess.CompletedProcess(
        list(request.command), proc.returncode, stdout, stderr)


def run_owned_script(arguments: list[str]) -> None:
    """Record a real owner lifecycle even when no detached helper is invoked.

    The controller separately holds the returned ledger bytes. Abrupt death has
    no finished row; an absent or truncated ledger never proves no child ran.
    """
    if not arguments or not os.path.isabs(arguments[0]):
        raise RuntimeError("owned worker script must be absolute")
    ledger = os.environ.get(LEDGER_ENV)
    if not ledger or not os.path.isabs(ledger) or os.path.realpath(ledger) != ledger:
        raise RuntimeError("owned worker ledger path must be explicit and canonical")
    command = (arguments[0],)
    _ledger_note("worker-started", None, command)
    sys.argv = arguments
    sys.path.insert(0, os.path.dirname(arguments[0]))
    try:
        runpy.run_path(arguments[0], run_name="__main__")
    finally:
        _ledger_note("worker-finished", None, command)


class ProcessDeadlinePolicyError(RuntimeError):
    """A caller supplied an invalid shared subprocess budget policy."""


_ACTIVE_DEADLINE: ContextVar[Any | None] = ContextVar("producer_process_deadline", default=None)


@contextmanager
def use_process_deadline(deadline: Any) -> Iterator[None]:
    """Expose one caller's remaining budget to nested producer subprocesses."""
    if not callable(getattr(deadline, "remaining", None)):
        raise ProcessDeadlinePolicyError("subprocess deadline has no remaining-time clock")
    token = _ACTIVE_DEADLINE.set(deadline)
    try:
        yield
    finally:
        _ACTIVE_DEADLINE.reset(token)


def process_timeout(default_s: float = 300.0) -> float:
    """Cap the subprocess timeout at the active budget without creating a new clock."""
    if default_s <= 0:
        raise ProcessDeadlinePolicyError("subprocess timeout must be positive")
    active = _ACTIVE_DEADLINE.get()
    remaining = active.remaining() if active is not None else float(default_s)
    return max(0.001, min(float(default_s), float(remaining)))


if __name__ == "__main__":
    run_owned_script(sys.argv[1:])
