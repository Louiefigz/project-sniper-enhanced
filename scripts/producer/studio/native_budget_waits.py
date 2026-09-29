"""Intervals the budget authority proves, on the batch clock, for the elapsed-time breakdown.

- Shared preparation: authorized setup ``[0, setupElapsed]`` (a pending setup counts to now) and
  run-scoped planning, specialist and check tasks from claim to end.
- Ready-but-no-agent: each AI task from readiness (enqueue, or its last prerequisite's
  completion) to its first claim, and from each released claim to its next claim (or its end, or
  now). Claim and release times come from the ``task-claimed``/``task-released`` events of the
  authority trail, read with the record; a wait whose times the trail does not hold is not guessed
  and is counted as untimed.
- Media launch windows: admission to outcome (or now), with each launch's attempt directory, where
  its owners journal their pool and pressure waits.
- Repair: repairCycle tasks from claim to end.
"""
from __future__ import annotations

from studio.production.task_schema import is_ai
from studio.production.tasks import tasks_of

SHARED_KINDS = ('planning', 'specialist', 'check')  # run-scoped preparation, not review or the director


def claim_history(events: tuple[dict, ...]) -> dict:
    """Per task, the batch time of each claim and release epoch recorded in the trail."""
    history: dict[str, dict] = {}
    for event in events:
        kind, task_id, epoch = event.get('event'), event.get('taskId'), event.get('epoch')
        if kind not in ('task-claimed', 'task-released') or type(epoch) is not int or type(event.get('elapsed')) \
                not in (int, float):
            continue
        row = history.setdefault(task_id, {'task-claimed': {}, 'task-released': {}})
        row[kind].setdefault(epoch, event['elapsed'])
    return history


def _claimed_span(task: dict, elapsed: float) -> tuple[float, float] | None:
    """A claimed task from its claim to its end (or now)."""
    if task['claim'] is None:
        return None
    end = task['terminalElapsed'] if task['terminalElapsed'] is not None else elapsed
    return task['claim']['claimedElapsed'], end


def ready_since(task: dict, tasks: dict) -> float | None:
    """When every prerequisite had completed (the enqueue time without prerequisites), else None."""
    rows = [tasks[task_id] for task_id in task['prerequisites']]
    if any(row['state'] != 'completed' for row in rows):
        return None
    return max([task['enqueuedElapsed'], *(row['terminalElapsed'] for row in rows)])


def _claim_time(task: dict, epoch: int, history: dict) -> float | None:
    """When this epoch was claimed: the row's own current claim, else the trail."""
    claim = task['claim']
    if claim is not None and claim['epoch'] == epoch:
        return claim['claimedElapsed']
    return history['task-claimed'].get(epoch)


def ready_waits(task: dict, tasks: dict, history: dict, elapsed: float) -> tuple[list[tuple[float, float]], bool]:
    """An AI task's waits for an agent, and whether any of them could not be timed."""
    since = ready_since(task, tasks)
    if since is None or not is_ai(task) or task['kind'] == 'director':
        return [], False
    times = history.get(task['id'], {'task-claimed': {}, 'task-released': {}})
    end = task['terminalElapsed'] if task['terminalElapsed'] is not None else elapsed
    waits, start = [], since
    for epoch in range(1, task['epochs'] + 1):
        claimed = _claim_time(task, epoch, times)
        if start is None or claimed is None:
            return waits, True
        waits.append((start, claimed))
        start = times['task-released'].get(epoch)
    if task['epochs'] and task['claim'] is not None:
        return waits, False
    if start is None:
        return waits, True
    return [*waits, (start, end)], False


def launch_windows(attempts: list[tuple[str, dict]], elapsed: float) -> list[dict]:
    """Each launch's window on the batch clock and the attempt directory its owners journal into."""
    return [{'clipId': clip_id, 'attemptId': row['id'], 'directory': row['output'], 'start': row['admittedElapsed'],
             'end': row['completedElapsed'] if row['completedElapsed'] is not None else elapsed}
            for clip_id, row in attempts]


def authority_intervals(record: dict, scope: dict, elapsed: float) -> dict:
    """Intervals the authority proves, for the tasks and attempts in scope."""
    tasks, rows = tasks_of(record), {'sharedPreparation': [], 'readyWithoutAgent': [], 'repair': []}
    setup = record['production']['authorization']
    rows['sharedPreparation'].append((0.0, setup['setupElapsed'] if setup['setup'] == 'complete' else elapsed))
    history, untimed = claim_history(scope['events']), 0
    for task in tasks.values():
        span = _claimed_span(task, elapsed)
        if task['clipId'] is None and task['kind'] in SHARED_KINDS and span:
            rows['sharedPreparation'].append(span)
        if task['id'] not in scope['tasks']:
            continue
        waits, missing = ready_waits(task, tasks, history, elapsed)
        rows['readyWithoutAgent'] += waits
        untimed += missing
        if task['kind'] == 'repairCycle' and span:
            rows['repair'].append(span)
    return {'rows': rows, 'untimedReadyWaits': untimed}
