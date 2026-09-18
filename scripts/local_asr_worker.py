"""Explicit local-ASR leaves inside one parent-owned worker process group.

Ordinary calls retain the existing separate-session runner. Only a worker
launched as its own session/group leader may enter the private context below.
Shared leaves do not claim descendant quiescence: the outer ``run_text`` owner
must stop/reap the complete worker group on success, error and cancellation.
No environment variable enables this mode or authorizes a provider.
"""
from __future__ import annotations

import os
import subprocess
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from producer.headless.process_runner import (
    ProcessDeadlineError, ProcessRequest, _capture_bounded, _validate, run_text,
)

_WORKER: ContextVar[int | None] = ContextVar("local_asr_worker_group", default=None)


def _worker_identity() -> int:
    """Require this exact process to lead its own session and process group."""
    try:
        identity = (os.getpid(), os.getpgrp(), os.getsid(0))
    except (AttributeError, OSError) as error:
        raise RuntimeError("local ASR worker group cannot be verified") from error
    if identity[0] <= 1 or len(set(identity)) != 1:
        raise RuntimeError("local ASR owned worker must be its session and group leader")
    return identity[0]


@contextmanager
def use_local_asr_worker_group() -> Iterator[None]:
    """Enter explicit private ownership; never activate via ambient environment."""
    if _WORKER.get() is not None:
        raise RuntimeError("local ASR worker group context cannot be nested")
    token = _WORKER.set(_worker_identity())
    try:
        yield
    finally:
        _WORKER.reset(token)


def _assert_worker(expected: int) -> None:
    """An inherited context after fork cannot authorize a different process."""
    if _worker_identity() != expected:
        raise RuntimeError("local ASR worker group ownership changed")


def _stop_leaf(proc: subprocess.Popen, grace: float) -> None:
    """Stop only the direct child; the outer owner cleans the shared group."""
    try:
        proc.terminate()
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=grace)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        proc.kill()
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("local ASR direct child could not be reaped; outer cleanup required") from error


def _run_shared(request: ProcessRequest, worker: int) -> subprocess.CompletedProcess:
    """Bound output and direct-child lifetime without signalling our own group."""
    _assert_worker(worker)
    _validate(request)
    if request.max_output_bytes is None or request.stdin_text != "":
        raise RuntimeError("local ASR shared leaf requires empty stdin and bounded output")
    proc = subprocess.Popen(list(request.command), stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        cwd=request.cwd, env=request.environment, close_fds=True,
        start_new_session=False, pass_fds=request.pass_fds)
    try:
        stdout, stderr = _capture_bounded(proc, request)
        _assert_worker(worker)
    except subprocess.TimeoutExpired as error:
        _stop_leaf(proc, request.termination_grace_seconds)
        raise ProcessDeadlineError("local ASR leaf exceeded its deadline; outer cleanup required") from error
    except BaseException:
        _stop_leaf(proc, request.termination_grace_seconds)
        raise
    return subprocess.CompletedProcess(list(request.command), proc.returncode, stdout, stderr)


def run_local_asr_leaf(request: ProcessRequest) -> subprocess.CompletedProcess:
    """Use ordinary ownership unless an explicit verified worker scope is active."""
    worker = _WORKER.get()
    return run_text(request) if worker is None else _run_shared(request, worker)
