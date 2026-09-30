"""Closed production authority; running needs a handle and unresolved work holds its slot."""
from __future__ import annotations

import re

from studio.native_budget_schema import AI_POLICY, BOUNDS, ROUTES, SHA256
from studio.production.authorization_record import authorization_identity, authorization_problem  # noqa: F401
from studio.production.host_contract import (
    CAPABILITIES, HOSTS, MAX_COUNT, MODES, clip_text, encoded_length, finite_seconds, governance,
    parse_capabilities, valid_failure, valid_handle, valid_receipts, valid_usage,
)
from studio.production.host_verdicts import HOST_RECORDS
from studio.production.production_optional import PRODUCTION_OPTIONAL, optional_problem

TASK_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}')
VERSION = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}')
HEX32 = re.compile(r'[0-9a-f]{32}')
MAX_TASK_OWNERS = 16
# AI holds a host slot/reservation; media uses export reservations; code costs no AI.
TASK_KINDS = {'director': 'ai', 'planning': 'ai', 'author': 'ai', 'review': 'ai', 'planReview': 'ai',
              'repairCycle': 'ai', 'specialist': 'ai', 'check': 'code', 'media': 'media'}
CLIP_KINDS = ('author', 'planReview', 'repairCycle', 'media')   # always about one output
RUN_KINDS = ('director',)                                        # never about one output
CREATIVE_KINDS = ('planning', 'author', 'planReview', 'repairCycle', 'specialist')  # none after minute 25
TASK_STATES = ('blocked', 'ready', 'claimed', 'running', 'cancel-requested', 'cancelled', 'completed',
               'failed', 'abandoned', 'superseded')
UNCLAIMED = ('blocked', 'ready')
LIVE = ('claimed', 'running', 'cancel-requested')
TERMINAL = ('cancelled', 'completed', 'failed', 'abandoned', 'superseded')
UNRESOLVABLE = ('abandoned', 'superseded', 'cancelled')
PRODUCTION_KEYS = {'ai', 'drain', 'tasks', 'governance', 'authorization'}
GOVERNANCE_KEYS = {'host', 'version', 'mode', 'unsupported', 'unproven', 'source'}
AI_KEYS = {'slots', 'reservations', 'charged'}

def is_ai(task: dict) -> bool:
    """AI work holds a host slot and a run reservation."""
    return TASK_KINDS[task['kind']] == 'ai'


def holds_slot(task: dict) -> bool:
    """Live work, and ended work whose resource is unresolved (any terminal state, G9), keep their slot."""
    return task['state'] in LIVE or (task['state'] in TERMINAL and task['unresolved'])


def settled(task: dict) -> bool:
    """Terminal with no unresolved resource."""
    return task['state'] in TERMINAL and not task['unresolved']


def finish(task: dict, state: str, elapsed: float, reason: str | None = None) -> None:
    """Move a task to a terminal state at this elapsed time."""
    task.update(state=state, terminalElapsed=elapsed, reason=clip_text(reason or task['reason'] or '') or None)


def handle_cleans_up(handle: dict | None, flag: str) -> bool:
    """Whether this handle's own host build was observed to end a turn's tools.

    ``flag`` is ``interruptCleansUp`` (an interrupt's terminal confirmation ends them) or
    ``endCleansUp`` (any observed end does). Read per task from the gate verdicts of the
    handle's host, never from whichever director enrolled last; unknown hosts prove nothing.
    """
    if handle is None or handle['type'] != 'host' or handle['host'] not in HOST_RECORDS:
        return False
    return governance(parse_capabilities(HOST_RECORDS[handle['host']]))[flag]


def _id(value: object) -> bool:
    """A task identifier."""
    return type(value) is str and TASK_ID.fullmatch(value) is not None


def _optional(check: object) -> object:
    """None, or a value passing the check."""
    return lambda value: value is None or check(value)


def _reason(value: object) -> bool:
    """A retained reason whose canonical encoding fits 512 bytes."""
    return type(value) is str and encoded_length(value) <= 512


def _count(value: object) -> bool:
    """A bounded nonnegative integer."""
    return type(value) is int and 0 <= value <= MAX_COUNT


def _claim(value: object) -> bool:
    """A durable launch intent: epoch, fencing token, time, the claimer's exact identity and the approval
    identity the work was claimed under (None for run-scoped work)."""
    return type(value) is dict and set(value) == {'epoch', 'token', 'claimedElapsed', 'claimer', 'approval'} \
        and type(value['epoch']) is int and 1 <= value['epoch'] <= MAX_COUNT and type(value['token']) is str \
        and HEX32.fullmatch(value['token']) is not None and finite_seconds(value['claimedElapsed']) \
        and valid_handle(value['claimer']) and (value['approval'] is None or type(value['approval']) is str
                                                  and SHA256.fullmatch(value['approval']) is not None)


def _prerequisites(value: object) -> bool:
    """A bounded list of distinct task ids."""
    return type(value) is list and len(value) <= BOUNDS['prerequisites'] and all(map(_id, value)) \
        and len(set(value)) == len(value)


def valid_owners(value: object) -> bool:
    """Bounded exact process identities retained when watchdog cleanup is incomplete."""
    return type(value) is list and len(value) <= MAX_TASK_OWNERS and all(
        valid_handle(row) and row['type'] == 'process' for row in value) and len(
        {(row['pid'], row['pgid'], row['started']) for row in value}) == len(value)


TASK_FIELDS = {
    'id': _id, 'runId': lambda value: type(value) is str, 'clipId': _optional(lambda value: type(value) is str),
    'kind': lambda value: value in TASK_KINDS, 'route': _optional(lambda value: value in ROUTES),
    'version': lambda value: type(value) is str and VERSION.fullmatch(value) is not None,
    'inputFingerprint': lambda value: type(value) is str and SHA256.fullmatch(value) is not None,
    'deadlineElapsed': finite_seconds, 'prerequisites': _prerequisites, 'parent': _optional(_id),
    'replaces': _optional(_id), 'supersededBy': _optional(_id),
    'depth': lambda value: _count(value) and value <= AI_POLICY['depth'],
    'state': lambda value: value in TASK_STATES, 'reason': _optional(_reason),
    'enqueuedElapsed': finite_seconds, 'epochs': _count, 'claim': _optional(_claim),
    'handle': _optional(valid_handle), 'attempt': _optional(lambda value: type(value) is str
                                                            and HEX32.fullmatch(value) is not None),
    'owners': valid_owners,
    'receipts': valid_receipts, 'failure': _optional(valid_failure), 'unresolved': lambda value: type(value) is bool,
    'charged': lambda value: type(value) is bool, 'cancelRequested': lambda value: type(value) is bool,
    'endConfirmed': lambda value: type(value) is bool,
    'usage': _optional(valid_usage), 'terminalElapsed': _optional(finite_seconds),
    'approvalStale': lambda value: type(value) is bool, 'revoked': lambda value: type(value) is bool,
}


def _fields_ok(row: object) -> bool:
    """A closed mapping whose every field passes its check."""
    optional = {'sectionBinding', 'sectionProgress', 'sectionCarryWithdrawal', 'sectionCarry'}
    if type(row) is not dict or set(row) - optional != set(TASK_FIELDS):
        return False
    if 'sectionBinding' in row:
        from studio.production.section_results import validate_binding
        try:
            validate_binding(row['sectionBinding'])
            from studio.production.section_chunk_progress import valid_progress
            valid_progress(row)
            from studio.production.section_chunk_reuse_history import valid_carry_withdrawal
            valid_carry_withdrawal(row)
            from studio.production.section_chunk_carry import valid_carry
            valid_carry(row)
        except (ValueError, TypeError, KeyError):
            return False
        from studio.production.section_assignment_repair import binding_kind
        if not binding_kind(row['sectionBinding'], row['kind'], row['clipId']):
            return False
    elif {'sectionProgress', 'sectionCarryWithdrawal', 'sectionCarry'} & set(row):
        return False
    return all(check(row[key]) for key, check in TASK_FIELDS.items())


def _scope_problem(row: dict, record: dict) -> str | None:
    """Kind, route and output scope agree, and the output exists."""
    if (row['route'] is not None) != (row['kind'] == 'media'):
        return 'a media task, and only a media task, names its route'
    if row['kind'] in CLIP_KINDS and row['clipId'] is None or row['kind'] in RUN_KINDS and row['clipId'] is not None:
        return 'task scope does not fit its kind'
    if row['clipId'] is not None and row['clipId'] not in record['clips']:
        return 'task names an unknown clip'
    claimed = (row['claim'] or {}).get('approval')
    if claimed is not None and (row['clipId'] is None or claimed not in
                                {item['identity'] for item in record['clips'][row['clipId']]['approvals']}):
        return 'task claim names an approval its clip never recorded'
    ai = TASK_KINDS[row['kind']] == 'ai'
    if (row['charged'] or row['usage'] is not None) and not ai or row['attempt'] is not None and row['kind'] != 'media':
        return 'charges and usage belong to AI tasks, launch attempts to media tasks'
    return None


def _state_problem(row: dict) -> str | None:
    """Claims, handles, outcomes and the unresolved flag agree with the state."""
    claim = row['claim']
    if row['state'] in LIVE and claim is None or row['state'] == 'running' and row['handle'] is None:
        return 'a live task has no claim or a running task no handle'
    if claim is None and (row['handle'] is not None or row['attempt'] is not None) \
            or claim is not None and claim['epoch'] > row['epochs']:
        return 'handle, attempt or epoch without its claim'
    if (row['terminalElapsed'] is not None) != (row['state'] in TERMINAL):
        return 'terminal time does not match the state'
    if (row['failure'] is not None) != (row['state'] == 'failed'):
        return 'a failure category belongs to a failed task only'
    if row['unresolved'] and row['state'] not in TERMINAL:
        return 'only an ended task can hold an unresolved resource'
    if row['state'] in ('superseded', 'completed') and row['revoked'] != (row['state'] == 'superseded'):
        return 'a superseded task is revoked and a completed one is not'
    return None


def _reference_problem(task_id: str, row: dict, tasks: dict) -> str | None:
    """Every referenced task exists in this run and none is the task itself."""
    references = [*row['prerequisites'], row['parent'], row['replaces'], row['supersededBy']]
    if any(item == task_id or item is not None and item not in tasks for item in references):
        return 'task references a missing task or itself'
    return None


def _task_problem(task_id: str, row: object, record: dict) -> str | None:
    """The first violation in one task row, or None."""
    if not _fields_ok(row) or row['id'] != task_id or row['runId'] != record['batchId']:
        return f'task {task_id} fields or identity'
    from studio.production.section_assignment_repair import replacement_problem
    problem = _scope_problem(row, record) or _state_problem(row) \
        or _reference_problem(task_id, row, record['production']['tasks']) \
        or replacement_problem(row, record['production']['tasks'])
    return f'task {task_id}: {problem}' if problem else None


def _ai_problem(ai: object) -> str | None:
    """The declared host slots and run reservations, and the historical charge."""
    if type(ai) is not dict or set(ai) != AI_KEYS or not all(_count(value) for value in ai.values()):
        return 'AI reservation fields'
    if not 1 <= ai['slots'] <= AI_POLICY['slotsCeiling'] or not 1 <= ai['reservations'] <= AI_POLICY['reservationsCeiling']:
        return 'AI slots or reservations exceed the policy ceiling'
    return None


def _governance_problem(value: object) -> str | None:
    """The host governance recorded when the director was enrolled (None before)."""
    if value is None:
        return None
    if type(value) is not dict or set(value) != GOVERNANCE_KEYS or value['mode'] not in MODES \
            or value['host'] is not None and value['host'] not in HOSTS \
            or not all(type(value[key]) is list and set(value[key]) <= set(CAPABILITIES)
                       for key in ('unsupported', 'unproven')) \
            or not (value['version'] is None or type(value['version']) is str and len(value['version']) <= 64) \
            or type(value['source']) is not str or len(value['source']) > 256:
        return 'host governance record'
    return None


def _drain_problem(record: dict) -> str | None:
    """A draining run records when and why shutdown began; an active one has not begun it."""
    drain, status = record['production']['drain'], record['status']
    if drain is not None and (type(drain) is not dict or set(drain) != {'startedElapsed', 'reason'}
                              or not finite_seconds(drain['startedElapsed']) or not _reason(drain['reason'])):
        return 'drain record'
    if (status == 'draining' and drain is None) or (status == 'active' and drain is not None):
        return 'drain record does not match the batch status'
    return None


def production_problem(record: dict) -> str | None:
    """The first violation in the record's production block, or None."""
    block = record['production']
    if type(block) is not dict or set(block) - PRODUCTION_OPTIONAL != PRODUCTION_KEYS:
        return 'production block fields'
    problem = _ai_problem(block['ai']) or _drain_problem(record) or _governance_problem(block['governance']) \
        or authorization_problem(record) or optional_problem(record)
    if problem:
        return problem
    tasks = block['tasks']
    if type(tasks) is not dict or len(tasks) > BOUNDS['tasks']:
        return 'production tasks'
    problem = next(filter(None, (_task_problem(key, row, record) for key, row in tasks.items())), None)
    if problem or len(upstream_first(tasks)) != len(tasks):
        return problem or 'task prerequisites form a cycle'
    charged = sum(1 for row in tasks.values() if row['charged'])
    if charged != block['ai']['charged'] or charged > block['ai']['reservations']:
        return 'AI reservation charges disagree with the charged tasks'
    return None


def upstream_first(tasks: dict) -> list[str]:
    """Task ids with every prerequisite before its dependents; tasks on or after a cycle are left out."""
    waiting = {task_id: len(task['prerequisites']) for task_id, task in tasks.items()}
    order = [task_id for task_id, count in waiting.items() if count == 0]
    for task_id in order:
        for other in (key for key, row in tasks.items() if task_id in row['prerequisites']):
            waiting[other] -= 1
            order.extend([other] if waiting[other] == 0 else [])
    return order


def holds_unresolved_work(raw: object) -> bool:
    """Conservative reading of any record's production block, this engine's or another version's.

    A record without the block (engines before version 4) holds no task work. A block
    whose tasks are not all recognisably ended with no unresolved resource, or that
    cannot be read, holds unresolved work: it is never released by a deadline alone.
    """
    if type(raw) is not dict or 'production' not in raw:
        return False
    block = raw['production']
    tasks = block.get('tasks') if type(block) is dict else None
    if type(tasks) is not dict:
        return True
    return not all(type(row) is dict and row.get('state') in TERMINAL and row.get('unresolved') is False
                   for row in tasks.values())
