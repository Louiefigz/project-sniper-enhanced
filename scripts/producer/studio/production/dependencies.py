"""Dependency-driven transitions: readiness, failure propagation, supersession, parent endings.

A task is ready only when every prerequisite is ``completed``. A failed or
cancelled prerequisite makes its unclaimed dependents failed with a retained
reason; superseding a task supersedes everything computed from it, because a
superseded result never satisfies a current dependency. Unlaunched AI work whose
parent request ended is cancelled: an ended request cannot spawn successors.
All functions change the caller's locked, in-memory record.
"""
from __future__ import annotations

from studio.production.queue_clock import task_deadline

from studio.native_budget_selection import compare_titles
from studio.production.host_contract import clip_text
from studio.production.task_schema import TERMINAL, UNCLAIMED, finish, holds_slot, is_ai, upstream_first

DEAD_PREREQUISITES = ('failed', 'cancelled', 'superseded')


def supersede(record: dict, task_id: str, cause: tuple[str, str | None], elapsed: float) -> list[str]:
    """Revoke the right to publish of a task and of everything computed from it.

    Revocation is recorded on every task it touches (``revoked``), independently of the state, so
    no later end restores it. A live or unresolved execution keeps its slot (``unresolved``); a
    failed or cancelled task keeps its outcome; an abandoned task keeps its state (its launch is
    uncertain, so its claim must never become releasable again). What was computed from any of
    them is superseded too.
    """
    reason, replacement = cause
    tasks, queue, changed = record['production']['tasks'], [task_id], []
    if replacement is not None:
        tasks[task_id]['supersededBy'] = replacement
    while queue:
        task = tasks[queue.pop(0)]
        if task['revoked']:
            continue                                     # already revoked, and so is everything after it
        task['revoked'] = True
        changed.append(task['id'])
        if task['state'] in ('failed', 'cancelled'):
            continue                                     # its dependents already failed with it
        if task['state'] != 'abandoned':
            task['unresolved'] = holds_slot(task)
            cause = reason if task['id'] == task_id else f'input {task_id} was superseded'
            finish(task, 'superseded', elapsed, f'{cause} (was {task["state"]})')
        queue.extend(other['id'] for other in tasks.values() if task['id'] in other['prerequisites'])
    return changed


def _parent_ended(tasks: dict, task: dict) -> str | None:
    """Unlaunched AI work whose parent request ended is cancelled."""
    parent = tasks.get(task['parent']) if task['parent'] else None
    if parent is None or not is_ai(task):
        return None
    if parent['state'] in ('cancelled', 'completed', 'failed', 'superseded', 'abandoned', 'cancel-requested'):
        return f'parent {parent["id"]} ended ({parent["state"]}); its unlaunched AI work is cancelled'
    return None


def approval_stale(record: dict, task: dict) -> bool:
    """Whether the approval this clip task was claimed under has since changed materially (title or script).

    A normalization-only title change is not material; returning to the claimed approval is current.
    """
    claimed = (task['claim'] or {}).get('approval')
    if not task['clipId'] or claimed is None:
        return False
    rows = record['clips'][task['clipId']]['approvals']
    if rows[-1]['identity'] == claimed:
        return False
    before = next((row for row in rows if row['identity'] == claimed), None)
    return before is None or before['script'] != rows[-1]['script'] \
        or compare_titles(before['title'], rows[-1]['title']) == 'different'


def stale_inputs(record: dict) -> dict[str, str | None]:
    """Per task: itself, or a task upstream of it, whose claimed approval changed materially; else None.

    Staleness travels through every dependency, run-scoped tasks with no clip included: a result
    computed from a stale input is stale too, so it never satisfies a dependent or starts a launch.
    Computed once over the acyclic task graph (the schema refuses a cycle), prerequisites first.
    """
    tasks, found = record['production']['tasks'], {}
    for task_id in upstream_first(tasks):
        task = tasks[task_id]
        found[task_id] = task_id if approval_stale(record, task) else next(
            (found[item] for item in task['prerequisites'] if found[item]), None)
    return found


def _waiting_note(prerequisite: dict, stale: str | None) -> str | None:
    """Why a live prerequisite does not satisfy yet, or None when it does (completed and current)."""
    state = prerequisite['state']
    if state == 'completed' and stale:
        cause = 'it was' if stale == prerequisite['id'] else f'its input {stale} was'
        return (f'{prerequisite["id"]} ({cause} completed under an approval that is no longer current: supersede '
                'or replace it)')
    if state == 'completed':
        return None
    note = ': execution evidence lost' if state == 'abandoned' else ''
    return f'{prerequisite["id"]} ({state}{note})'


def _dependency_outcome(record: dict, task: dict, stale: dict) -> tuple[str, str, str | None]:
    """(state, reason, failure category) implied by the prerequisites of an unclaimed task."""
    tasks = record['production']['tasks']
    ended = _parent_ended(tasks, task)
    if ended:
        return 'cancelled', ended, None
    for task_id in task['prerequisites']:
        state = tasks[task_id]['state'] if not tasks[task_id]['revoked'] else 'superseded'
        if state in DEAD_PREREQUISITES:
            return 'failed', f'prerequisite {task_id} is {state}', f'prerequisite-{state}'
    waiting = [note for note in (_waiting_note(tasks[item], stale[item]) for item in task['prerequisites']) if note]
    if waiting:
        return 'blocked', 'waiting for ' + ', '.join(waiting), None
    return 'ready', '', None


def refresh(record: dict, elapsed: float) -> list[str]:
    """Apply dependency outcomes until nothing changes (bounded by the task count)."""
    tasks, moved, stale = record['production']['tasks'], [], stale_inputs(record)
    for _ in range(len(tasks) + 1):
        changes = [(task, *_dependency_outcome(record, task, stale)) for task in tasks.values()
                   if task['state'] in UNCLAIMED]
        changes = [(task, state, reason, category) for task, state, reason, category in changes
                   if (state, clip_text(reason) or None) != (task['state'], task['reason'])]
        if not changes:
            return moved
        for task, state, reason, category in changes:
            _apply_dependency(task, (state, reason, category), elapsed)
            moved.append(task['id'])
    return moved


def _apply_dependency(task: dict, outcome: tuple[str, str, str | None], elapsed: float) -> None:
    """Record one dependency-driven state with its retained reason."""
    state, reason, category = outcome
    if state in TERMINAL:
        if category:
            task['failure'] = {'category': category, 'detail': clip_text(reason)}
        finish(task, state, elapsed, reason)
        return
    task.update(state=state, reason=clip_text(reason) or None)


def ready_order(record: dict) -> list[dict]:
    """Ready tasks, least deadline first, then enqueue order and id."""
    ready = [task for task in record['production']['tasks'].values() if task['state'] == 'ready']
    return sorted(ready, key=lambda task: (task_deadline(record, task), task['enqueuedElapsed'], task['id']))
