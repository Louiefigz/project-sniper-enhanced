"""The outer export watchdog: one supervised exporter child, always under a deadline, settled once.

``supervise_export`` is how a public Short export runs (``native_short_export.main``, which
``native_export.py`` forwards to, ``native_batch.py run-media`` and the legacy
``resume_final_qc.py``). The watchdog holds no pool lease, reserves nothing and charges nothing.
It starts the exporter in its own session with a one-use claim (``process.write_claim``) and the
owned-session ledger variable, relays its output (at most ``OUTPUT_LIMIT_BYTES``), and watches:

- the deadline, which always exists, and is a Short's (another format's project is refused). A
  task's or a bound project's batch gives its delivery deadline
  until the child publishes its launch grant (then that grant plus ``DEADLINE_GRACE_SECONDS``); an
  unreadable authority refuses the export (fail closed). An unbound export is a **declared one-output
  run**: this one output directory, with a grant of ``ONE_OUTPUT_SECONDS`` that the watchdog writes
  before the child starts;
- a stop request for its task, the acknowledgement deadline (``ACK_SECONDS`` after the child
  started with no acknowledgement) and its own interruption.
Any of them stops the child (SIGTERM, the cleanup grace). Whenever the child ended, its group and
recorded sessions are ended (``process_group.end_group``) before the task is settled once
(``process_settle``).
"""
from __future__ import annotations

import json
import os
import selectors
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from cut_preview_io import bound_json, write_new
from headless.process_runner import LEDGER_ENV
from studio import native_budget_store as store
from studio.native_budget_batches import BudgetRefused
from studio.native_budget_clock import BudgetClockError, ClockAnchor, allocation, allocation_remaining, observe
from studio.native_budget_clock import start_anchor
from studio.native_budget_registry import owner_binding
from studio.native_budget_store import BudgetAuthorityError
from studio.native_export import export_adapter
from studio.production import process, process_group
from studio.production.process import ExportLaunch, TaskClaim
from studio.production.process_settle import STOP_REQUESTED, UNACKNOWLEDGED, Ending, settle

DEADLINE, INTERRUPTED = 'watchdog-deadline', 'watchdog-interrupted'
ONE_OUTPUT_SECONDS = 3600.0
ACK_SECONDS = 60.0
OUTPUT_LIMIT_BYTES = 4 * 1024 ** 2
REFUSED_EXIT = 3


class ExportRefused(RuntimeError):
    """The watchdog cannot bound this export (its authority is unreadable); nothing starts."""


@dataclass(frozen=True)
class ExportWatch:
    """What the watchdog enforces: the task, claim directory, deadline and when the child started."""

    task: TaskClaim | None
    directory: Path
    deadline: dict
    started: float
    since: float


def run_deadline(spec: ExportLaunch) -> tuple[dict, bool]:
    """(deadline allocation, declared one-output run?) for this export; refuses when it cannot tell.

    Every deadline here is a Short's: a project that declares another format is refused (a Long's
    deadline and one-output run come from its own format rules, which this engine does not have).
    """
    try:
        root = store.default_root()
        if spec.project is not None and export_adapter(spec.project.resolve(strict=True)) != 'native-short':
            raise ValueError(f'{spec.project} is not a native Short: the Short export watchdog applies only Short '
                             'deadlines')
        binding = None if spec.task or spec.project is None else owner_binding(root, spec.project.resolve(strict=True))
        batch_id = spec.task.batch_id if spec.task else binding['batchId'] if binding and \
            binding['status'] != 'closed' else None
        if batch_id is None:
            return allocation(start_anchor(), ONE_OUTPUT_SECONDS, 0.0), True
        record = store.read_batch(root, batch_id)
        anchor = observe(ClockAnchor.from_record(record['clock']), record['startEpoch'])
        return _bound_deadline(spec, root, (record, anchor), binding)
    except (BudgetAuthorityError, BudgetClockError, BudgetRefused, OSError, ValueError, KeyError,
            RuntimeError) as error:
        raise ExportRefused(f'the export deadline cannot be established: {type(error).__name__}: {error}') from error


def _bound_deadline(spec: ExportLaunch, root: Path, state: tuple, binding: dict | None) -> tuple[dict, bool]:
    """Build the exact clip/task allocation inside the caller's refusal boundary."""
    record, anchor = state
    from studio.production.formats import clip_deadlines
    from studio.production.queue_authority import bind_allocation
    clip_id = record['production']['tasks'][spec.task.task_id]['clipId'] if spec.task else binding['clipId']
    deadline = clip_deadlines(record, record['clips'][clip_id])['deliverySeconds']
    if spec.task:
        from studio.production.queue_clock import task_deadline
        deadline = min(deadline, task_deadline(record, record['production']['tasks'][spec.task.task_id]))
    grant = allocation(anchor, deadline - anchor.elapsed, 0.0)
    return bind_allocation(grant, record, {'authority': str(root), 'batchId': record['batchId'], 'clipId': clip_id}), False


def read_grant(directory: Path) -> dict | None:
    """The launch grant the child (or, for a one-output run, the watchdog) published, or None."""
    file = directory / process.GRANT
    if not file.is_file():
        return None
    try:
        grant = bound_json(file, maximum=4096)
        allocation_remaining(grant)
    except (OSError, RuntimeError, KeyError, TypeError, ValueError) as error:
        raise ExportRefused(f'The published export grant is unreadable: {error}') from error
    return grant


def _task_row(task: TaskClaim) -> dict | None:
    """The task's row, read without writing; None when unreadable."""
    try:
        return store.read_batch(store.default_root(), task.batch_id)['production']['tasks'].get(task.task_id)
    except (BudgetAuthorityError, OSError, ValueError):
        return None


def _reason(watch: ExportWatch, stops: object) -> tuple[str, str] | None:
    """Why the child must stop now, or None."""
    if stops.reason:
        return INTERRUPTED, f'the watchdog {stops.reason}'
    grant = read_grant(watch.directory)
    remaining = allocation_remaining(watch.deadline)
    if grant:
        remaining = min(remaining, allocation_remaining(grant) + process.DEADLINE_GRACE_SECONDS)
    if remaining <= 0:
        return DEADLINE, 'the export ran past its launch grant' if grant else 'the export ran past its batch deadline'
    row = _task_row(watch.task) if watch.task else None
    if watch.task and row is None:
        return 'watchdog-authority-unavailable', 'the task authority is unreadable'
    if row is not None and ((row.get('claim') or {}).get('epoch'), (row.get('claim') or {}).get('token')) \
            != (watch.task.epoch, watch.task.token):
        return STOP_REQUESTED, 'the export no longer owns the current task claim'
    if row is not None and (row['state'] == 'cancel-requested' or row.get('revoked') or row.get('approvalStale')):
        return STOP_REQUESTED, f'task {watch.task.task_id} was asked to stop'
    if row is not None and row['handle'] is None and time.monotonic() - watch.started > ACK_SECONDS:
        return UNACKNOWLEDGED, f'the exporter did not acknowledge its claim within {ACK_SECONDS:.0f} s; nothing ran'
    return None


class OutputRelay:
    """The child's stdout and stderr copied to this process's, at most ``OUTPUT_LIMIT_BYTES`` in all."""

    def __init__(self, child: subprocess.Popen) -> None:
        """Watch both pipes of ``child``."""
        self.selector, self.written, self.cut = selectors.DefaultSelector(), 0, False
        for pipe, target in ((child.stdout, sys.stdout), (child.stderr, sys.stderr)):
            os.set_blocking(pipe.fileno(), False)
            self.selector.register(pipe, selectors.EVENT_READ, target)

    def pump(self, timeout: float) -> None:
        """Copy what the child wrote within ``timeout`` seconds (bounded); with both pipes closed, just wait."""
        if not self.selector.get_map():
            time.sleep(timeout)
            return
        for key, _mask in self.selector.select(timeout):
            chunk = os.read(key.fileobj.fileno(), 65536)
            if not chunk:
                self.selector.unregister(key.fileobj)
                continue
            self._write(key.data, chunk)

    def _write(self, target: object, chunk: bytes) -> None:
        """Forward what fits under the bound; past it, one marker and nothing more."""
        kept = chunk[:max(OUTPUT_LIMIT_BYTES - self.written, 0)]
        binary = getattr(target, 'buffer', None)
        if kept and binary is None:
            target.write(kept.decode('utf-8', errors='replace'))
        elif kept:
            binary.write(kept)
        target.flush()
        self.written += len(kept)
        if len(kept) < len(chunk) and not self.cut:
            self.cut = True
            sys.stderr.write(f'[export output past {OUTPUT_LIMIT_BYTES} bytes is not shown]\n')

    def drain(self) -> None:
        """Copy what is left once the child's group has ended (bounded: the pipes close with it)."""
        deadline = time.monotonic() + process.REAP_SECONDS
        while self.selector.get_map() and time.monotonic() < deadline:
            self.pump(0.2)
        for key in list(self.selector.get_map().values()):
            self.selector.unregister(key.fileobj)
            key.fileobj.close()


def watch_child(child: subprocess.Popen, watch: ExportWatch, stops: object, relay: OutputRelay) -> tuple | None:
    """Wait for the child (never reaping it); stop it on a deadline, stop request, missing acknowledgement
    or interruption. Returns why it was stopped, or None when it ended by itself."""
    while not process_group.exited(child.pid):
        relay.pump(process.POLL_SECONDS)
        reason = _reason(watch, stops)
        if reason:
            process_group.terminate(child, relay.pump)
            return reason
    return None


def exit_code(code: int | None) -> int:
    """A process exit status as a shell exit code (signal N becomes 128 + N)."""
    if code is None:
        return 1
    return 128 - code if code < 0 else code


def _start_child(spec: ExportLaunch, claim: Path, watch: ExportWatch) -> subprocess.Popen:
    """Start the exporter in its own session; a failed start settles the task (nothing ran) and raises."""
    environment = {**os.environ, process.CLAIM_ENV: str(claim), LEDGER_ENV: str(watch.directory / process.LEDGER)}
    try:
        return subprocess.Popen([sys.executable, '-B', str(spec.script or process.EXPORTER), *spec.arguments],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=True, env=environment)
    except OSError as error:
        if spec.task:
            settle(spec.task, Ending(None, ('export-spawn-failed', f'the exporter could not start: {error}'), (), None))
        raise


def _refusal(directory: Path) -> str | None:
    """The reservation refusal the child published, if any."""
    file = directory / process.REFUSAL
    return bound_json(file, maximum=4096).get('reason') if file.is_file() else None


def _supervised_end(child: subprocess.Popen, watch: ExportWatch, stops: object) -> Ending:
    """Always clean the child and recorded sessions, including an unexpected monitor failure."""
    relay = None
    reason = None
    try:
        relay = OutputRelay(child)
        reason = watch_child(child, watch, stops, relay)
    except Exception as error:  # a failed monitor must stop the work it can no longer supervise
        reason = ('watchdog-error', f'{type(error).__name__}: {error}')
    finally:
        survivors = process_group.end_group(child, watch.directory, watch.since)
    try:
        if relay is not None:
            relay.drain()
        refusal = _refusal(watch.directory)
    except (OSError, RuntimeError, ValueError) as error:
        reason = reason or ('watchdog-evidence-error', f'{type(error).__name__}: {error}')
        refusal = None
    return Ending(child.pid, reason, tuple(survivors), refusal)


def _refuse(spec: ExportLaunch, error: ExportRefused) -> int:
    """Refuse an export whose deadline cannot be established; its task fails (nothing ran)."""
    print(json.dumps({'status': 'refused-by-export-watchdog', 'reason': str(error), 'childLaunched': False}),
          flush=True)
    if spec.task:
        settle(spec.task, Ending(None, ('export-refused', str(error)), (), None))
    return REFUSED_EXIT


def supervise_export(spec: ExportLaunch) -> int:
    """Run the export as this watchdog's supervised child for its whole lifetime; return its exit code."""
    try:
        deadline, declared = run_deadline(spec)
    except ExportRefused as error:
        return _refuse(spec, error)
    directory = Path(tempfile.mkdtemp(prefix='sniper-export-')).resolve()
    removable = False
    try:
        claim = process.write_claim(directory, spec)
        if declared:
            write_new(directory / process.GRANT, deadline)   # the declared one-output run's grant
        watch = ExportWatch(spec.task, directory, deadline, time.monotonic(), time.time())
        with process.stop_requests() as stops:
            child = _start_child(spec, claim, watch)
            ending = _supervised_end(child, watch, stops)
        settled = settle(spec.task, ending) if spec.task else None
        removable = not ending.survivors
        if ending.reason or ending.survivors:
            print(json.dumps({'status': 'stopped-by-export-watchdog' if ending.reason else 'export-left-processes',
                              'category': ending.reason[0] if ending.reason else None,
                              'reason': ending.reason, 'survivors': ending.survivors,
                              'childExitCode': child.returncode, 'task': settled,
                              'recoveryDirectory': str(directory) if not removable else None}), flush=True)
        return exit_code(child.returncode) or (1 if ending.reason or ending.survivors else 0)
    finally:
        if removable:
            shutil.rmtree(directory, ignore_errors=True)
        else:
            print(f'Export supervision evidence retained at {directory}', file=sys.stderr, flush=True)
