"""Durable Short capacity accounting; historical and Long clocks keep their policy.

Only scheduler observations settle excluded time. A missing heartbeat leaves the
interval counted and visible as uncertain. Transactions checkpoint productive
work before changing it, so parallel work is never deducted as queue waiting.
"""
from __future__ import annotations

import math

POLICY = 'short-render-capacity-v1'
MAX_GAP_SECONDS = 6.0
MAX_WORKERS = 64


def new_clock() -> dict:
    """Create the accounting policy for a newly authorized Short."""
    return {'policy': POLICY, 'excludedSeconds': 0.0, 'pendingSeconds': 0.0,
            'observedElapsed': 0.0, 'uncertainSeconds': 0.0, 'workers': {}, 'taskCredits': {}, 'deliveryCredits': {}}


def excluded(clip: dict) -> float:
    """Return settled credit only; an open wait grants no speculative time."""
    return clip.get('capacityClock', {}).get('excludedSeconds', 0.0)


def enabled(clip: dict) -> bool:
    """Only explicitly versioned Short authorizations use this policy."""
    return clip.get('output', {}).get('format', 'short') == 'short' \
        and clip.get('capacityClock', {}).get('policy') == POLICY


def productive(record: dict, clip_id: str, workers: dict) -> bool:
    """Owners and tasks outside the proven waiting set count as useful work."""
    if any(row['state'] != 'waiting' for row in workers.values()):
        return True
    tasks = {row['taskId'] for row in workers.values() if row['taskId']}
    attempts = {row['attemptId'] for row in workers.values() if row['attemptId']}
    clip = record['clips'][clip_id]
    if any(row['status'] == 'running' and row['id'] not in attempts for row in clip['attempts']):
        return True
    return any(row['clipId'] in (None, clip_id) and row['kind'] != 'director'
               and (row['state'] in ('claimed', 'running', 'cancel-requested') or row.get('unresolved'))
               and row['id'] not in tasks for row in record['production']['tasks'].values())


def checkpoint(record: dict, elapsed: float) -> None:
    """Accumulate eligible intervals before each authority state transition."""
    for clip_id, clip in record['clips'].items():
        if enabled(clip) and record['status'] == 'active' and clip['state'] != 'handed-off':
            _checkpoint_clip(record, clip_id, elapsed)


def _checkpoint_clip(record: dict, clip_id: str, elapsed: float) -> None:
    """Keep potential credit pending until a fresh scheduler observation."""
    clip = record['clips'][clip_id]
    clock = clip['capacityClock']
    delta = max(0.0, elapsed - clock['observedElapsed'])
    clock['observedElapsed'] = max(elapsed, clock['observedElapsed'])
    workers = clock['workers']
    waiting = [row for row in workers.values() if row['state'] == 'waiting']
    hold_open = bool(record['holds']) and record['holds'][-1]['endElapsed'] is None
    if not waiting or hold_open or productive(record, clip_id, workers):
        return
    if any(elapsed - row['seenElapsed'] > MAX_GAP_SECONDS for row in waiting):
        clock['uncertainSeconds'] += clock['pendingSeconds'] + delta
        clock['pendingSeconds'] = 0.0
        return
    clock['pendingSeconds'] += delta


def observe_worker(record: dict, context: dict, observation: dict, elapsed: float) -> float:
    """Record one scheduler/owner state after checkpointing the preceding interval."""
    clip = record['clips'][context['clipId']]
    if not enabled(clip) or record['status'] != 'active' or clip['state'] == 'handed-off':
        return 0.0
    clock, key = clip['capacityClock'], context['workerId']
    prior = clock['workers'].get(key)
    if prior and prior['state'] == 'waiting':
        bucket = 'uncertainSeconds' if observation['state'] == 'finished' else 'excludedSeconds'
        clock[bucket] += clock['pendingSeconds']
        clock['pendingSeconds'] = 0.0
    if observation['state'] == 'finished':
        clock['workers'].pop(key, None)
        return clock['excludedSeconds']
    if key not in clock['workers'] and len(clock['workers']) >= MAX_WORKERS:
        raise ValueError('Short capacity accounting has too many unsettled owners')
    identity = {name: context[name] for name in ('supervisor', 'boot') if name in context}
    clock['workers'][key] = {**observation, **identity, 'seenElapsed': elapsed,
                             'taskId': context.get('taskId'), 'attemptId': context.get('attemptId')}
    return clock['excludedSeconds']


def task_deadline(record: dict, task: dict) -> float:
    """Translate clip task deadlines by earned idle capacity time; running AI earns none."""
    if task['kind'] == 'director':
        from studio.production.formats import run_deadlines
        return run_deadlines(record)['deliverySeconds']
    clip = record['clips'].get(task['clipId'], {})
    if not enabled(clip):
        return task['deadlineElapsed']
    clock = clip['capacityClock']
    origin = clock.get('taskCredits', {}).get(task['id'])
    credit = max(0.0, excluded(clip) - origin) if origin is not None else 0.0
    return task['deadlineElapsed'] + credit


def status(clip: dict, elapsed: float) -> dict:
    """Report wall, counted and uncertain time separately."""
    authorized = clip.get('output', {}).get('authorizedElapsed', 0.0)
    clock = clip.get('capacityClock', {})
    return {'timingPolicy': clock.get('policy', 'elapsed-wall-v1'),
            'totalElapsedSeconds': max(0.0, elapsed - authorized),
            'countedProductionSeconds': max(0.0, elapsed - authorized - excluded(clip)),
            'excludedRenderQueueSeconds': excluded(clip),
            'uncertainQueueSeconds': clock.get('uncertainSeconds', 0.0),
            'capacityWaits': list(clock.get('workers', {}).values())}


def problem(clip: dict) -> str | None:
    """Validate the additive policy without applying it to historical records."""
    if 'capacityClock' not in clip:
        return None
    clock = clip['capacityClock']
    keys = set(new_clock())
    if type(clock) is not dict or set(clock) != keys or clock['policy'] != POLICY:
        return 'Short capacity clock shape/policy'
    numeric = ('excludedSeconds', 'pendingSeconds', 'observedElapsed', 'uncertainSeconds')
    if any(not _number(clock[name]) for name in numeric) \
            or clock['excludedSeconds'] + clock['pendingSeconds'] > clock['observedElapsed'] + 1e-6:
        return 'Short capacity clock totals'
    workers, credits = clock['workers'], clock['taskCredits']
    if type(clock['deliveryCredits']) is not dict or any(not _number(value) for value in clock['deliveryCredits'].values()):
        return 'Short delivery clock credits'
    if type(workers) is not dict or len(workers) > MAX_WORKERS or type(credits) is not dict:
        return 'Short capacity clock owners'
    if any(not isinstance(key, str) or not _number(value) for key, value in credits.items()):
        return 'Short capacity task credits'
    return next((issue for row in workers.values() if (issue := _worker_problem(row))), None)


def _number(value: object) -> bool:
    """Require finite nonnegative seconds."""
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _worker_problem(row: object) -> str | None:
    """Validate the bounded scheduler evidence retained for one owner."""
    keys = {'state', 'resource', 'evidence', 'seenElapsed', 'taskId', 'attemptId'}
    if type(row) is not dict or set(row) - {'supervisor', 'boot'} != keys or row['state'] not in ('working', 'waiting') \
            or not _number(row['seenElapsed']):
        return 'Short capacity worker state'
    if ('supervisor' in row) != ('boot' in row) or 'supervisor' in row and not _owner_identity(row):
        return 'Short capacity worker process identity'
    if any(type(row[key]) is not str or len(row[key]) > 2048 for key in ('resource', 'evidence')):
        return 'Short capacity worker evidence'
    if any(row[key] is not None and (type(row[key]) is not str or len(row[key]) > 128)
           for key in ('taskId', 'attemptId')):
        return 'Short capacity worker identity'
    return None


def _owner_identity(row: dict) -> bool:
    """New workers retain an exact owner identity; historical rows remain readable."""
    owner = row['supervisor']
    return type(row['boot']) is str and bool(row['boot']) and type(owner) is dict \
        and set(owner) == {'pid', 'pgid', 'started'} \
        and all(type(owner[key]) is int and owner[key] > 1 for key in ('pid', 'pgid')) \
        and type(owner['started']) is str and bool(owner['started'].strip())


def record_delivery(clip: dict, attempt_id: str) -> None:
    """Freeze earned credit at delivery; future waits cannot make a late delivery timely."""
    if enabled(clip):
        clip['capacityClock']['deliveryCredits'][attempt_id] = excluded(clip)


def delivery_deadline(record: dict, clip: dict, delivery: dict) -> float:
    """Evaluate a receipt against its contemporaneous production allowance."""
    from studio.production.formats import clip_deadlines
    end = clip_deadlines(record, clip)['deliverySeconds']
    if not enabled(clip):
        return end
    earned = clip['capacityClock']['deliveryCredits'].get(delivery['attemptId'], 0.0)
    return end - excluded(clip) + earned


def settle_task_workers(record: dict, task_id: str) -> list[str]:
    """Retire a task's owners only after its watchdog proves all owned sessions ended.

    Callers must hold the authority lock and supply actual cleanup proof; ordinary
    completion callbacks and heartbeat expiry must never invoke this function.
    """
    removed = []
    for clip in record['clips'].values():
        clock = clip.get('capacityClock')
        if clock is None:
            continue
        keys = [key for key, row in clock['workers'].items() if row['taskId'] == task_id]
        if keys:
            clock['uncertainSeconds'] += clock['pendingSeconds']
            clock['pendingSeconds'] = 0.0
        for key in keys:
            del clock['workers'][key]
        removed.extend(keys)
    return removed
