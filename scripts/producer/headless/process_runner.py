"""Bounded text subprocesses with owned process-group cancellation and reap."""
from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass


class ProcessDeadlineError(RuntimeError):
    """A child group exceeded its deadline and was reaped."""


@dataclass(frozen=True)
class ProcessRequest:
    """Closed inputs for one secret-free text subprocess."""

    command: tuple[str, ...]
    stdin_text: str
    cwd: str
    environment: dict[str, str]
    timeout_seconds: float
    termination_grace_seconds: float = 1.0


def _validate(request: ProcessRequest) -> None:
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
            raise RuntimeError("child process group could not be reaped") from exc
    deadline = time.monotonic() + grace
    while _group_exists(group_id) and time.monotonic() < deadline:
        _signal_group(group_id, signal.SIGKILL)
        time.sleep(0.01)
    if _group_exists(group_id):
        raise RuntimeError("child process group remains after forced reap")


def _reap_success_descendants(proc: subprocess.Popen, grace: float) -> None:
    if _group_exists(proc.pid):
        _terminate_group(proc, grace)


def run_text(request: ProcessRequest) -> subprocess.CompletedProcess:
    """Run one child in a new session and reap its group on every interruption."""
    _validate(request)
    proc = subprocess.Popen(
        list(request.command), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, cwd=request.cwd,
        env=request.environment, close_fds=True, start_new_session=True)
    try:
        stdout, stderr = proc.communicate(
            request.stdin_text, timeout=request.timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        _terminate_group(proc, request.termination_grace_seconds)
        raise ProcessDeadlineError("child process group exceeded its deadline") from exc
    except BaseException:
        _terminate_group(proc, request.termination_grace_seconds)
        raise
    _reap_success_descendants(proc, request.termination_grace_seconds)
    return subprocess.CompletedProcess(
        list(request.command), proc.returncode, stdout, stderr)
