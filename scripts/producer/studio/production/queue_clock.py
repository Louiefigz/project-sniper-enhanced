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
from studio.production import queue_stall
from studio.production.task_schema import LIVE, holds_slot, is_ai

# The longest gap between two observations of one waiting owner that still credits the interval (P1 Step B13, P2):
# the admission loop's own bounds, summed: a 2 s poll sleep (native_run_admission.wait_capacity) + the 10 s ledger
# wait (native_work_pool_state.LEDGER_WAIT_SECONDS) + 3 host inspections of 3 s (INSPECTION_ATTEMPTS x
# native_work_pool_policy.HOST_IDENTITY_TIMEOUT_SECONDS) + 1.5 s of their backoff + one 5 s process-table read
# (native_budget_launch.PS_TIMEOUT_SECONDS, read by recovery_evidence) = 27.5 s, rounded up. A longer gap (a laptop
# sleep, a stopped process, an unbounded authority lock wait) is counted, as uncertain.
POLL_BOUND_SECONDS = 30.0
# After these a waiting row's pending interval is uncertain, never credit: the owner ended, or a refusal that is not
# for occupied capacity (P1 Step B12, C13) could not confirm it.
UNCONFIRMING = ('finished', 'unverified')
SETTLED = 'capacitySettled'   # the key a settling event (or one of its changes) carries entries under (X189 F2)


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


def productive(record: dict, clip_id: str, workers: dict, elapsed: float) -> bool:
    """Owners and tasks outside the proven waiting set count as useful work at ``elapsed`` (P1 Step B2, C4).

    Useful work: an owner row that is not waiting; on a v2 clock, the enrolled director holding its slot while it
    has not declared itself idle for this Short (``director_activity``); a running attempt other than the waited
    one; and any task of this Short, or run-scoped, other than the director and the waited owners' tasks, that is
    live, ready AI or check work that can still be claimed, or ended unresolved but not ``completed``. A completed
    turn does no work; only its slot evidence is missing (X99(2)). Any other unresolved end may still be running.
    Blocked tasks wait for their prerequisites (often the render itself) and do not count.
    """
    if any(row['state'] != 'waiting' for row in workers.values()):
        return True
    tasks = {row['taskId'] for row in workers.values() if row['taskId']}
    attempts = {row['attemptId'] for row in workers.values() if row['attemptId']}
    clip = record['clips'][clip_id]
    if any(row['status'] == 'running' and row['id'] not in attempts for row in clip['attempts']):
        return True
    rows = record['production']['tasks'].values()
    if writable(clip) and clip['capacityClock']['directorWorking'] \
            and any(row['kind'] == 'director' and holds_slot(row) for row in rows):
        return True
    return any(row['clipId'] in (None, clip_id) and row['kind'] != 'director' and row['id'] not in tasks
               and _task_is_work(record, row, elapsed) for row in rows)


def _task_is_work(record: dict, row: dict, elapsed: float) -> bool:
    """Live work, ready AI or check work, or an unresolved end that is not a completion (X99(2)).

    A ready creative task whose claim is refused for good (its output's preparation deadline has passed:
    ``claim_admission.authoring_closed``, the claim refusal's own rule) can never run, so it is not work (X183 m6);
    the director should cancel it.
    """
    if row['state'] in LIVE or (row.get('unresolved') and row['state'] != 'completed'):
        return True
    if row['state'] != 'ready' or not (is_ai(row) or row['kind'] == 'check'):
        return False
    from studio.production.claim_admission import authoring_closed
    return not authoring_closed(record, row, elapsed)


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
    # Work is judged at the interval's start: a task that stops being work mid-interval still counts for it.
    if not waiting or hold_open or productive(record, clip_id, workers, elapsed - delta):
        return
    if any(elapsed - row['seenElapsed'] > POLL_BOUND_SECONDS for row in waiting):
        clock['uncertainSeconds'] += clock['pendingSeconds'] + delta
        clock['pendingSeconds'] = 0.0
        return
    clock['pendingSeconds'] += delta


def verified_wait(row: dict) -> bool:
    """A waiting row whose pool evidence shows occupied capacity: the capacity class, a ticket and occupants (C11)."""
    return row.get('waitClass') == 'capacity' and type(row.get('ticket')) is int and bool(row.get('occupants'))


def observe_worker(record: dict, context: dict, observation: dict, elapsed: float) -> float:
    """Record one scheduler/owner state after checkpointing the preceding interval; return the settled credit.

    The row keeps the observation's pool evidence (``ticket``, ``occupants``, ``waitClass``; an observation
    without it, a working owner's, records none). A waiting row's pending interval becomes credit only when that
    row was a verified wait (``verified_wait``), the next state is not ``UNCONFIRMING`` (the owner finished, or an
    ``unverified`` refusal that is not for capacity, C13) and the Short's stall is not truncated
    (``queue_stall.suppressed``); otherwise it is counted, as uncertain (P1 Step B4). Then ``queue_stall.track``
    names or clears the Short's ``capacity-stalled`` state (M-050). A v1 clock is read-only: nothing is recorded
    and its earned credit is returned (0.0 for a clip without one).
    """
    clip = record['clips'][context['clipId']]
    if not writable(clip):
        return excluded(clip)
    if record['status'] != 'active' or clip['state'] == 'handed-off':
        return 0.0
    clock, key = clip['capacityClock'], context['workerId']
    prior = clock['workers'].get(key)
    if prior and prior['state'] == 'waiting':
        credited = observation['state'] not in UNCONFIRMING and verified_wait(prior) \
            and not queue_stall.suppressed(clock)
        clock['excludedSeconds' if credited else 'uncertainSeconds'] += clock['pendingSeconds']
        clock['pendingSeconds'] = 0.0
    if observation['state'] == 'finished':
        clock['workers'].pop(key, None)
    else:
        _record_row(clock, context, observation, elapsed)
    queue_stall.track(clock, elapsed)   # the named stall state (M-050); credit never stops because time passed
    return clock['excludedSeconds']


def _record_row(clock: dict, context: dict, observation: dict, elapsed: float) -> None:
    """Write the owner's row with its identity and its pool evidence (none for a working owner)."""
    key = context['workerId']
    if key not in clock['workers'] and len(clock['workers']) >= MAX_WORKERS:
        raise ValueError('Short capacity accounting has too many unsettled owners')
    identity = {name: context[name] for name in ('supervisor', 'boot') if name in context}
    clock['workers'][key] = {**observation, **identity, 'seenElapsed': elapsed,
                             'taskId': context.get('taskId'), 'attemptId': context.get('attemptId'),
                             'ticket': observation.get('ticket'), 'occupants': list(observation.get('occupants', ())),
                             'waitClass': observation.get('waitClass')}


def record_task_origin(record: dict, task_id: str, clip_id: str | None) -> None:
    """Record where a new task's credit starts: its Short's settled credit now (C6, P1 Step B8).

    A clip-scoped task records on its clip's clock (a v1 clock too; its credit since then stays 0). A run-scoped
    task (the caller passes no director) records on every writable Short clock, so it later gains the largest
    credit any Short earned after it was enqueued, never retroactive credit; a Long has no clock and adds nothing.
    """
    clips = [record['clips'][clip_id]] if clip_id else [clip for clip in record['clips'].values() if writable(clip)]
    for clip in clips:
        if 'capacityClock' in clip:
            clip['capacityClock']['taskCredits'].setdefault(task_id, excluded(clip))


def _credit_since(clip: dict, task_id: str) -> float | None:
    """The clip's settled credit since the task's recorded origin; None when it recorded none."""
    origin = clip['capacityClock'].get('taskCredits', {}).get(task_id)
    return max(0.0, excluded(clip) - origin) if origin is not None else None


def task_deadline(record: dict, task: dict) -> float:
    """Translate task deadlines by earned idle capacity time; running AI earns none.

    A clip task gains its Short's credit since its origin. A run-scoped task gains the largest credit any
    writable Short earned since its origin there (C6), never past its root's deadline, the run's delivery deadline
    (X190 m1: its parent, the director, holds that one); the director keeps the run's delivery deadline.
    """
    from studio.production.formats import run_deadlines
    if task['kind'] == 'director':
        return run_deadlines(record)['deliverySeconds']
    if task['clipId'] is None:
        credits = [_credit_since(clip, task['id']) for clip in record['clips'].values() if writable(clip)]
        return min(task['deadlineElapsed'] + max((credit for credit in credits if credit is not None), default=0.0),
                   run_deadlines(record)['deliverySeconds'])
    clip = record['clips'].get(task['clipId'], {})
    if not enabled(clip):
        return task['deadlineElapsed']
    return task['deadlineElapsed'] + (_credit_since(clip, task['id']) or 0.0)


def status(clip: dict, elapsed: float) -> dict:
    """Report wall, counted and uncertain time separately, and a v2 Short's stall state and bound (M-050).

    ``capacityState`` is what close and the actions act on (``queue_stall.shown_state``): a handed-off Short is not
    stalled (X190 s1); its raw row stays under ``stall``. A v2 Short's times stop at its deliveries and its visible
    hand-off (M-054, C12: ``queue_handoff.frozen_times``).
    """
    from studio.production.queue_handoff import frozen_times
    authorized = clip.get('output', {}).get('authorizedElapsed', 0.0)
    clock = clip.get('capacityClock', {})
    v2 = clock.get('policy') == POLICY
    running = (max(0.0, elapsed - authorized), max(0.0, elapsed - authorized - excluded(clip)))
    return {'capacityState': queue_stall.shown_state(clip), 'stall': clock['stall'] if v2 else None,
            'stallBoundSeconds': queue_stall.stall_seconds() if v2 else None,
            'timingPolicy': clock.get('policy', 'elapsed-wall-v1'),
            'totalElapsedSeconds': running[0], 'countedProductionSeconds': running[1],
            'excludedRenderQueueSeconds': excluded(clip),
            'uncertainQueueSeconds': clock.get('uncertainSeconds', 0.0),
            'capacityWaits': list(clock.get('workers', {}).values()),
            **(frozen_times(clip, authorized, running) if v2 else {})}


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
    completion callbacks and heartbeat expiry must never invoke this function. The clip's pending interval
    becomes uncertain only when no waiting owner remains in it: another task's waiting owner keeps the pending
    interval it is accruing (P1 Step B5, P6). A stalled v2 clock is then re-tracked, so its stall clears with the
    waits it named (X184 m2); a settlement never names a stall (X190 n1: the next observation's window does, and
    writes its event). Returns the removed owner keys; ``settle_task_capacity`` also returns what the settling
    event carries for the audit.
    """
    return [key for keys in _settle_rows(record, task_id).values() for key in keys]


def settle_task_capacity(record: dict, task_id: str) -> dict:
    """``settle_task_workers``, returning each v2 Short's settlement entry for its settling event (X189 F2): the
    settled credit and the removed owners, which ``queue_audit`` reads to close the waiting window and anchor the
    total. Only a Short whose rows were removed has one; the entry's size is bounded in ``native_budget_store``."""
    from studio.production.queue_audit import settlement_entry
    return {clip_id: settlement_entry(record['clips'][clip_id], keys)
            for clip_id, keys in _settle_rows(record, task_id).items() if writable(record['clips'][clip_id])}


def _settle_rows(record: dict, task_id: str) -> dict:
    """Remove a task's owner rows from every clock; ``{clipId: removed keys}`` for each clip that had some."""
    removed = {}
    for clip_id, clip in record['clips'].items():
        clock = clip.get('capacityClock')
        keys = [key for key, row in (clock or {}).get('workers', {}).items() if row['taskId'] == task_id]
        for key in keys:
            del clock['workers'][key]
        if keys and not any(row['state'] == 'waiting' for row in clock['workers'].values()):
            clock['uncertainSeconds'] += clock['pendingSeconds']
            clock['pendingSeconds'] = 0.0
        if keys and writable(clip) and queue_stall.state(clip) == queue_stall.STALLED:
            queue_stall.track(clock, clock['observedElapsed'])   # clears only: the waits it named are gone
        if keys:
            removed[clip_id] = keys
    return removed
