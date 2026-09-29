"""Execution outcomes: completion, failure, cancellation and usage, fenced by the claim.

Every callback must carry the task's current claim epoch and token (``check_claim``);
an older epoch is refused. Repeating a recorded outcome is a no-op only when it is
the same outcome of the same claim with the same artifact identity; any other
repetition is a conflict. Cancellation requested is not cancellation complete: a
live task keeps its slot in ``cancel-requested`` until termination is confirmed.
A revoked task may still report its end, settling its slot and retaining artifacts
as history; completion ends superseded without restoring publication. Usage is the host's
cumulative count and only ever grows; a task without a report stays unknown.
Acknowledged media completes, fails or confirms cancellation only through its
export watchdog after owned cleanup; generic callbacks cannot invent that proof.
"""
from __future__ import annotations

from dataclasses import dataclass

from studio.production.claims import ClaimRef, Outcome, check_claim
from studio.production.dependencies import approval_stale, refresh
from studio.production.host_contract import clip_text, merge_usage, valid_failure, valid_receipts
from studio.production.task_schema import (
    LIVE, TERMINAL, UNCLAIMED, UNRESOLVABLE, finish, handle_cleans_up, holds_slot, is_ai,
)
from studio.production.tasks import TaskConflict, TaskRefused, task_of
from studio.production.queue_clock import task_deadline


@dataclass(frozen=True)
class TaskResult:
    """A completed execution's immutable artifacts and (optionally) its cumulative usage."""

    receipts: tuple
    usage: dict | None = None


@dataclass(frozen=True)
class TaskFailure:
    """A failure category slug, a bounded detail and (optionally) usage."""

    category: str
    detail: str
    usage: dict | None = None


def _usage(task: dict, usage: dict | None) -> None:
    """Merge a cumulative usage report into an AI task."""
    if usage is None:
        return
    if not is_ai(task):
        raise ValueError('Only AI tasks report host usage')
    task['usage'] = merge_usage(task['usage'], usage)


def _ended(task: dict, ref: ClaimRef) -> Outcome:
    """A committed outcome naming the task's resulting state."""
    return Outcome(True, {'taskId': task['id'], 'epoch': ref.epoch}, {'taskId': task['id'], 'state': task['state'],
                                                                     'unresolved': task['unresolved']})


def _replay(task: dict) -> Outcome:
    """A repeated identical outcome changes nothing."""
    return Outcome(False, {}, {'taskId': task['id'], 'state': task['state'], 'replayed': True})


def _may_report(task: dict) -> bool:
    """Live work, or an ended execution whose end was never reported: superseded still holding its slot,
    or abandoned yet acknowledged or unresolved. An execution reports its end once."""
    if task['state'] in LIVE:
        return True
    if task['endConfirmed']:
        return False
    if task['state'] == 'superseded':
        return task['unresolved']
    return task['state'] == 'abandoned' and (task['handle'] is not None or task['unresolved'])


def _require_nonmedia_outcome(task: dict) -> None:
    """Acknowledged media settles only from the watchdog's owned cleanup evidence."""
    if task['kind'] == 'media' and task['handle'] is not None:
        raise TaskRefused(f'Task {task["id"]} is acknowledged media; its export watchdog must confirm cleanup '
                          'and settle its exact launch outcome')


def _section_completion(record: dict, ref: ClaimRef, receipts: list[dict]) -> bool:
    """Validate owned section results, separating historical settlement from publication."""
    from studio.production.section_results import validate_result, validate_settlement_result
    task = task_of(record, ref.task_id)
    if not task.get('sectionBinding'):
        return False
    if len(receipts) != 1:
        raise ValueError('A section task completes with its single owned result receipt')
    settling = task['state'] in ('superseded', 'abandoned') and (_may_report(task) or bool(task['receipts']))
    validator = validate_settlement_result if settling else validate_result
    validator(record, ref, receipts[0])
    return settling


def complete(record: dict, ref: ClaimRef, result: TaskResult, elapsed: float) -> Outcome:
    """Record an execution's artifacts; dependents of a current (not superseded) result become ready."""
    task = task_of(record, ref.task_id)
    check_claim(task, ref)
    receipts = [dict(row) for row in result.receipts]
    if not valid_receipts(receipts) or not receipts and task['kind'] != 'director':
        raise ValueError('A completion binds its artifacts: 1-8 distinct receipts {path, sha256, bytes}')
    settling = _section_completion(record, ref, receipts)
    if task['state'] == 'completed' or task['state'] == 'superseded' and task['receipts'] \
            or settling and task['receipts']:
        if task['receipts'] != receipts:
            raise TaskConflict(f'Task {ref.task_id} already completed with different artifacts')
        return _replay(task)
    _require_nonmedia_outcome(task)
    if task['handle'] is None:
        raise TaskRefused(f'Task {ref.task_id} was never acknowledged; an execution attaches before it completes')
    if not _may_report(task):
        raise TaskConflict(f'Task {ref.task_id} already ended as {task["state"]}')
    if task.get('sectionBinding', {}).get('chunkPlan') and not settling:
        from studio.production.section_chunk_progress import require_live_review
        elapsed = require_live_review(record, task)
    if not task['revoked'] and task['kind'] != 'director' and elapsed > task_deadline(record, task):
        return fail(record, ref, TaskFailure('deadline-expired', 'completion arrived after the task deadline',
                                            result.usage), elapsed)
    _usage(task, result.usage)
    task.update(receipts=receipts, unresolved=False, endConfirmed=True, approvalStale=approval_stale(record, task))
    if task['revoked'] and task['state'] != 'superseded':
        finish(task, 'superseded', elapsed, f'{task["reason"]}; it completed after its right to publish was revoked')
    elif not task['revoked'] and not settling:
        task['reason'] = None
        finish(task, 'completed', elapsed)
    refresh(record, elapsed)
    outcome = _ended(task, ref)
    outcome.event.update(event='task-completed', receipts=receipts, publishable=task['state'] == 'completed',
                         approvalStale=task['approvalStale'])
    return outcome


def fail(record: dict, ref: ClaimRef, failure: TaskFailure, elapsed: float) -> Outcome:
    """Record a failed execution (or a claim that failed before launch); dependents fail with the reason."""
    task = task_of(record, ref.task_id)
    check_claim(task, ref)
    row = {'category': failure.category, 'detail': clip_text(failure.detail) if type(failure.detail) is str else None}
    if not valid_failure(row):
        raise ValueError('A failure names a category slug and a bounded detail')
    if task['state'] == 'failed':
        if task['failure']['category'] != row['category']:
            raise TaskConflict(f'Task {ref.task_id} already failed as {task["failure"]["category"]}')
        return _replay(task)
    _require_nonmedia_outcome(task)
    if task['state'] in ('completed', 'cancelled') or task['state'] == 'superseded' and not task['unresolved']:
        raise TaskConflict(f'Task {ref.task_id} already ended as {task["state"]}')
    if not _may_report(task):
        raise TaskRefused(f'Task {ref.task_id} is {task["state"]}: its claim was fenced')
    _usage(task, failure.usage)
    task['endConfirmed'] = True
    if task['state'] == 'superseded':
        task.update(unresolved=False, reason=clip_text(f'{task["reason"]}; its execution failed ({row["category"]})'))
    else:
        task.update(failure=row, unresolved=False)
        finish(task, 'failed', elapsed, row['detail'] or row['category'])
    refresh(record, elapsed)
    outcome = _ended(task, ref)
    outcome.event.update(event='task-failed', category=row['category'])
    return outcome


def confirm_cancelled(record: dict, ref: ClaimRef, usage: dict | None, elapsed: float) -> Outcome:
    """Termination of a claimed or running execution is confirmed: its slot frees."""
    task = task_of(record, ref.task_id)
    check_claim(task, ref)
    if task['state'] == 'cancelled' and task['claim']['epoch'] == ref.epoch \
            or task['state'] in UNRESOLVABLE and not task['unresolved']:
        return _replay(task)
    _require_nonmedia_outcome(task)
    if task['state'] in ('completed', 'failed') or not _may_report(task):
        raise TaskConflict(f'Task {ref.task_id} already ended as {task["state"]}')
    _usage(task, usage)
    _terminated(record, task, elapsed)
    refresh(record, elapsed)
    outcome = _ended(task, ref)
    outcome.event.update(event='task-cancelled', state=task['state'], unresolved=task['unresolved'])
    return outcome


def _terminated(record: dict, task: dict, elapsed: float) -> None:
    """A confirmed end frees the slot only when the end of the exact execution is proved.

    AI work with no bound execution proves nothing (a host turn may have started), and a
    host turn whose own host was not observed to end its tools on interrupt may leave
    them running: both are recorded as ended (``cancelled``, or their superseded or
    abandoned state kept) with the slot ``unresolved``. A cancelled task never completes later.
    """
    handle = task['handle']
    if handle is None and is_ai(task):
        note = 'no execution is bound to this claim, so its termination cannot be confirmed; the slot stays held'
    elif handle is not None and handle['type'] == 'host' and not handle_cleans_up(handle, 'interruptCleansUp'):
        note = ('the host confirmed the turn ended but its host was not observed to end its tool processes; the '
                'slot stays unresolved until evidence or settlement')
    else:
        note = None
    task['endConfirmed'] = True
    if task['state'] in LIVE:
        finish(task, 'cancelled', elapsed, note or 'termination confirmed')
        task['unresolved'] = note is not None
        return
    task.update(unresolved=note is not None, reason=clip_text(f'{task["reason"]}; {note or "termination confirmed"}'))


def request_cancel(record: dict, task_id: str, reason: str, elapsed: float) -> Outcome:
    """Stop unlaunched work now; ask live or unresolved work to stop (its slot stays held)."""
    task = task_of(record, task_id)
    if type(reason) is not str or not reason.strip():
        raise ValueError('A cancellation request records its reason')
    if not _mark_cancel(task, clip_text(reason), elapsed):
        return Outcome(False, {}, _cancel_detail(task))
    refresh(record, elapsed)
    return Outcome(True, {'event': 'task-cancel-requested', 'taskId': task_id, 'state': task['state'],
                          'reason': clip_text(reason)}, _cancel_detail(task))


def _mark_cancel(task: dict, reason: str, elapsed: float) -> bool:
    """Apply one cancellation request; False when it changes nothing."""
    if task['state'] in UNCLAIMED:
        task['cancelRequested'] = True
        finish(task, 'cancelled', elapsed, reason)
        return True
    if task['state'] in ('claimed', 'running'):
        task.update(state='cancel-requested', cancelRequested=True, reason=reason)
        return True
    if holds_slot(task) and not task['cancelRequested']:
        task['cancelRequested'] = True
        return True
    return False


def _cancel_detail(task: dict) -> dict:
    """What the caller must interrupt: the exact handle and claim, while the task still holds its slot."""
    claim = task['claim']
    return {'taskId': task['id'], 'state': task['state'], 'handle': task['handle'],
            'epoch': claim['epoch'] if claim else None, 'holdsSlot': holds_slot(task),
            'terminationPending': holds_slot(task)}


def record_usage(record: dict, ref: ClaimRef, usage: dict, elapsed: float) -> Outcome:
    """Merge a (possibly delayed or replayed) cumulative usage report; it never lowers a count."""
    task = task_of(record, ref.task_id)
    check_claim(task, ref)
    before = task['usage']
    _usage(task, usage)
    if task['usage'] == before:
        return _replay(task)
    return Outcome(True, {'event': 'task-usage', 'taskId': ref.task_id, 'epoch': ref.epoch, 'usage': task['usage']},
                   {'taskId': ref.task_id, 'usage': task['usage']})


def settle_resource(record: dict, task_id: str, reason: str, elapsed: float) -> Outcome:
    """While a run drains, the operator's recorded evidence settles an unresolved slot; the charge stays."""
    task = task_of(record, task_id)
    if record['status'] != 'draining':
        raise TaskRefused('Unresolved work is settled only while the run drains; before that it keeps its slot')
    if type(reason) is not str or not reason.strip():
        raise ValueError("Settling an unresolved resource records the operator's evidence")
    if not (task['state'] in TERMINAL and task['unresolved']):
        raise TaskRefused(f'Task {task_id} is {task["state"]} with no unresolved resource to settle')
    task.update(unresolved=False, reason=clip_text(f'{task["reason"]}; settled by the operator: {reason}'))
    return Outcome(True, {'event': 'task-resource-settled', 'taskId': task_id, 'reason': clip_text(reason)},
                   {'taskId': task_id, 'state': task['state'], 'unresolved': False})
