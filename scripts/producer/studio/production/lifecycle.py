"""Run shutdown: delivery and shutdown are separate, and unresolved work is never released.

A clip's hand-off opens its MP4 even while a critic's termination is unconfirmed;
it freezes that clip's work: unlaunched tasks are cancelled and live ones are asked
to stop (their slots stay held). Closing a run first reconciles the evidence and
freezes everything the same way. It becomes ``closed`` only when every owned task
has ended with no unresolved resource and no media launch is running; otherwise it
becomes ``draining``. A draining run admits no new work, cannot be archived, and
blocks a new run from starting, so shutdown cannot be used to escape reservations.
Asking to close it again settles it once the evidence allows.
"""
from __future__ import annotations

from studio.production.queue_clock import task_deadline

from studio.production.callbacks import request_cancel
from studio.production.host_contract import CHILD_ENVIRONMENT, USAGE_FIELDS, clip_text
from studio.production.reconcile import Observation, reconcile_tasks
from studio.production.task_schema import LIVE, TASK_STATES, holds_slot, holds_unresolved_work, is_ai, settled
from studio.production.tasks import TaskRefused, active_ai, tasks_of


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


def begin_drain(record: dict, reason: str, elapsed: float) -> list[str]:
    """Stop admitting work and freeze every task; the run stays unreleased until it settles."""
    if record['status'] != 'active':
        raise TaskRefused(f'Batch {record["batchId"]} is {record["status"]}; only an active batch starts draining')
    record['status'] = 'draining'
    record['production']['drain'] = {'startedElapsed': elapsed, 'reason': clip_text(reason)}
    return freeze(record, None, f'run draining: {reason}', elapsed)


def close_or_drain(record: dict, elapsed: float, observation: Observation) -> dict:
    """After ``close_refusal`` passed: reconcile, freeze, then close if everything settled, else drain."""
    changes = reconcile_tasks(record, observation, elapsed)
    frozen = freeze(record, None, 'batch closing', elapsed) if record['status'] == 'active' else []
    open_tasks, running = unsettled(record), running_attempts(record)
    if not open_tasks and not running:
        record['status'], record['closedAtElapsed'] = 'closed', elapsed
    elif record['status'] == 'active':
        record['status'] = 'draining'
        record['production']['drain'] = {'startedElapsed': elapsed, 'reason': 'close requested with unsettled work'}
    return {'status': record['status'], 'reconciled': changes, 'frozen': frozen, 'unsettled': open_tasks,
            'runningAttempts': running}


def archive_refusal(record: dict) -> str | None:
    """Only a closed batch with no running launch and no unresolved task leaves resolution."""
    running = [row for clip in (record.get('clips') or {}).values() if type(clip) is dict
               for row in clip.get('attempts', []) if type(row) is dict and row.get('status') == 'running']
    if record.get('status') != 'closed' or running:
        return 'Only a closed batch whose launches have all finished can be archived'
    if holds_unresolved_work(record):
        return ('The batch still holds production tasks that have not ended or hold an unresolved resource; '
                'settle them with the engine that started it')
    return None


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
