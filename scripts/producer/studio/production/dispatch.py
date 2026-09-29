#!/usr/bin/env python3
"""The detached, single-instance media dispatcher of one production batch.

``start`` launches it in its own session (it outlives the command and the conversation that ran it)
and waits, bounded, for its readiness record. It takes no heavy or audio pool lease and runs no
media. Each poll it reconciles the authority (one process-table read, under the batch lock), then
claims admissible ready media tasks, least task deadline first (``dependencies.ready_order``),
within its bounded supervisor count. Real render capacity is acquired by each native owner, as its
own exact identity, and starts ``native_batch.py run-media`` for each claim. That command's export
watchdog starts the public exporter, whose child alone acknowledges the claim, reserves and is
charged; the watchdog settles the task once. The dispatcher holds a private kernel lock (one per
batch) and the install's maintenance lock (shared) for its lifetime, keeps a bounded log, and exits
once the batch stops admitting work, every clip is handed off, or the delivery deadline passed and
its launches ended (bounded by ``CLEANUP_WINDOW_SECONDS``).

It refuses to start, and a started one exits with the reason, when this checkout's engine is not
the engine the batch froze (``engine_refusal``). An unexpected error while launching or settling one
task fails only that task, by name (``dispatcher-error``); any other unexpected error ends the
dispatcher with a named exit record, never silently.

If it dies, durable intent survives: a claim no child acknowledged is fenced by ``reconcile`` and
stays uncertain (never relaunched); acknowledged exports continue under their own watchdogs; a
restarted dispatcher reconciles before it claims. A claim whose ``run-media`` ended unacknowledged
and unsettled fails (nothing ran). No relaunch across a reboot, and no AI work: the host capability
gate failed, so AI tasks stay with the coordinator under supervised mode.

  dispatch.py run --batch ID     (started by ``native_batch.py dispatch``; one per batch)
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

if __name__ == '__main__':
    sys.path[0] = str(Path(__file__).resolve().parents[2])  # run as a script: import from scripts/producer

from headless.durable_files import DurableFileError  # noqa: E402
from studio import native_budget_engine  # noqa: E402
from studio import native_budget_store as store  # noqa: E402
from studio.native_budget_binding import REPO, advance_clock  # noqa: E402
from studio.native_budget_clock import BudgetClockError  # noqa: E402
from studio.native_budget_store import BudgetAuthorityError  # noqa: E402
from studio.production import api, media, process  # noqa: E402
from studio.production.callbacks import TaskFailure  # noqa: E402
from studio.production.claims import ClaimRef, claim_refusal  # noqa: E402
from studio.production.dependencies import ready_order  # noqa: E402
from studio.production.dispatch_state import (  # noqa: E402,F401  (status: the dispatcher's public reading)
    LOCK, LOG, BoundedLog, busy_slots, engine_refusal, status, utc, write_identity)
from studio.production.host_contract import clip_text  # noqa: E402
from studio.production.tasks import TaskRefused
from studio.production.formats import run_deadlines  # noqa: E402

PRODUCER = Path(__file__).resolve().parents[2]
APP_ROOT = PRODUCER.parents[1]
RUN_SELF = [sys.executable, '-B', str(Path(__file__).resolve())]
RUN_MEDIA = [sys.executable, '-B', str(PRODUCER / 'native_batch.py'), 'run-media']
POLL_SECONDS = 2.0
STARTUP_SECONDS = 20.0
CLEANUP_WINDOW_SECONDS = 180.0
BUSY_EXIT, REFUSED_EXIT = 75, 3
DISPATCHER_ERROR = 'dispatcher-error'
EXPECTED = (TaskRefused, BudgetAuthorityError, DurableFileError, OSError, ValueError)


def start(root: Path, batch_id: str) -> dict:
    """Start the batch's dispatcher detached, or report the one already running (never a second)."""
    record = store.read_batch(root, batch_id)
    if record['status'] != 'active':
        raise TaskRefused(f'Batch {batch_id} is {record["status"]}: no media task is dispatched')
    refusal = engine_refusal(record, native_budget_engine.engine_identity(REPO))
    if refusal:
        raise TaskRefused(refusal)
    current = status(root, batch_id)
    if current['running']:
        return {'status': 'already-running', **current}
    directory = media.batch_state(root, batch_id)
    child = process.spawn_detached([*RUN_SELF, 'run', '--batch', batch_id], directory / LOG)
    deadline = time.monotonic() + STARTUP_SECONDS
    while time.monotonic() < deadline:
        current = status(root, batch_id)
        if current['running']:  # this child, or the instance that holds the lock (this child then exits 75)
            return {'status': 'started' if current['identity']['pid'] == child.pid else 'already-running', **current}
        if child.poll() not in (None, BUSY_EXIT):
            tail = (directory / LOG).read_text(errors='replace')[-2000:]
            raise RuntimeError(f'The dispatcher exited ({child.returncode}) before it was ready: {tail}')
        time.sleep(0.05)
    raise RuntimeError(f'The dispatcher did not become ready within {STARTUP_SECONDS:.0f}s; see {directory / LOG}')


@dataclass
class Dispatcher:
    """One running dispatcher: its batch, exact identity, launched run-media children and log."""

    root: Path
    batch_id: str
    identity: dict
    log: BoundedLog
    children: dict = field(default_factory=dict)
    noted: set = field(default_factory=set)
    broken: set = field(default_factory=set)
    claims: dict = field(default_factory=dict)

    def note(self, task_id: str, event: str, detail: str) -> None:
        """Log a task that cannot launch now, once per reason."""
        if (task_id, event) not in self.noted:
            self.noted.add((task_id, event))
            self.log.write(event, taskId=task_id, detail=detail)

    def step(self) -> str | None:
        """One bounded poll: reconcile, reap, decide whether to exit, then launch admissible media."""
        try:
            api.reconcile(self.root, self.batch_id)
            self.reap()
            record = store.read_batch(self.root, self.batch_id)
            elapsed = advance_clock(record)  # read only: nothing is committed here
        except (BudgetAuthorityError, BudgetClockError) as error:
            self.log.write('authority-unavailable', error=f'{type(error).__name__}: {error}')
            return 'the batch authority is unavailable; launched exports continue under their own watchdogs'
        reason = self.exit_reason(record, elapsed)
        if reason is None:
            self.launch_ready(record, elapsed)
        return reason

    def exit_reason(self, record: dict, elapsed: float) -> str | None:
        """Why the dispatcher is done, or None to keep polling."""
        delivery = run_deadlines(record)['deliverySeconds']
        if self.children:
            late = elapsed >= delivery + CLEANUP_WINDOW_SECONDS
            return 'the cleanup window after the delivery deadline ended' if late else None
        if record['status'] != 'active':
            return f'the batch is {record["status"]}'
        if elapsed >= delivery:
            return 'the delivery deadline passed'
        if all(clip['state'] == 'handed-off' for clip in record['clips'].values()):
            return 'every clip is handed off'
        return None

    def launch_ready(self, record: dict, elapsed: float) -> None:
        """Claim ready media by deadline within the supervisor bound; owners acquire actual pool slots."""
        if record['status'] != 'active' or elapsed >= run_deadlines(record)['deliverySeconds']:
            return
        # Supervisors queue inside the real pool; they are not heavy render slots.
        free = min(16, len(record['clips'])) - len(self.children)
        for task in ready_order(record):
            if free <= 0:
                return
            if task['kind'] != 'media' or task['id'] in self.broken or claim_refusal(record, task, elapsed):
                continue
            try:
                free -= 1 if self.launch(task) else 0
            except Exception as error:  # noqa: BLE001 - an unexpected error fails only this task, by name
                self.task_error(task['id'], error)

    def launch(self, task: dict) -> bool:
        """Claim one media task as this dispatcher and start its run-media; False when it did not start."""
        try:
            kept = media.stored_request(self.root, self.batch_id, task['id'])
            if kept is None:
                self.note(task['id'], 'waiting-for-media-request', 'enqueue keeps the request; none is kept yet')
                return False
            media.check_request(task, *kept)
            claimed = api.claim_task(self.root, self.batch_id, task['id'], self.identity)
        except EXPECTED as error:
            self.note(task['id'], 'not-launched', f'{type(error).__name__}: {error}')
            return False
        self.claims[task['id']] = ClaimRef(task['id'], claimed['epoch'], claimed['token'])
        return self.spawn(self.claims[task['id']])

    def spawn(self, ref: ClaimRef) -> bool:
        """Start run-media for a committed claim; a failed start releases it (nothing was started)."""
        command = [*RUN_MEDIA, '--batch', self.batch_id, '--task', ref.task_id, '--epoch', str(ref.epoch),
                   '--token', ref.token]
        log = self.root / media.STATE / self.batch_id / media.LOGS / f'{ref.task_id}-e{ref.epoch}.log'
        try:
            self.children[ref.task_id] = (process.spawn_detached(command, log), ref)
            self.claims.pop(ref.task_id, None)
        except (OSError, ValueError) as error:
            self.claims.pop(ref.task_id, None)
            self.log.write('spawn-failed', taskId=ref.task_id, error=str(error))
            self.settle_unlaunched(ref, TaskFailure('run-media-spawn-failed', f'run-media could not start: {error}'))
            return False
        self.log.write('launched', taskId=ref.task_id, epoch=ref.epoch, pid=self.children[ref.task_id][0].pid)
        return True

    def settle_unlaunched(self, ref: ClaimRef, failure: TaskFailure) -> None:
        """Release a claim nothing launched for; a refused release fails the task with the reason instead."""
        try:
            api.release_claim(self.root, self.batch_id, ref)
        except TaskRefused as refusal:
            self.log.write('release-refused', taskId=ref.task_id, reason=str(refusal))
            self.fail(ref, failure)

    def fail(self, ref: ClaimRef, failure: TaskFailure) -> None:
        """Fail this claim's task; a refusal (already settled, fenced) is logged, never raised."""
        try:
            api.fail_task(self.root, self.batch_id, ref, failure)
        except TaskRefused as refusal:
            self.log.write('settle-refused', taskId=ref.task_id, reason=str(refusal))

    def task_error(self, task_id: str, error: Exception, ref: ClaimRef | None = None) -> None:
        """An unexpected error while handling one task: fail that task by name and keep dispatching others.

        A task this dispatcher has not claimed is claimed first, so the failure lands on a fenced claim.
        """
        self.broken.add(task_id)
        detail = clip_text(f'the dispatcher failed handling task {task_id}: {type(error).__name__}: {error}')
        self.log.write(DISPATCHER_ERROR, taskId=task_id, error=detail)
        try:
            ref = ref or self.claims.pop(task_id, None)
            if ref is None:
                claimed = api.claim_task(self.root, self.batch_id, task_id, self.identity)
                ref = ClaimRef(task_id, claimed['epoch'], claimed['token'])
            self.fail(ref, TaskFailure(DISPATCHER_ERROR, detail))
        except Exception as unsettled:  # noqa: BLE001 - logged; the task stays as the authority records it
            self.log.write('task-error-unsettled', taskId=task_id, error=f'{type(unsettled).__name__}: {unsettled}')

    def reap(self) -> None:
        """Record ended run-media children; fail a claim none of them acknowledged or settled (nothing ran)."""
        for task_id, (child, ref) in list(self.children.items()):
            if child.poll() is None:
                continue
            del self.children[task_id]
            self.log.write('run-media-ended', taskId=task_id, exitCode=child.returncode)
            try:
                self.fail_unacknowledged(ref, child.returncode)
            except Exception as error:  # noqa: BLE001 - fails only this task, by name
                self.task_error(task_id, error, ref)

    def fail_unacknowledged(self, ref: ClaimRef, code: int) -> None:
        """A claim still unacknowledged after its run-media ended failed to launch: nothing ran, no retry."""
        row = store.read_batch(self.root, self.batch_id)['production']['tasks'][ref.task_id]
        if row['handle'] is not None or row['state'] not in ('claimed', 'cancel-requested') \
                or row['claim']['epoch'] != ref.epoch:
            return
        if row['state'] == 'cancel-requested':
            api.confirm_cancelled(self.root, self.batch_id, ref)
            return
        self.fail(ref, TaskFailure('launch-not-acknowledged', f'run-media exited ({code}) before its exporter '
                                   'acknowledged the claim; nothing ran'))

    def loop(self, stops: object) -> str:
        """Poll until done or asked to stop; returns why it ended (an unexpected error ends it by name)."""
        while True:
            try:
                reason = f'the dispatcher {stops.reason}' if stops.reason else self.step()
            except Exception as error:  # noqa: BLE001 - never die silently: the exit record names it
                self.log.write(DISPATCHER_ERROR, error=f'{type(error).__name__}: {error}')
                return f'{DISPATCHER_ERROR}: {type(error).__name__}: {error}'
            if reason:
                return reason
            time.sleep(POLL_SECONDS)


def run(root: Path, batch_id: str) -> int:
    """The dispatcher process: one instance per batch, alive until settlement or the deadline."""
    directory = media.batch_state(root, batch_id)
    try:
        process.hold_single_instance(directory, LOCK)
    except process.InstanceBusy:
        return BUSY_EXIT
    from studio.native_runtime import sniper_lock  # the install's maintenance lock, shared for this lifetime
    sniper_lock.hold_for_process(APP_ROOT, 'production media dispatcher')
    dispatcher = Dispatcher(root, batch_id, process.own_process(), BoundedLog(directory / LOG))
    record = {'schemaVersion': 1, 'kind': 'native-media-dispatcher', 'batchId': batch_id,
              'identity': dispatcher.identity, 'startedAt': utc(), 'exit': None}
    refusal = engine_refusal(store.read_batch(root, batch_id), native_budget_engine.engine_identity(REPO))
    write_identity(directory, record if refusal is None else {**record, 'exit': {'at': utc(), 'reason': refusal}})
    if refusal:
        dispatcher.log.write('refused', reason=refusal)
        return REFUSED_EXIT
    dispatcher.log.write('started', identity=dispatcher.identity)
    reason = DISPATCHER_ERROR
    try:
        with process.stop_requests() as stops:
            reason = dispatcher.loop(stops)
    finally:
        dispatcher.log.write('exited', reason=reason, children=sorted(dispatcher.children))
        write_identity(directory, {**record, 'exit': {'at': utc(), 'reason': reason}})
    return 0


def main() -> None:
    """``run --batch ID``: the detached dispatcher entry (``native_batch.py dispatch`` starts it)."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('action', choices=('run',))
    parser.add_argument('--batch', required=True)
    args = parser.parse_args()
    raise SystemExit(run(store.default_root(), store.require_batch_id(args.batch)))


if __name__ == '__main__':
    main()
