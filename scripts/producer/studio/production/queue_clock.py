"""Durable Short capacity accounting; historical and Long clocks keep their policy.

Only scheduler observations settle excluded time. A missing heartbeat leaves the
interval counted and visible as uncertain. Transactions checkpoint productive
work before changing it, so parallel work is never deducted as queue waiting.

New Shorts get v2 clocks (``queue_clock_schema``). A v1 clock, written by the P0
engine, is read-only here: it is read for deadlines, delivery credit and status,
and never advanced (``writable``); a delivery still freezes its credit.
"""
from __future__ import annotations

from studio.production.queue_clock_schema import (  # noqa: F401  new_clock and problem are re-exported
    MAX_WORKERS, POLICIES, POLICY, new_clock, problem,
)

MAX_GAP_SECONDS = 6.0


def excluded(clip: dict) -> float:
    """Return settled credit only; an open wait grants no speculative time."""
    return clip.get('capacityClock', {}).get('excludedSeconds', 0.0)


def enabled(clip: dict) -> bool:
    """A Short with a versioned capacity clock: its deadlines move by its settled credit."""
    return clip.get('output', {}).get('format', 'short') == 'short' \
        and clip.get('capacityClock', {}).get('policy') in POLICIES


def writable(clip: dict) -> bool:
    """Only v2 clocks advance under this engine; a v1 clock keeps what it earned (P1 Step B1)."""
    return enabled(clip) and clip['capacityClock']['policy'] == POLICY


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
    """Accumulate eligible intervals before each authority state transition (v2 clocks only)."""
    for clip_id, clip in record['clips'].items():
        if writable(clip) and record['status'] == 'active' and clip['state'] != 'handed-off':
            _checkpoint_clip(record, clip_id, elapsed)


def _checkpoint_clip(record: dict, clip_id: str, elapsed: float) -> None:
    """Keep potential credit pending until a fresh scheduler observation (``checkpoint`` passes no v1 clock)."""
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
    """Record one scheduler/owner state after checkpointing the preceding interval; return the settled credit.

    A v1 clock is read-only: nothing is recorded and its earned credit is returned (0.0 for a clip without one).
    """
    clip = record['clips'][context['clipId']]
    if not writable(clip):
        return excluded(clip)
    if record['status'] != 'active' or clip['state'] == 'handed-off':
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
                             'taskId': context.get('taskId'), 'attemptId': context.get('attemptId'),
                             'ticket': None, 'occupants': [], 'waitClass': None}  # no pool evidence (M-047 adds it)
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
