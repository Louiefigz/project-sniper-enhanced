"""Process lifetimes for production media work: exact identities, detached start, one instance, the export claim.

- The detached media dispatcher (``dispatch``) holds a private kernel lock as its single-instance
  guard (``hold_single_instance``, never waits) and records its exact identity: pid, process group
  and start time, so a reused PID never matches (``native_render_processes.identity_matches``).
- The public Short exporter always runs as the child of a non-heavy outer watchdog
  (``process_watch.supervise_export``, which holds no pool lease, reserves nothing and charges
  nothing). This module writes the child's claim (``write_claim``) and gives the child its side:
  ``supervised_claim``, the published launch grant (``publish_grant``) and a reservation refusal
  (``publish_refusal``), both files in the claim's private directory that only the watchdog reads.
- The exporter child checks its claim (``supervised_claim``): a private claim file naming its live
  parent by exact identity and the child's exact arguments, acknowledged once. A variable naming
  no such file is refused, so there is no flag that enters the internal path, and a supervised
  child never wraps itself again. **This is not authentication:** any process of the same user can
  write a claim naming itself and start the exporter as its own child; the claim proves only that
  the parent that wrote it is alive and supervising, not that it is the watchdog. What it rules
  out is an accidental or reused claim, a dead supervisor and a second child on one claim.
- If its watchdog dies (even by SIGKILL), the child sends itself SIGTERM within ``POLL_SECONDS``
  and, if it is still running ``STOP_GRACE_SECONDS`` later, SIGKILLs its own process group (a
  supervised child always leads its own group: the claim is refused otherwise).
"""
from __future__ import annotations

import fcntl
import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from cut_preview_io import write_new
from headless.durable_files import (
    DurableFileError, assert_private_lock_identity, open_private_dir, open_private_file, read_private_file,
)
from native_render_processes import ProcessIdentity, ResourceMeasurementError, identity_matches
from studio import native_budget_launch as launch
from studio.production.claims import ClaimRef
from studio.production.tasks import TASK_ID

EXPORTER = Path(__file__).resolve().parents[1] / 'native_short_export.py'
CLAIM_ENV = 'SNIPER_EXPORT_SUPERVISION'
CLAIM_KIND = 'native-export-supervision'
CLAIM, GRANT, REFUSAL, ACKNOWLEDGED = 'claim.json', 'grant.json', 'refusal.json', 'acknowledged'
LEDGER = 'owned-sessions.jsonl'   # headless.process_runner.LEDGER_ENV rows: own-session children
CLAIM_KEYS = frozenset({'schemaVersion', 'kind', 'watchdog', 'nonce', 'arguments', 'task'})
POLL_SECONDS = 1.0
STOP_GRACE_SECONDS = 45.0      # the cleanup reserve: owned cleanup after SIGTERM, then SIGKILL of the group
DEADLINE_GRACE_SECONDS = 15.0  # past the launch's granted deadline before the watchdog stops the export
REAP_SECONDS = 10.0
STOP_SIGNALS = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)
_HELD_LOCKS: list[int] = []      # single-instance locks, held until this process exits
_ACTIVE: list = []               # this process's verified supervision (a supervised exporter child only)


class InstanceBusy(RuntimeError):
    """Another live process holds this single-instance lock."""


class SupervisionRefused(RuntimeError):
    """The process presents no exact supervised claim; nothing starts."""


@dataclass(frozen=True)
class TaskClaim:
    """The claimed media task an exporter launch belongs to, and the SHA-256 of its kept request."""

    batch_id: str
    task_id: str
    epoch: int
    token: str
    request_sha256: str

    def ref(self) -> ClaimRef:
        """The fencing reference every callback carries."""
        return ClaimRef(self.task_id, self.epoch, self.token)

    def record(self) -> dict:
        """The claim as stored in the supervision file."""
        return {'batchId': self.batch_id, 'taskId': self.task_id, 'epoch': self.epoch, 'token': self.token,
                'requestSha256': self.request_sha256}


@dataclass(frozen=True)
class ExportLaunch:
    """One public export: its arguments, project (None when unknown before preparation) and task.

    ``script`` is the entry the watchdog starts as its child: None for the Short exporter
    (``EXPORTER``, read when the child starts), or the legacy ``resume_final_qc.py`` command.
    """

    arguments: tuple[str, ...]
    project: Path | None
    task: TaskClaim | None = None
    script: Path | None = None


@dataclass(frozen=True)
class Supervision:
    """A verified supervised child: its private claim directory and the task it runs for, if any."""

    directory: Path
    task: TaskClaim | None


def own_process() -> dict:
    """This process's exact handle {type, pid, pgid, started}."""
    return {'type': 'process', **launch.own_identity()}


def alive(identity: dict) -> bool | None:
    """Whether exactly this process (pid, group and start time) lives; None when the table is unreadable."""
    try:
        table = launch._process_table()
    except (OSError, subprocess.SubprocessError, ResourceMeasurementError):
        return None
    return identity_matches(table, ProcessIdentity(identity['pid'], identity['started'], identity['pgid']))


def hold_single_instance(directory: Path, name: str) -> None:
    """Hold a private kernel lock for the rest of this process, or raise InstanceBusy (never waits)."""
    dir_fd = open_private_dir(str(directory))
    try:
        fd = open_private_file(dir_fd, name, os.O_CREAT | os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            assert_private_lock_identity(dir_fd, name, fd)
        except BlockingIOError as error:
            os.close(fd)
            raise InstanceBusy(f'{directory / name} is held by another live process') from error
        except BaseException:
            os.close(fd)
            raise
    finally:
        os.close(dir_fd)
    _HELD_LOCKS.append(fd)


def spawn_detached(command: list[str], log: Path) -> subprocess.Popen:
    """Start a command in its own session (it outlives this process); its output is appended to ``log``."""
    fd = os.open(log, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        return subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=fd, stderr=fd, start_new_session=True,
                                close_fds=True)
    finally:
        os.close(fd)


class _Stops:
    """Why this process was asked to stop (set by a signal handler), or None."""

    reason: str | None = None


@contextmanager
def stop_requests() -> Iterator[_Stops]:
    """Turn SIGTERM, SIGINT and SIGHUP into a recorded stop request; restore the handlers afterwards."""
    stops = _Stops()

    def request_stop(number: int, _frame: object) -> None:
        """Record the first stop request."""
        stops.reason = stops.reason or f'received {signal.Signals(number).name}'
    previous = {number: signal.signal(number, request_stop) for number in STOP_SIGNALS}
    try:
        yield stops
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


@contextmanager
def interrupt_on_termination() -> Iterator[None]:
    """SIGTERM becomes KeyboardInterrupt, so preparation and native owners run their own cleanup."""
    def raise_interrupt(number: int, _frame: object) -> None:
        """Interrupt the running export at its current bytecode."""
        raise KeyboardInterrupt(f'the export watchdog sent {signal.Signals(number).name}')
    previous = signal.signal(signal.SIGTERM, raise_interrupt)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def _task(raw: object) -> TaskClaim | None:
    """The typed task claim of a supervision file (None for an export that belongs to no task)."""
    if raw is None:
        return None
    keys = ('batchId', 'taskId', 'token', 'requestSha256')
    if type(raw) is not dict or set(raw) != {*keys, 'epoch'} or not all(type(raw[key]) is str for key in keys) \
            or TASK_ID.fullmatch(raw['taskId']) is None or type(raw['epoch']) is not int or raw['epoch'] < 1:
        raise SupervisionRefused('the supervised claim names a malformed task claim')
    return TaskClaim(raw['batchId'], raw['taskId'], raw['epoch'], raw['token'], raw['requestSha256'])


def _read_claim(path: Path) -> tuple[dict, Path]:
    """The claim file: owned, private, single-link, inside a private canonical directory, closed shape."""
    if not path.is_absolute() or path.name != CLAIM:
        raise SupervisionRefused(f'{CLAIM_ENV} does not name a supervision claim file')
    try:
        dir_fd = open_private_dir(str(path.parent))
        try:
            claim = json.loads(read_private_file(dir_fd, CLAIM, 64 * 1024).decode('utf-8'))
        finally:
            os.close(dir_fd)
    except (DurableFileError, OSError, UnicodeError, ValueError) as error:
        raise SupervisionRefused(f'the supervision claim is unreadable: {error}') from error
    if type(claim) is not dict or set(claim) != CLAIM_KEYS or claim['schemaVersion'] != 1 \
            or claim['kind'] != CLAIM_KIND or type(claim['arguments']) is not list \
            or type(claim['watchdog']) is not dict or set(claim['watchdog']) != {'type', 'pid', 'pgid', 'started'}:
        raise SupervisionRefused('the supervision claim does not have the closed claim shape')
    return claim, path.parent


def _acknowledge(directory: Path) -> None:
    """Consume the claim: exactly one process may ever acknowledge it."""
    try:
        fd = os.open(directory / ACKNOWLEDGED, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError as error:
        raise SupervisionRefused('this supervision claim was already acknowledged by another process') from error
    with os.fdopen(fd, 'w') as handle:
        handle.write(str(os.getpid()))


def supervised_claim() -> Supervision | None:
    """This process's exact supervised claim; None when no claim is named (the caller then supervises).

    Refused (``SupervisionRefused``): a named file that is not a private claim, a watchdog that is
    not this process's live parent by exact identity, other arguments, or a claim already used.
    """
    value = os.environ.get(CLAIM_ENV)
    if value is None:
        return None
    claim, directory = _read_claim(Path(value))
    watchdog = claim['watchdog']
    if os.getppid() != watchdog['pid'] or alive(watchdog) is not True:
        raise SupervisionRefused('the supervision claim does not name this process\'s live watchdog')
    if os.getpgrp() != os.getpid():
        raise SupervisionRefused('a supervised exporter leads its own process group (the watchdog starts it in '
                                 'its own session)')
    if claim['arguments'] != sys.argv[1:]:
        raise SupervisionRefused('the supervision claim names other exporter arguments')
    task = _task(claim['task'])
    _acknowledge(directory)
    os.environ.pop(CLAIM_ENV, None)
    supervision = Supervision(directory, task)
    _ACTIVE[:] = [supervision]
    _stop_when_orphaned(watchdog['pid'])
    return supervision


def _stop_when_orphaned(watchdog: int) -> None:
    """An export never runs unsupervised: when its watchdog dies it stops itself (SIGTERM, owned cleanup),
    and if that cleanup has not ended it after the grace, SIGKILLs its own process group."""
    def watch() -> None:
        """Poll the parent; a reparented child has lost its watchdog."""
        while os.getppid() == watchdog:
            time.sleep(POLL_SECONDS)
        os.kill(os.getpid(), signal.SIGTERM)
        time.sleep(STOP_GRACE_SECONDS)
        os.killpg(os.getpid(), signal.SIGKILL)   # its own group: supervised_claim admits only a group leader
    threading.Thread(target=watch, daemon=True, name='sniper-export-watchdog-parent').start()


def publish_grant(budget: dict | None) -> None:
    """Tell the outer watchdog this launch's granted deadline (a supervised, budgeted child only)."""
    if budget and _ACTIVE:
        write_new(_ACTIVE[0].directory / GRANT, budget['allocation'])


def publish_refusal(reason: str) -> None:
    """Tell the outer watchdog the budget refused this task's launch (it settles the task with it)."""
    if _ACTIVE:
        write_new(_ACTIVE[0].directory / REFUSAL, {'reason': reason[:512]})


def write_claim(directory: Path, launch_spec: ExportLaunch) -> Path:
    """Write the one-use supervision claim for this watchdog's exporter child; returns its path."""
    write_new(directory / CLAIM, {'schemaVersion': 1, 'kind': CLAIM_KIND, 'watchdog': own_process(),
                                  'nonce': uuid.uuid4().hex, 'arguments': list(launch_spec.arguments),
                                  'task': launch_spec.task.record() if launch_spec.task else None})
    return directory / CLAIM
