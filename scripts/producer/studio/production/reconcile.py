"""Recovery after a crash, restart or disconnect: evidence decides, uncertainty stays charged.

Each unsettled task is checked against evidence the caller supplies in one
``Observation``: a single process-table read (exact PID, process group and start
time, so a reused PID never matches) and the host adapter's report per host
handle. No evidence means no change.

- A claim nobody acknowledged, whose holder is gone, is an uncertain launch: it
  becomes ``abandoned``, stays charged and is never made ready again. AI work keeps
  its slot (a host turn may have started before its acknowledgement was lost);
  media and check children must acknowledge before any work, so their claim is
  fenced instead and a late child is refused. The same holds after supersession:
  a superseded AI claim whose holder is gone becomes ``abandoned`` with its slot held.
- An ended media exporter stays unresolved until its watchdog confirms owned cleanup.
  Exporter PID termination alone cannot prove the detached sessions ended. When a
  watchdog retained surviving owners, all exact identities and their process groups
  must be gone before the recorded launch outcome can settle the task. Unknown
  identities retain the slot. Revoked, cancelled and expired work cannot publish.
- Otherwise a gone execution whose process group is empty has terminated:
  ``cancel-requested`` becomes ``cancelled``, anything else ``abandoned`` without a
  held slot. Survivors in its group, a host turn seen terminal (no host end event is
  evidence yet; ``task_end``) or a host that no longer knows the turn leave the slot unresolved.

Host events arrive through ``apply_host_event`` and use the same fenced callbacks.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

from native_render_processes import ProcessIdentity, ResourceMeasurementError, identity_matches
from studio import native_budget_launch
from studio.native_budget_policy import clip_record
from studio.production.callbacks import TaskFailure, TaskResult, complete, confirm_cancelled, fail, record_usage
from studio.production.claims import ClaimRef, Outcome, attach, check_claim
from studio.production.dependencies import refresh
from studio.production.host_contract import CATEGORY, HostEvent, clip_text
from studio.production.task_end import ALIVE, LOST, TERMINATED, observed_state
from studio.production.task_schema import LIVE, TERMINAL, UNRESOLVABLE, finish, is_ai
from studio.production.tasks import TaskConflict, task_of, tasks_of
from studio.production.queue_clock import SETTLED, settle_task_capacity, task_deadline

HOST_STATES = {'running': ALIVE, 'terminal': TERMINATED, 'unknown': LOST}


@dataclass(frozen=True)
class Observation:
    """One reading of the evidence: the process table (None when unreadable) and host turn states."""

    table: dict | None
    host: dict = field(default_factory=dict)


def host_key(handle: dict) -> str:
    """The key a host adapter reports one turn under."""
    return f'{handle["host"]}:{handle["thread"]}:{handle["turn"] or ""}'


def current_observation(host: dict | None = None) -> Observation:
    """Read the process table once; an unreadable table is no evidence, never evidence of death."""
    host = dict(host or {})
    if any(value not in HOST_STATES for value in host.values()):
        raise ValueError('A host turn is reported as running, terminal or unknown')
    try:
        table = native_budget_launch._process_table()
    except (OSError, subprocess.SubprocessError, ResourceMeasurementError):
        table = None
    return Observation(table, host)


def execution_state(handle: dict, observation: Observation) -> str | None:
    """ALIVE, TERMINATED (exact identity gone, nothing left), LOST (cannot prove the end) or None."""
    if handle['type'] == 'host':
        return HOST_STATES.get(observation.host.get(host_key(handle)))
    if observation.table is None:
        return None
    if identity_matches(observation.table, ProcessIdentity(handle['pid'], handle['started'], handle['pgid'])):
        return ALIVE
    survivors = any(row[1] == handle['pgid'] for row in observation.table.values())
    return LOST if survivors else TERMINATED


def _evidence(record: dict, handle: dict, observation: Observation) -> str | None:
    """The execution state as the one end rule reads it (``task_end.observed_state``): an ended host turn is lost."""
    return observed_state(handle, execution_state(handle, observation))


def _change(task: dict, before: str, reason: str) -> dict:
    """One reconciliation change, as reported and recorded; its reason clipped as the record's is (X246 n1)."""
    return {'taskId': task['id'], 'from': before, 'to': task['state'], 'unresolved': task['unresolved'],
            'reason': clip_text(reason)}


def _abandon(task: dict, unresolved: bool, reason: str, elapsed: float) -> dict:
    """Lost execution evidence: charged, never retried; ``unresolved`` keeps the slot."""
    before = task['state']
    task['unresolved'] = unresolved
    finish(task, 'abandoned', elapsed, reason)
    return _change(task, before, reason)


def _unacknowledged(record: dict, task: dict, observation: Observation, elapsed: float) -> dict | None:
    """A claim with no acknowledged execution whose holder is gone."""
    if _evidence(record, task['claim']['claimer'], observation) in (None, ALIVE):
        return None
    held = is_ai(task)
    reason = ('the claim holder ended before any execution acknowledged it: the launch is uncertain, stays charged '
              'and is never retried; ' + ('a host turn may have started, so its slot stays held' if held
                                          else 'the claim is fenced, so a late child cannot start'))
    return _abandon(task, held, reason, elapsed)


def _exact_outcome(record: dict, task: dict, elapsed: float) -> dict | None:
    """The outcome a media task's exporter recorded for its bound launch, when exact."""
    clip = clip_record(record, task['clipId'])
    attempt = next((row for row in clip['attempts'] if row['id'] == task['attempt']), None)
    before = task['state']
    if attempt is None or attempt['status'] not in ('succeeded', 'failed'):
        return None
    if task['cancelRequested']:
        return _media_terminal(task, 'cancelled', elapsed, 'media cleanup confirmed after cancellation')
    if task['revoked']:
        return _media_terminal(task, 'superseded', elapsed, 'revoked media cleanup confirmed')
    if attempt['completedElapsed'] > _outcome_deadline(record, task, attempt):
        task['failure'] = {'category': 'deadline-expired', 'detail': 'the media outcome exceeded its task deadline'}
        return _media_terminal(task, 'failed', elapsed, task['failure']['detail'])
    if attempt['status'] == 'failed':
        category = (attempt['failure'] or {}).get('category') or ''
        detail = f'exporter launch {attempt["id"]} failed ({attempt["resultStatus"]})'
        task.update(unresolved=False, endConfirmed=True, owners=[], failure={
            'category': category if CATEGORY.fullmatch(category) else 'launch-failed', 'detail': clip_text(detail)})
        finish(task, 'failed', elapsed, detail)
        return _change(task, before, detail)
    delivery = next((row for row in clip['deliveries'] if row['attemptId'] == attempt['id']), None)
    if delivery is None or not delivery['output'] or not delivery['sha256']:
        return None
    task.update(receipts=[{'path': delivery['output'], 'sha256': delivery['sha256'], 'bytes': None}],
                unresolved=False, endConfirmed=True, owners=[], reason=None)
    finish(task, 'completed', elapsed)
    return _change(task, before, 'the exporter recorded its exact delivery before the task callback was lost')


def _outcome_deadline(record: dict, task: dict, attempt: dict) -> float:
    """Evaluate success with credit frozen at delivery, never credit earned by later work."""
    clip = record['clips'][task['clipId']]
    from studio.production.queue_clock import enabled
    if not enabled(clip) or attempt['status'] != 'succeeded':
        return task_deadline(record, task)
    clock = clip['capacityClock']
    origin = clock['taskCredits'].get(task['id'])
    earned = clock['deliveryCredits'].get(attempt['id'], 0.0)
    return task['deadlineElapsed'] + (max(0.0, earned - origin) if origin is not None else 0.0)


def _media_terminal(task: dict, state: str, elapsed: float, reason: str) -> dict:
    """Close media after cleanup without restoring cancelled or revoked publication."""
    before = task['state']
    task.update(unresolved=False, endConfirmed=True, owners=[])
    finish(task, state, elapsed, reason)
    return _change(task, before, reason)


def _owners_ended(task: dict, observation: Observation) -> bool:
    """Every retained owner is observed gone; unknown identities never prove cleanup."""
    return bool(task['owners']) and all(row['started'] != 'unobservable'
        and execution_state(row, observation) == TERMINATED for row in task['owners'])


def _live(record: dict, task: dict, observation: Observation, elapsed: float) -> dict | None:
    """An acknowledged live execution: alive, exactly finished, terminated or lost."""
    status = _evidence(record, task['handle'], observation)
    if status in (None, ALIVE):
        return None
    if task['kind'] == 'media':
        return _abandon(task, True, 'the exporter ended; its watchdog must confirm all owned cleanup', elapsed)
    task['endConfirmed'] = status == TERMINATED
    if status == TERMINATED and task['state'] == 'cancel-requested':
        before = task['state']
        finish(task, 'cancelled', elapsed, 'termination confirmed: the exact execution is gone')
        return _change(task, before, 'termination confirmed')
    if status == TERMINATED:
        return _abandon(task, False, 'the execution ended without reporting an outcome', elapsed)
    return _abandon(task, True, 'the execution is gone but its end cannot be proved (survivors in its process '
                                'group, or the host no longer knows the turn)', elapsed)


def _unresolved(record: dict, task: dict, observation: Observation, elapsed: float) -> dict | None:
    """An ended task still holding its slot frees it once termination is proved."""
    if task['handle'] is not None and _evidence(record, task['handle'], observation) != TERMINATED:
        return None
    if task['kind'] == 'media':
        if not _owners_ended(task, observation):
            return None
        settled = settle_task_capacity(record, task['id'])   # its credit and names ride on the change (X189 F2)
        change = _media_resolved(record, task, elapsed)
        return {**change, SETTLED: settled} if settled else change
    task.update(unresolved=False, endConfirmed=True,
                reason=clip_text(f'{task["reason"] or task["state"]}; termination confirmed'))
    return _change(task, task['state'], 'termination confirmed')


def _media_resolved(record: dict, task: dict, elapsed: float) -> dict:
    """A media task whose owned cleanup is confirmed: its terminal outcome, or its termination confirmed."""
    if task['cancelRequested'] or task['revoked']:
        state = 'superseded' if task['revoked'] else 'cancelled'
        return _media_terminal(task, state, elapsed, 'owned cleanup confirmed without publication')
    if task['attempt'] is not None and (outcome := _exact_outcome(record, task, elapsed)):
        return outcome
    task['owners'] = []
    task.update(unresolved=False, endConfirmed=True,
                reason=clip_text(f'{task["reason"] or task["state"]}; termination confirmed'))
    return _change(task, task['state'], 'termination confirmed')


def _reconcile_one(record: dict, task: dict, observation: Observation, elapsed: float) -> dict | None:
    """The change the evidence implies for one task, or None."""
    if task['state'] in LIVE and task['handle'] is None:
        return _unacknowledged(record, task, observation, elapsed)
    if task['state'] in LIVE:
        return _live(record, task, observation, elapsed)
    if task['state'] in TERMINAL and task['unresolved'] and (task['handle'] is not None or task['owners']):
        return _unresolved(record, task, observation, elapsed)
    if task['state'] in UNRESOLVABLE and task['unresolved'] and task['claim'] is not None:
        return _fenced_unacknowledged(record, task, observation, elapsed)
    return None


def _fenced_unacknowledged(record: dict, task: dict, observation: Observation, elapsed: float) -> dict | None:
    """An ended, never-acknowledged claim whose holder is provably gone.

    Media/check children must acknowledge before any work, so their claim is fenced and
    frees. A superseded AI claim becomes ``abandoned`` with its slot held: a host turn may
    have started, and no one is left to attest that nothing launched, so it is never released.
    """
    if is_ai(task) and task['state'] != 'superseded' \
            or _evidence(record, task['claim']['claimer'], observation) in (None, ALIVE):
        return None
    if is_ai(task):
        return _abandon(task, True, f'{task["reason"]}; its claim holder ended before any execution '
                                    'acknowledged it: the launch is uncertain and its slot stays held', elapsed)
    task.update(unresolved=False, reason=clip_text(f'{task["reason"]}; its claim holder is gone and no child '
                                                   'acknowledged it, so the claim is fenced'))
    return _change(task, task['state'], 'claim fenced: holder gone before acknowledgement')


def reconcile_tasks(record: dict, observation: Observation, elapsed: float) -> list[dict]:
    """Apply the evidence to every unsettled task; dependents follow. Returns the changes."""
    changes = [change for task in list(tasks_of(record).values())
               if (change := _reconcile_one(record, task, observation, elapsed))]
    if changes:
        refresh(record, elapsed)
    return changes


def _bind_host(record: dict, ref: ClaimRef, event: HostEvent, elapsed: float) -> bool:
    """A host event speaks for exactly one turn: attach it when its acknowledgement was lost."""
    task = task_of(record, ref.task_id)
    check_claim(task, ref)
    if task['handle'] is None:
        return attach(record, ref, event.handle, elapsed).changed
    if task['handle'] != event.handle:
        raise TaskConflict(f'Host event for task {ref.task_id} names another execution')
    return False


def _host_outcome(record: dict, ref: ClaimRef, event: HostEvent, elapsed: float) -> Outcome:
    """The callback one bound host event maps to."""
    task = task_of(record, ref.task_id)
    if event.type == 'usage':
        if event.usage is None:
            raise ValueError('A usage event carries usage')
        return record_usage(record, ref, event.usage, elapsed)
    if event.type == 'completed':
        return complete(record, ref, TaskResult(event.receipts, event.usage), elapsed)
    if event.type == 'failed':
        return fail(record, ref, TaskFailure(event.failure['category'], event.failure['detail'], event.usage), elapsed)
    if event.type == 'interrupted':
        return confirm_cancelled(record, ref, event.usage, elapsed)
    if event.type == 'lost' and task['state'] in LIVE:
        change = _abandon(task, True, 'the host no longer knows this turn: termination cannot be proved', elapsed)
        refresh(record, elapsed)
        return Outcome(True, {'event': 'task-abandoned', 'taskId': ref.task_id, 'epoch': ref.epoch}, change)
    return Outcome(False, {}, {'taskId': ref.task_id, 'state': task['state'], 'terminationPending': True})


def apply_host_event(record: dict, event: HostEvent, elapsed: float) -> Outcome:
    """Map one validated host event onto the fenced task callbacks (a cancel acknowledgement ends nothing)."""
    ref = ClaimRef(event.task_id, event.epoch, event.token)
    if event.type in ('accepted', 'started'):
        return attach(record, ref, event.handle, elapsed)
    attached = _bind_host(record, ref, event, elapsed)
    outcome = _host_outcome(record, ref, event, elapsed)
    if attached and not outcome.changed:
        return Outcome(True, {'event': 'task-attached', 'taskId': ref.task_id, 'epoch': ref.epoch,
                              'handle': event.handle}, outcome.detail)
    return outcome
