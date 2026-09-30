"""Run shutdown: delivery and shutdown are separate, and closure never releases unresolved work.

A clip's hand-off opens its MP4 even while a critic's termination is unconfirmed;
it freezes that clip's work: unlaunched tasks are cancelled and live ones are asked
to stop (their slots stay held). Draining and closing freeze every task except the enrolled
director, whose batch assignment ends only at the recorded closure or its own end (X29).
Closing reconciles first, then drains while media is live (no closure is recorded). Otherwise
it ends the director's assignment, revokes live AI work (state and slot kept) and closes with
``production.closure`` listing every task still holding a slot or an unresolved resource;
those rows reach the host record inside the closing transaction (X37, X79). A draining run
admits no new work and blocks a new run; a closed one is archived only when its closure and
the host record list all its unsettled work.
"""
from __future__ import annotations

from pathlib import Path

from studio.production.queue_clock import task_deadline

from studio.production.callbacks import request_cancel
from studio.production.host_contract import CHILD_ENVIRONMENT, USAGE_FIELDS, clip_text
from studio.production.reconcile import Observation, reconcile_tasks
from studio.production.task_end import settle_end
from studio.production.task_schema import LIVE, TASK_STATES, finish, holds_slot, holds_unresolved_work, is_ai, settled
from studio.production.tasks import TaskRefused, active_ai, tasks_of
from studio.production.unresolved_executions import append_unresolved, recorded_task_ids


def unsettled(record: dict) -> list[str]:
    """Tasks that have not ended, or ended still holding a resource."""
    return sorted(task_id for task_id, task in tasks_of(record).items() if not settled(task))


def running_attempts(record: dict) -> list[str]:
    """Media launches still running in the authority."""
    return [attempt['id'] for clip in record['clips'].values() for attempt in clip['attempts']
            if attempt['status'] == 'running']


def freeze(record: dict, clip_id: str | None, reason: str, elapsed: float) -> list[str]:
    """Cancel unlaunched work and request cancellation of live work, for one clip or the whole run."""
    frozen = []
    for task in list(tasks_of(record).values()):
        if clip_id is not None and task['clipId'] != clip_id:
            continue
        if request_cancel(record, task['id'], reason, elapsed).changed:
            frozen.append(task['id'])
    return frozen


def _enrolled_director(record: dict) -> dict | None:
    """The live, non-revoked director task: the run's enrolled director, if any."""
    return next((task for task in tasks_of(record).values()
                 if task['kind'] == 'director' and task['state'] in LIVE and not task['revoked']), None)


def _freeze_run(record: dict, reason: str, elapsed: float) -> list[str]:
    """Freeze every task except the enrolled director (its assignment ends at closure or its own end, X29)."""
    director = _enrolled_director(record)
    others = [task_id for task_id, task in tasks_of(record).items() if task is not director]
    return [task_id for task_id in others if request_cancel(record, task_id, reason, elapsed).changed]


def begin_drain(record: dict, reason: str, elapsed: float) -> list[str]:
    """Stop admitting work and freeze every task but the enrolled director; the run stays unreleased until it closes."""
    if record['status'] != 'active':
        raise TaskRefused(f'Batch {record["batchId"]} is {record["status"]}; only an active batch starts draining')
    record['status'] = 'draining'
    record['production']['drain'] = {'startedElapsed': elapsed, 'reason': clip_text(reason)}
    return _freeze_run(record, f'run draining: {reason}', elapsed)


def _ai_host(task: dict) -> str | None:
    """The AI host of the task's own host handle; with no handle, of its host claimer; else None (gate M3, X114 m9).

    A process-handle execution is a process, not a host's turn, so its row is null: it counts against every host
    (fail closed).
    """
    handle = task['handle'] if task['handle'] is not None else (task['claim'] or {}).get('claimer')
    return handle['host'] if handle is not None and handle['type'] == 'host' else None


def _closure_rows(record: dict) -> list[dict]:
    """One row per task still holding a slot or an unresolved resource, in the host record's row shape."""
    return [{'taskId': task['id'], 'kind': task['kind'], 'state': task['state'], 'host': _ai_host(task),
             'hostProcess': None, 'reason': task['reason']} for task in tasks_of(record).values() if not settled(task)]


def record_closure(record: dict, root: Path) -> int:
    """Append the closure's rows the host record lacks; idempotent per (batchId, taskId) (X37, X79)."""
    rows = record['production'].get('closure', {}).get('unresolvedAtClose')
    return append_unresolved(root, record['batchId'], rows) if rows else 0


def _close(record: dict, elapsed: float, root: Path) -> dict:
    """Steps (3)-(7): end the director's assignment, freeze, revoke live AI work, record the closure, append it.

    The result names the director's end (its task and end fields) and the revoked tasks for the close event.
    """
    director, ended = _enrolled_director(record), None
    if director is not None:
        proof = settle_end(director, 'closure')     # (3) released (X29); never cancel-requested or revoked by close
        finish(director, 'cancelled' if director['cancelRequested'] else 'completed', elapsed, proof.note)
        ended = {'taskId': director['id'], **proof.event_fields()}
    frozen = _freeze_run(record, 'batch closing', elapsed)                                        # (4)
    revoked = [task for task in tasks_of(record).values() if is_ai(task) and task['state'] in LIVE
               and not task['revoked']]
    for task in revoked:                                                                          # (5)
        task['revoked'] = True
    record['status'], record['closedAtElapsed'] = 'closed', elapsed                               # (6)
    record['production']['closure'] = {'closedElapsed': elapsed, 'unresolvedAtClose': _closure_rows(record)}
    record_closure(record, root)                                                                  # (7)
    return {'frozen': frozen, 'directorEnd': ended, 'revoked': [task['id'] for task in revoked]}


def close_or_drain(record: dict, elapsed: float, observation: Observation, root: Path) -> dict:
    """After ``close_refusal`` passed: (1) reconcile; (2) drain while media is live, else close (steps 3-7)."""
    changes = reconcile_tasks(record, observation, elapsed)
    running = running_attempts(record)
    live_media = any(task['kind'] == 'media' and task['state'] in LIVE for task in tasks_of(record).values())
    result = {'frozen': [], 'directorEnd': None, 'revoked': []}
    if not running and not live_media:
        result = _close(record, elapsed, root)
    elif record['status'] == 'active':
        result['frozen'] = _freeze_run(record, 'batch closing', elapsed)
        record['status'] = 'draining'
        record['production']['drain'] = {'startedElapsed': elapsed, 'reason': 'close requested with unsettled work'}
    return {'status': record['status'], 'reconciled': changes, 'unsettled': unsettled(record),
            'runningAttempts': running, **result}


def archive_refusal(record: dict, root: Path) -> str | None:
    """Only a closed batch with no running launch, whose unsettled work its closure and the host record list."""
    running = [row for clip in (record.get('clips') or {}).values() if type(clip) is dict
               for row in clip.get('attempts', []) if type(row) is dict and row.get('status') == 'running']
    if record.get('status') != 'closed' or running:
        return 'Only a closed batch whose launches have all finished can be archived'
    if not holds_unresolved_work(record):
        return None
    listed = {row['taskId'] for row in record['production'].get('closure', {}).get('unresolvedAtClose', [])}
    open_tasks = set(unsettled(record))
    if open_tasks <= listed and open_tasks <= recorded_task_ids(root, record['batchId']):
        return None
    return (f'Batch {record["batchId"]} holds unresolved work not recorded at closure '
            '(production.closure/unresolved-executions.jsonl)')


def _usage_summary(tasks: list[dict]) -> dict:
    """Known cumulative usage per field, and how many AI tasks have no report (unknown, not zero)."""
    known = {field: sum(task['usage'][field] for task in tasks if task['usage'] and task['usage'][field] is not None)
             for field in USAGE_FIELDS}
    unknown = {field: sum(1 for task in tasks if not task['usage'] or task['usage'][field] is None)
               for field in USAGE_FIELDS}
    return {'known': known, 'unknownTasks': unknown}


def limitations(governance: dict | None) -> list[str]:
    """What the run must say it cannot enforce, from the host governance recorded at enrollment."""
    rows = [f'every host child starts from a clean environment ({", ".join(CHILD_ENVIRONMENT)}); an inherited '
            'provider key silently switches Claude Code to API-key billing']
    if governance is None or governance['mode'] == 'record-only':
        return ['no host capability was observed for this run: AI work is recorded and counted, nothing enforces '
                'its deadlines', *rows]
    if governance['mode'] == 'supervised':
        rows.insert(0, 'AI deadlines are enforced only while the coordinator is alive to interrupt the exact turn '
                       'and confirm its termination; absolute AI expiry is unsupported on this host')
    if 'directorEnrollment' in governance['unsupported']:
        rows.append('the running director is recorded and counted, not governed by the host')
    rows.append('tool cleanup after an interrupt is judged per task from its own host (Codex was not observed to '
                'end tools on interrupt; neither host on every end): such a slot stays unresolved until evidence or '
                'the operator\'s settlement while the run drains')
    rows.append('the director handle is self-declared at enrollment: no host adapter verifies it')
    return rows


def task_summary(record: dict, elapsed: float) -> dict:
    """Counts by state, AI reservations and usage coverage, governance, overdue work and what holds the run open."""
    tasks = list(tasks_of(record).values())
    ai_tasks = [task for task in tasks if is_ai(task) and task['charged']]
    ai, governance = record['production']['ai'], record['production']['governance']
    directors = [task['id'] for task in tasks if task['kind'] == 'director' and holds_slot(task)]
    overdue = sorted(task['id'] for task in tasks if task['state'] in LIVE and task['kind'] != 'director'
                     and elapsed >= task_deadline(record, task))
    return {'counts': {state: sum(1 for task in tasks if task['state'] == state) for state in TASK_STATES},
            'ai': {'slots': ai['slots'], 'active': active_ai(record), 'reservations': ai['reservations'],
                   'charged': ai['charged'], 'enrolledDirector': directors[0] if directors else None,
                   'usage': _usage_summary(ai_tasks)},
            'governance': governance, 'limitations': limitations(governance),
            'overdue': overdue, 'ready': sorted(task['id'] for task in tasks if task['state'] == 'ready'),
            'unresolved': sorted(task['id'] for task in tasks if task['unresolved']),
            'revoked': sorted(task['id'] for task in tasks if task['revoked']),
            'unsettled': unsettled(record), 'drain': record['production']['drain']}
