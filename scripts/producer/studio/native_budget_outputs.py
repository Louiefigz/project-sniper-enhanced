"""Per-output status that explains a delay while it can still be corrected (plan §9).

For each output: who holds its current work (task, state, claim epoch, exact host turn or
process), the exact approved input, project, task and output versions, elapsed and remaining
wall budget, its AI reservations and usage coverage, current state, blockers, the latest safe
render start (unit A5's whole-batch forecast, read through ``forecast_path`` only), next
actions, its independent milestones and its elapsed-time breakdown.
"""
from __future__ import annotations

from studio.native_budget_breakdown import breakdown
from studio.native_budget_milestones import milestones
from studio.native_budget_usage import ai_usage
from studio.production.task_schema import LIVE, is_ai
from studio.production.tasks import tasks_of

A5_FORECAST = 'latest_safe_launch'
MAX_BLOCKERS = 12


def forecast_path(record: dict, clip_id: str, elapsed: float) -> dict:
    """The one seam to A5's latest-safe render start, nested as ``{status, path}``.

    ``status`` is ``forecast`` with A5's result as ``path`` (its own states, a duration it cannot
    use included), ``unknown`` while the forecast function is not in this engine, or
    ``forecast-defect`` naming any exception it raised (never swallowed into a verdict).
    """
    from studio import native_budget_forecast as forecast
    latest = getattr(forecast, A5_FORECAST, None)
    if latest is None:
        return {'status': 'unknown', 'path': None, 'reason': 'the whole-batch latest-safe forecast (unit A5) is not '
                                                             'in this engine'}
    try:
        return {'status': 'forecast', 'path': latest(record, clip_id, elapsed)}
    except Exception as error:  # a defect in the forecast is reported by name, never hidden or retried
        return {'status': 'forecast-defect', 'path': None, 'defect': f'{type(error).__name__}: {error}'[:400]}


def _mine(record: dict, clip_id: str) -> list[dict]:
    """The output's task rows in enqueue order."""
    rows = [task for task in tasks_of(record).values() if task['clipId'] == clip_id]
    return sorted(rows, key=lambda task: (task['enqueuedElapsed'], task['id']))


def owners(tasks: list[dict], elapsed: float) -> list[dict]:
    """Live work on the output with its exact claim and handle."""
    return [{'taskId': task['id'], 'kind': task['kind'], 'state': task['state'],
             'claimEpoch': task['claim']['epoch'] if task['claim'] else None, 'handle': task['handle'],
             'deadlineElapsed': task['deadlineElapsed'], 'overdue': elapsed >= task['deadlineElapsed']}
            for task in tasks if task['state'] in LIVE]


def versions(clip: dict, tasks: list[dict]) -> dict:
    """The approved content, bound project, current task inputs, running launch and latest output."""
    approval = clip['approvals'][-1] if clip['approvals'] else None
    current = {task['kind']: task for task in tasks if task['state'] != 'superseded'}
    running = [row for row in clip['attempts'] if row['status'] == 'running']
    project = clip['projects'][-1] if clip['projects'] else None
    return {'approvedContent': approval and {key: approval[key] for key in ('identity', 'titleSha256', 'script',
                                                                            'elapsed', 'recordedBy')},
            'approvalChanges': max(0, len(clip['approvals']) - 1),
            'project': project and {key: project[key] for key in ('path', 'key', 'projectHash')},
            'tasks': [{'taskId': task['id'], 'kind': task['kind'], 'version': task['version'],
                       'inputFingerprint': task['inputFingerprint'], 'state': task['state']}
                      for task in current.values()],
            'runningLaunches': [{'attemptId': row['id'], 'route': row['route'], 'inputIdentity': row['identity'],
                                 'admittedElapsed': row['admittedElapsed']} for row in running],
            'output': clip['deliveries'][-1] if clip['deliveries'] else None}


def wall_budget(record: dict, clip: dict, elapsed: float) -> dict:
    """Elapsed and remaining wall time against the output's deadlines (holds never subtract)."""
    deadlines = record['deadlines']
    return {'elapsedSeconds': round(elapsed, 1), 'addedAfterStart': clip['addedAfterStart'],
            'preparationRemainingSeconds': round(deadlines['preparationSeconds'] - elapsed, 1),
            'launchCutoffRemainingSeconds': round(deadlines['deliverySeconds'] - deadlines['handoffReserveSeconds']
                                                  - elapsed, 1),
            'deliveryRemainingSeconds': round(deadlines['deliverySeconds'] - elapsed, 1)}


def current_state(clip: dict, tasks: list[dict], found: dict) -> str:
    """One word for where the output is, by the strongest evidence first."""
    routes = {row['route'] for row in clip['attempts'] if row['status'] == 'running'}
    states = {task['state'] for task in tasks if is_ai(task)}
    ordered = (('handed-off', clip['state'] == 'handed-off'), ('visible', found['visibleMp4']['status'] == 'visible'),
               ('rendering', bool(routes - {'preview'})), ('previewing', 'preview' in routes),
               ('encoded-not-visible', found['encoding']['status'] == 'encoded'),
               ('ai-work-in-progress', bool(states & set(LIVE))), ('ready-awaiting-dispatch', 'ready' in states),
               ('blocked', 'blocked' in states))
    return next((name for name, holds in ordered if holds), 'idle')


def _task_blocker(task: dict, elapsed: float) -> str | None:
    """Why one task holds the output back, if it does."""
    name = f'task {task["id"]} ({task["kind"]})'
    if task['state'] == 'blocked':
        return f'{name} is blocked: {task["reason"]}'
    if task['state'] == 'failed' and task['supersededBy'] is None:
        return f'{name} failed: {task["failure"]["category"]}: {task["failure"]["detail"]}'
    if task['state'] == 'cancel-requested':
        return f'{name} was asked to stop; its termination is not confirmed'
    if task['state'] in LIVE and elapsed >= task['deadlineElapsed']:
        return f'{name} is past its deadline ({task["deadlineElapsed"]:.0f}s)'
    return None


def blockers(record: dict, clip: dict, tasks: list[dict], elapsed: float) -> list[str]:
    """Blocked, failed, stopping or overdue tasks, a failed last launch and a missing project."""
    rows = [reason for reason in (_task_blocker(task, elapsed) for task in tasks) if reason]
    last = clip['attempts'][-1] if clip['attempts'] else None
    if last and last['status'] in ('failed', 'abandoned'):
        failure = last['failure'] or {}
        rows.append(f'the last {last["route"]} launch {last["status"]}: {failure.get("category")} '
                    f'({failure.get("signature")})')
    if clip['outputSeconds'] is None and elapsed >= record['deadlines']['draftDecisionSeconds']:
        rows.append('no launch has recorded this output\'s duration, so no render can be forecast')
    return rows[:MAX_BLOCKERS]


def next_actions(clip: dict, existing: list[str], found: dict) -> list[str]:
    """The batch advice plus what the milestones add: an off-clock hand-off, an unproven one, work to stop."""
    rows, visible = list(existing), found['visibleMp4']
    if visible['status'] == 'confirmed-not-on-batch-clock':
        rows.append(f'record the visible hand-off on the batch clock: native_batch.py handoff --clip '
                    f'{visible["delivery"]["clipId"]} --confirmation {visible["evidence"]}')
    elif clip['state'] == 'handed-off' and visible['status'] != 'visible':
        rows.append('handed off without a recorded visible hand-off confirmation; report the visible hand-off '
                    'as unproven')
    if visible['status'] == 'visible' and found['cleanup']['status'] == 'pending':
        rows.append('visible: start no further autonomous work on this output; its cleanup is still pending')
    return rows


def output_status(record: dict, clip_id: str, elapsed: float, inputs: dict) -> dict:
    """Everything §9 asks of one output. inputs: {'verdicts', 'transcripts', 'timing', 'events', 'actions'}."""
    clip, tasks = record['clips'][clip_id], _mine(record, clip_id)
    found = milestones(record, clip_id, elapsed, inputs['verdicts'])
    return {'owners': owners(tasks, elapsed), 'versions': versions(clip, tasks),
            'wallBudget': wall_budget(record, clip, elapsed), 'ai': ai_usage(record, clip_id, inputs['transcripts']),
            'state': current_state(clip, tasks, found), 'blockers': blockers(record, clip, tasks, elapsed),
            'forecast': forecast_path(record, clip_id, elapsed),
            'nextActions': next_actions(clip, inputs['actions'], found), 'milestones': found,
            'elapsedBreakdown': breakdown(record, elapsed, inputs['timing'], (clip_id, inputs['events']))}
