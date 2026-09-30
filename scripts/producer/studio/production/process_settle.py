"""The export watchdog settles its task once, after the child's group is gone, from exact evidence.

Only the watchdog settles: the exporter child acknowledges its claim and reserves, and never
records an outcome, so ``endConfirmed`` is set only after ``process_group.end_group`` found the
child's group and recorded sessions gone. One locked transaction decides, in this order:

- a task that is no longer this claim's live work is left alone;
- a claim the child never acknowledged ends ``cancelled`` when a stop was requested, otherwise
  ``failed`` with the watchdog's reason (``launch-not-acknowledged`` for the acknowledgement
  deadline or an early exit): nothing ran;
- an acknowledged execution whose processes survive keeps its slot: the survivors are recorded as
  the task's ``owners`` (its launch, unless stopped on request, is closed with the watchdog's
  category) and ``reconcile`` settles it once they are gone;
- after cancellation and watchdog-stop decisions, a launch the exporter recorded as succeeded completes the task from the authority's own delivery
  row for the task's bound attempt (``reconcile._exact_outcome``), never from a file in the attempt
  folder;
- a requested stop ends ``cancelled``; a watchdog stop fails the task with its category
  (``watchdog-deadline``, ``watchdog-interrupted``, ``launch-not-acknowledged``) whatever the
  interrupted exporter recorded; otherwise an exporter-recorded failure keeps its category, a
  refused reservation fails ``launch-refused`` with the child's published reason, and anything else
  fails ``export-exited-without-outcome``. A launch still marked running is closed with the category.
"""
from __future__ import annotations

from dataclasses import dataclass

from studio import native_budget_store as store
from studio.native_budget_launch import record_outcome
from studio.production.claims import Outcome
from studio.production.dependencies import refresh, supersede
from studio.production.host_contract import clip_text
from studio.production.reconcile import _exact_outcome
from studio.production.session import transact
from studio.production.queue_clock import SETTLED, settle_task_capacity
from studio.production.task_schema import LIVE, MAX_TASK_OWNERS, UNRESOLVABLE, finish

STOP_REQUESTED, UNACKNOWLEDGED = 'stop-requested', 'launch-not-acknowledged'
EXITED = ('export-exited-without-outcome', 'the exporter ended without recording an outcome')
EVENTS = {'completed': 'task-completed', 'failed': 'task-failed', 'cancelled': 'task-cancelled',
          'superseded': 'task-completed'}


@dataclass(frozen=True)
class Ending:
    """How one supervised child ended: its pid (None: never started), the watchdog's stop reason
    (category, detail) or None, the identities that survived, and the child's published refusal."""

    child_pid: int | None
    reason: tuple[str, str] | None
    survivors: tuple[dict, ...]
    refusal: str | None


def _end(task: dict, state: str, elapsed: float, failure: tuple[str, str] | None) -> None:
    """A confirmed end: the group is gone, so the slot frees."""
    state = 'superseded' if task['revoked'] else state
    if failure and state == 'failed':
        task['failure'] = {'category': failure[0], 'detail': clip_text(failure[1])}
    task.update(unresolved=False, endConfirmed=True, owners=[])
    finish(task, state, elapsed, failure[1] if failure else 'the watchdog confirmed the execution ended')


def _close_attempt(record: dict, task: dict, failure: tuple[str, str], elapsed: float) -> None:
    """Close the task's launch still marked running (or abandoned) with the watchdog's category."""
    attempts = record['clips'][task['clipId']]['attempts'] if task['attempt'] else []
    if not any(row['id'] == task['attempt'] and row['status'] in ('running', 'abandoned') for row in attempts):
        return
    record_outcome(record, {'clipId': task['clipId'], 'attemptId': task['attempt']},
                   {'status': 'failed', 'failureCategory': failure[0], 'failedPhase': None,
                    'errorType': 'ExportWatchdog', 'error': failure[1], 'successStatuses': (), 'stages': []},
                   elapsed)


def _attempt_status(record: dict, task: dict) -> str | None:
    """The recorded status of the task's bound launch (None when none is bound)."""
    rows = record['clips'][task['clipId']]['attempts'] if task['attempt'] else []
    return next((row['status'] for row in rows if row['id'] == task['attempt']), None)


def _unacknowledged(task: dict, ending: Ending, elapsed: float) -> None:
    """A claim no child acknowledged: nothing ran."""
    if task['cancelRequested']:
        _end(task, 'cancelled', elapsed, None)
        return
    _end(task, 'failed', elapsed, ending.reason or (UNACKNOWLEDGED, 'the exporter child ended before '
                                                                   'acknowledging its claim; nothing ran'))


def _category(ending: Ending) -> str | None:
    """The watchdog's stop category, or None when the child ended by itself."""
    return ending.reason[0] if ending.reason else None


def _acknowledged(record: dict, task: dict, ending: Ending, elapsed: float) -> None:
    """Proved cleanup: cancellation and watchdog reasons take precedence over a delivery."""
    status = _attempt_status(record, task)
    if task['cancelRequested'] or _category(ending) == STOP_REQUESTED:
        _close_attempt(record, task, ('cancelled', 'stopped on request'), elapsed)
        _end(task, 'cancelled', elapsed, None)
        return
    if ending.reason is None and status == 'succeeded' and _exact_outcome(record, task, elapsed):
        return
    if ending.reason is None and status == 'failed' and _exact_outcome(record, task, elapsed):
        return
    refused = ('launch-refused', ending.refusal) if ending.refusal and task['attempt'] is None else None
    failure = ending.reason or refused or EXITED
    _close_attempt(record, task, failure, elapsed)
    _end(task, 'failed', elapsed, failure)


def _keep_owners(record: dict, task: dict, ending: Ending, elapsed: float) -> None:
    """Processes outlived the group kill: they hold the slot as the task's owners until ``reconcile`` sees them
    gone. A launch still marked running is closed now with the watchdog's category (a stop leaves it running)."""
    known = {(row['pid'], row['started']) for row in task['owners']}
    owners = task['owners'] + [row for row in ending.survivors if (row['pid'], row['started']) not in known]
    if len(owners) > MAX_TASK_OWNERS:
        unknown = {**owners[0], 'started': 'unobservable'}
        owners = [unknown, *(row for row in owners if row != unknown)]
    task['owners'] = owners[:MAX_TASK_OWNERS]
    task['unresolved'] = True
    if task['state'] not in UNRESOLVABLE:
        finish(task, 'abandoned', elapsed, 'watchdog cleanup left owned processes or unknown liveness')
    if not task['cancelRequested'] and _category(ending) != STOP_REQUESTED:
        _close_attempt(record, task, ending.reason or EXITED, elapsed)
    if _category(ending) == STOP_REQUESTED:
        task['cancelRequested'] = True
    elif ending.reason:
        task['reason'] = clip_text(f'{ending.reason[0]}: {ending.reason[1]}; cleanup remains unresolved')
        supersede(record, task['id'], (task['reason'], None), elapsed)


def _decide(record: dict, task: dict, ending: Ending, elapsed: float) -> str | None:
    """Apply the evidence to this claim's live task; returns the event, or None when nothing applies."""
    handle = task['handle']
    if handle is not None and (handle['type'] != 'process' or handle['pid'] != ending.child_pid):
        return None
    if ending.survivors:
        _keep_owners(record, task, ending, elapsed)
        return 'tasks-reconciled'
    if handle is None:
        _unacknowledged(task, ending, elapsed)
        return EVENTS[task['state']]
    _acknowledged(record, task, ending, elapsed)
    return EVENTS[task['state']]


def settle(task_claim: object, ending: Ending) -> dict:
    """One locked settlement of the watchdog's task (``committed`` False when it was not its to settle)."""
    def operation(record: dict, elapsed: float) -> Outcome:
        """Settle the task if it is still this claim's live work."""
        task = record['production']['tasks'].get(task_claim.task_id)
        claim = (task or {}).get('claim') or {}
        pending = task is not None and (task['state'] in LIVE or task['state'] in UNRESOLVABLE and task['unresolved'])
        if not pending or (claim.get('epoch'), claim.get('token')) \
                != (task_claim.epoch, task_claim.token):
            return Outcome(False, {}, {'taskId': task_claim.task_id, 'settled': False})
        event = _decide(record, task, ending, elapsed)
        if event is None:
            return Outcome(False, {}, {'taskId': task_claim.task_id, 'settled': False})
        # The owners' rows go with their credit and names, in this same terminal event (X189 F2).
        settled = {} if ending.survivors else settle_task_capacity(record, task['id'])
        refresh(record, elapsed)
        detail = {'taskId': task['id'], 'state': task['state'], 'failure': task['failure'], 'owners': task['owners']}
        line = {'event': event, 'epoch': task_claim.epoch, **detail, **({SETTLED: settled} if settled else {})}
        return Outcome(True, line, {**detail, 'settled': True})
    return transact(store.default_root(), task_claim.batch_id, operation)
