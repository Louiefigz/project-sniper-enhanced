"""Claims: reserve before dispatch, fence every later callback by claim epoch and token.

A claim is durable launch intent, committed before anything is started; it is
not evidence that a child exists. AI work is admitted here against the run's
host slots and reservations, and (for per-clip dispatch kinds) the existing
per-clip counters, exactly as ``native_batch.py admit`` would charge it. The
charge belongs to the task and is never refunded: releasing a claim that was
definitely not launched frees the slot (AI work: only with the launch tool's
recorded failure, G9), and a later re-claim takes a new epoch without a second
charge. Every AI task other than the enrolled director needs a
live AI parent: the authority admits no AI task outside the enrolled director's tree (it cannot stop
host work it is never told about).

The child (or the host adapter) acknowledges the claim with its exact handle
before any expensive work (``attach``); a media child then reserves its one
exporter launch through ``check_launch`` in the same commit that charges it.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from studio.native_budget_clock import MIN_STAGE_SECONDS
from studio.native_budget_policy import charge, clip_record, phase_refusal
from studio.native_budget_schema import DISPATCH_KINDS
from studio.production.dependencies import refresh, stale_inputs
from studio.production.formats import clip_deadlines
from studio.production.governance import host_governance, host_rules
from studio.production.host_contract import clip_text, require_handle
from studio.production.task_end import end_cause, require_launch_error, settle_end
from studio.production.task_schema import LIVE, TERMINAL, UNRESOLVABLE, finish, holds_slot, is_ai
from studio.production.tasks import (
    StaleClaim, TaskConflict, TaskRefused, TaskSpec, active_ai, new_row, require_headroom, require_identity,
    task_of, tasks_of,
)

from studio.production.claim_admission import claim_refusal
from studio.production.queue_clock import task_deadline


@dataclass(frozen=True)
class ClaimRef:
    """The claim a callback speaks for: task, epoch and fencing token."""

    task_id: str
    epoch: int
    token: str


@dataclass(frozen=True)
class Outcome:
    """A transition's result; ``changed`` outcomes are committed with ``event``, then ``refusal`` raised."""

    changed: bool
    event: dict
    detail: dict
    refusal: str | None = None


@dataclass(frozen=True)
class Enrollment:
    """The already-running director, recorded with its exact host (or process) handle."""

    task_id: str
    handle: dict
    version: str
    input_fingerprint: str


@dataclass(frozen=True)
class LaunchCheck:
    """What a media child's exporter reservation must match in its acknowledged claim."""

    route: str
    clip_id: str
    handle: dict
    fingerprint: str


def check_claim(task: dict, ref: ClaimRef) -> None:
    """Refuse a callback whose epoch or token is not the task's current claim."""
    claim = task['claim']
    if claim is None or type(ref.epoch) is not int or ref.epoch != claim['epoch'] or ref.token != claim['token']:
        current = claim['epoch'] if claim else None
        raise StaleClaim(f'Callback for task {task["id"]} carries claim epoch {ref.epoch}; the current claim is '
                         f'{current}: a stale or foreign callback is refused')


def _current_approval(record: dict, task: dict) -> str | None:
    """The identity of the clip's current approval, which this claim is made under."""
    approvals = record['clips'][task['clipId']]['approvals'] if task['clipId'] else []
    return approvals[-1]['identity'] if approvals else None


def claim_detail(record: dict, task: dict) -> dict:
    """What the launched child needs: identity, fencing claim, exact input receipts and the approved script."""
    tasks = tasks_of(record)
    inputs = {task_id: {'version': tasks[task_id]['version'], 'receipts': tasks[task_id]['receipts']}
              for task_id in task['prerequisites']}
    clip = record['clips'][task['clipId']] if task['clipId'] else None
    approval = clip['approvals'][-1] if clip and clip['approvals'] else None  # a Long has no Short approval
    return {'batchId': record['batchId'], 'taskId': task['id'], 'epoch': task['claim']['epoch'],
            'token': task['claim']['token'], 'kind': task['kind'], 'route': task['route'],
            'clipId': task['clipId'], 'version': task['version'], 'inputFingerprint': task['inputFingerprint'],
            'deadlineElapsed': task_deadline(record, task), 'parent': task['parent'], 'inputs': inputs,
            'approval': approval, 'output': clip.get('output') if clip else None, 'hostRules': host_rules(record, task)}


def _charge(record: dict, task: dict, elapsed: float) -> None:
    """Charge an AI task once: one run reservation and, for dispatch kinds, the clip counter."""
    if not is_ai(task) or task['charged']:
        return
    record['production']['ai']['charged'] += 1
    task['charged'] = True
    if task['clipId'] and task['kind'] in DISPATCH_KINDS:
        clip = clip_record(record, task['clipId'])
        charge(clip, task['kind'])
        clip['dispatches'].append({'kind': task['kind'], 'label': f'task {task["id"]}', 'elapsed': elapsed})


def expired_claim(record: dict, task: dict, elapsed: float) -> Outcome | None:
    """Settle a prelaunch deadline refusal without charging or creating a new claim."""
    task_id = task['id']
    deadline = task_deadline(record, task)
    if deadline - elapsed < record['deadlines']['cleanupReserveSeconds'] + MIN_STAGE_SECONDS:
        detail = f'Task {task_id} reached its deadline ({deadline:.0f}s) before launch'
        task['failure'] = {'category': 'deadline-expired', 'detail': detail}
        finish(task, 'failed', elapsed, detail)
        refresh(record, elapsed)
        return Outcome(True, {'event': 'task-failed', 'taskId': task_id, 'category': 'deadline-expired',
                             'checkedElapsed': elapsed},
                       {'taskId': task_id, 'state': 'failed', 'checkedElapsed': elapsed}, detail)
    return None


def claim(record: dict, task_id: str, claimer: dict, elapsed: float) -> Outcome:
    """Commit launch intent after cold evidence and fresh original deadline/headroom checks."""
    task, claimer = task_of(record, task_id), require_handle(claimer)
    if task['state'] != 'ready':
        note = f' ({task["reason"]})' if task['reason'] else ''
        raise TaskRefused(f'Task {task_id} is {task["state"]}{note}; only a ready task can be claimed')
    if expired := expired_claim(record, task, elapsed):
        return expired
    refusal = claim_refusal(record, task, elapsed)
    if refusal:
        raise TaskRefused(refusal)
    if task.get('sectionBinding', {}).get('chunkPlan'):
        from studio.native_budget_binding import advance_clock
        elapsed = advance_clock(record)
        if expired := expired_claim(record, task, elapsed):
            return expired
        if refusal := claim_refusal(record, task, elapsed, proof_current=True):
            raise TaskRefused(refusal)
    _charge(record, task, elapsed)
    epoch = task['epochs'] + 1
    task.update(state='claimed', epochs=epoch, reason=None,
                claim={'epoch': epoch, 'token': uuid.uuid4().hex, 'claimedElapsed': elapsed, 'claimer': claimer,
                       'approval': _current_approval(record, task)})
    return Outcome(True, {'event': 'task-claimed', 'taskId': task_id, 'epoch': epoch, 'kind': task['kind'],
                          'claimer': claimer, 'checkedElapsed': elapsed},
                   {**claim_detail(record, task), 'checkedElapsed': elapsed})


def enroll_director(record: dict, enrollment: Enrollment, elapsed: float) -> Outcome:
    """Record the running director as the run's root AI task; it holds one slot and one reservation."""
    handle, tasks = require_handle(enrollment.handle), tasks_of(record)
    require_identity(enrollment.task_id, enrollment.version, enrollment.input_fingerprint)
    existing = tasks.get(enrollment.task_id)
    if existing is not None:
        if existing['kind'] == 'director' and existing['handle'] == handle and existing['state'] in LIVE:
            return Outcome(False, {}, claim_detail(record, existing))
        raise TaskConflict(f'Task {enrollment.task_id} already exists and is not this running director')
    ai, live = record['production']['ai'], [task['id'] for task in tasks.values()
                                            if task['kind'] == 'director' and holds_slot(task)]
    refusal = phase_refusal(record, None, elapsed) or (live and f'Director {live[0]} is already enrolled') or None
    if refusal is None and (active_ai(record) >= ai['slots'] or ai['charged'] >= ai['reservations']):
        refusal = 'No AI slot or reservation is left to enroll the director'
    if refusal:
        raise TaskRefused(refusal)
    spec = TaskSpec(enrollment.task_id, record['batchId'], 'director', enrollment.version,
                    enrollment.input_fingerprint, clip_deadlines(record, None)['deliverySeconds'])
    row = new_row(record, spec, [], (0, elapsed))
    row.update(state='running', epochs=1, charged=True, handle=handle,
               claim={'epoch': 1, 'token': uuid.uuid4().hex, 'claimedElapsed': elapsed, 'claimer': handle,
                      'approval': None})
    tasks[enrollment.task_id] = row
    ai['charged'] += 1
    record['production']['governance'] = host_governance(handle)
    require_headroom(record)
    return Outcome(True, {'event': 'director-enrolled', 'taskId': enrollment.task_id, 'handle': handle,
                          'governance': record['production']['governance']['mode']}, claim_detail(record, row))


def release(record: dict, ref: ClaimRef, elapsed: float, launch_error: str | None = None) -> Outcome:
    """Release a claim no execution acknowledged; the charge stays.

    Media and check claims hold export reservations, not AI slots, so the holder's word releases them. An AI
    claim is released only with the launch tool's own failure, verbatim (G9): ``task_end.end_cause`` accepts it
    exactly as it does for ``fail`` (X88, X89). Any given launch error goes into the ``task-released`` event
    only, never into a record field. When the release ends an AI task, the event also records
    ``endCause: unlaunched``.
    """
    task = task_of(record, ref.task_id)
    check_claim(task, ref)
    if task['handle'] is not None:
        raise TaskRefused(f'Task {ref.task_id} was acknowledged by an execution; only its termination frees it')
    cause = _release(record, task, elapsed, launch_error)
    event = {'event': 'task-released', 'taskId': ref.task_id, 'epoch': ref.epoch}
    if launch_error is not None:   # the launch tool's failure, verbatim: in the event only, never a record field
        event['launchError'] = require_launch_error(launch_error)
    if cause is not None and task['state'] in TERMINAL:   # an AI end is settled through the one rule, as fail does
        event.update(settle_end(task, cause).event_fields())
    refresh(record, elapsed)
    return Outcome(True, event, {'taskId': ref.task_id, 'state': task['state']})


def _release(record: dict, task: dict, elapsed: float, launch_error: str | None) -> str | None:
    """Settle an unlaunched claim: ready again, cancelled when stopping was requested, or its slot freed.

    An abandoned claim is never released: its holder was observed gone, so no one can attest that nothing
    launched. An AI claim needs the launch tool's failure and returns its cause (``unlaunched``); others None.
    """
    state = task['state']
    if state in ('abandoned', 'cancelled'):
        raise TaskRefused(f'Task {task["id"]} is {state}; releasing it cannot prove that nothing launched')
    if is_ai(task) and launch_error is None:
        raise TaskRefused("Releasing an unlaunched claim records the launch tool's failure verbatim (--launch-error)")
    cause = end_cause(task, 'failed', launch_error) if is_ai(task) else None
    if state == 'superseded' and task['unresolved']:
        task.update(unresolved=False, reason=clip_text(f'{task["reason"] or state}; claim released before launch'))
        return cause
    if state == 'cancel-requested' or state == 'claimed' and record['status'] != 'active':
        finish(task, 'cancelled', elapsed, 'claim released before launch; nothing ran')
        return cause
    if state != 'claimed':
        raise TaskRefused(f'Task {task["id"]} is {state}; there is no unlaunched claim to release')
    task.update(state='ready', claim=None, reason=None)
    return cause


def attach(record: dict, ref: ClaimRef, handle: dict, elapsed: float) -> Outcome:
    """Bind the exact execution that acknowledged the claim; ``proceed`` says whether it may work."""
    task, handle = task_of(record, ref.task_id), require_handle(handle)
    check_claim(task, ref)
    if not is_ai(task) and handle['type'] != 'process':
        raise ValueError('Media and check work acknowledge with their exact process identity')
    state = task['state']
    detail = {'taskId': ref.task_id, 'epoch': ref.epoch}
    if task['handle'] is not None:
        if task['handle'] != handle:
            raise TaskConflict(f'Task {ref.task_id} was already acknowledged by another execution')
        return Outcome(False, {}, {**detail, 'state': state, 'proceed': state == 'running'})
    if state == 'claimed' and (expired := expired_claim(record, task, elapsed)):
        return expired
    if state == 'claimed':
        task['state'] = 'running'
    elif state != 'cancel-requested' and not (state in UNRESOLVABLE and task['unresolved']):
        raise TaskRefused(f'Task {ref.task_id} is {state}: its claim was fenced before acknowledgement; this '
                          'execution must not start')
    task['handle'] = handle
    refresh(record, elapsed)
    return Outcome(True, {'event': 'task-attached', 'taskId': ref.task_id, 'epoch': ref.epoch, 'handle': handle},
                   {**detail, 'state': task['state'], 'proceed': task['state'] == 'running'})


def check_launch(record: dict, ref: ClaimRef, check: LaunchCheck) -> dict:
    """The acknowledged media task this exporter launch belongs to; it reserves exactly once."""
    task = task_of(record, ref.task_id)
    check_claim(task, ref)
    if task['kind'] != 'media' or (task['route'], task['clipId']) != (check.route, check.clip_id):
        raise TaskRefused(f'This {check.route} launch of clip {check.clip_id} is not claimed media task {ref.task_id}')
    if task['state'] != 'running':
        raise TaskRefused(f'Task {ref.task_id} is {task["state"]}; no launch is admitted for it')
    if task_deadline(record, task) - record['clock']['elapsed'] \
            < record['deadlines']['cleanupReserveSeconds'] + MIN_STAGE_SECONDS:
        raise TaskRefused(f'Task {ref.task_id} reached its deadline before exporter reservation')
    if task['handle'] != check.handle:
        raise TaskRefused('Only the process that acknowledged the claim may reserve its launch')
    if check.fingerprint != task['inputFingerprint']:
        raise TaskRefused(f'Task {ref.task_id} was enqueued for other inputs; enqueue a replacement')
    if task['attempt'] is not None:
        raise TaskRefused(f'Task {ref.task_id} already reserved launch {task["attempt"]}; a claim launches once')
    stale = stale_inputs(record)[task['id']]
    if stale:
        raise TaskRefused(f'Task {ref.task_id} was claimed on work whose approval has since changed ({stale}); '
                          'supersede or replace it: no launch is admitted for a stale input')
    return task
