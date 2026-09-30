"""Task definitions, dependency checks and dependency-driven transitions, on one locked record.

Everything here is a pure change to the caller's in-memory record; the caller
(``production.api``) holds the batch lock and commits, or discards the record when
a refusal is raised. Enqueue is one bounded DAG check, not a workflow language:

- prerequisites must already exist in this run or arrive in the same submission;
  a reference to another run (``<run>/<task>``), a missing id and a cycle are refused;
- a failed, cancelled or superseded (``revoked``) prerequisite is refused: replacement work names
  a new input version and dependency set (``replaces``);
- re-submitting an identical definition is a no-op (a lost acknowledgement), a
  different definition under an existing id is a conflict.

Readiness follows dependencies: a task is ready only when every prerequisite is
``completed``. A failed or cancelled prerequisite makes its dependents failed with a
retained reason; superseding a task supersedes everything computed from it, because
a superseded result never satisfies a current dependency.
"""
from __future__ import annotations

import math
from copy import deepcopy
from dataclasses import dataclass

from studio.native_budget_batches import BudgetRefused
from studio.native_budget_policy import clip_record, phase_refusal
from studio.native_budget_store import MAX_RECORD_BYTES, canonical
from studio.native_budget_schema import BOUNDS, ROUTES, SHA256
from studio.production.dependencies import DEAD_PREREQUISITES, refresh, supersede
from studio.production.formats import clip_deadlines, output_format
from studio.production.task_schema import (
    AI_POLICY, CLIP_KINDS, RUN_KINDS, TASK_ID, TASK_KINDS, TERMINAL, VERSION, holds_slot, is_ai,
)
from studio.production.settlement import settlement_reserve



class TaskRefused(BudgetRefused):
    """The task rules refuse this transition; nothing was started."""

    category = 'task-refused'


class StaleClaim(TaskRefused):
    """A callback carries an old claim epoch or the wrong token: it is fenced out."""


class TaskConflict(TaskRefused):
    """A repeated callback or definition disagrees with what was already recorded."""


@dataclass(frozen=True)
class TaskSpec:
    """One task a planner declares; ids are typed and unique within the run."""

    task_id: str
    run_id: str
    kind: str
    version: str
    input_fingerprint: str
    deadline_elapsed: float
    clip_id: str | None = None
    route: str | None = None
    prerequisites: tuple[str, ...] = ()
    parent: str | None = None
    replaces: str | None = None
    section_binding: dict | None = None


def tasks_of(record: dict) -> dict:
    """The run's task table."""
    return record['production']['tasks']


def task_of(record: dict, task_id: str) -> dict:
    """One task of this run; an unknown id is refused, never created."""
    task = tasks_of(record).get(task_id)
    if task is None:
        raise TaskRefused(f'Task {task_id} is not part of batch {record["batchId"]}')
    return task


def active_ai(record: dict) -> int:
    """AI slots in use, the director included."""
    return sum(1 for task in tasks_of(record).values() if is_ai(task) and holds_slot(task))


def _definition(row: dict) -> tuple:
    """The immutable declaration of a task, for replay comparison."""
    return tuple(row[key] for key in ('runId', 'kind', 'clipId', 'route', 'version', 'inputFingerprint',
                                      'deadlineElapsed', 'prerequisites', 'parent', 'replaces')) + (row.get('sectionBinding'),)


def _prerequisite_ids(record: dict, spec: TaskSpec) -> list[str]:
    """Normalize ``<run>/<task>`` references; another run's task is refused."""
    ids = []
    for item in spec.prerequisites:
        run, _, task_id = item.rpartition('/')
        if run and run != record['batchId']:
            raise TaskRefused(f'Task {spec.task_id} names prerequisite {item} of another run; '
                              'a task depends only on tasks of its own run')
        if type(task_id) is not str or TASK_ID.fullmatch(task_id) is None:
            raise ValueError(f'Prerequisite {item!r} is not a task id')
        ids.append(task_id)
    if len(set(ids)) != len(ids) or len(ids) > BOUNDS['prerequisites'] or spec.task_id in ids:
        raise TaskRefused(f'Task {spec.task_id} needs at most {BOUNDS["prerequisites"]} distinct prerequisites, '
                          'none of them itself')
    return ids


def require_identity(task_id: object, version: object, fingerprint: object) -> None:
    """A typed task id, version and SHA-256 input fingerprint."""
    if type(task_id) is not str or TASK_ID.fullmatch(task_id) is None \
            or type(version) is not str or VERSION.fullmatch(version) is None \
            or type(fingerprint) is not str or SHA256.fullmatch(fingerprint) is None:
        raise ValueError('A task needs a typed id, version and SHA-256 input fingerprint')


def _check_spec(record: dict, spec: TaskSpec, elapsed: float) -> None:
    """Identity, kind, scope and deadline of one declaration."""
    if spec.run_id != record['batchId']:
        raise TaskRefused(f'Task {spec.task_id} belongs to run {spec.run_id}, not {record["batchId"]}')
    require_identity(spec.task_id, spec.version, spec.input_fingerprint)
    if spec.section_binding is not None:
        from studio.production.section_assignment_repair import validate_section_spec
        validate_section_spec(record, spec)
    if spec.kind not in TASK_KINDS or spec.kind in RUN_KINDS:
        raise ValueError(f'Task kind {spec.kind!r} cannot be enqueued (the running director is enrolled)')
    if (spec.route is not None) != (spec.kind == 'media') or spec.route is not None and spec.route not in ROUTES:
        raise ValueError('A media task, and only a media task, names one supported route')
    if spec.kind in CLIP_KINDS and spec.clip_id is None:
        raise ValueError(f'A {spec.kind} task names its clip')
    clip = clip_record(record, spec.clip_id) if spec.clip_id else None
    refusal = phase_refusal(record, clip, elapsed)
    if refusal is None and clip is not None and not clip['approvals'] and output_format(clip) == 'short':
        refusal = (f'Clip {spec.clip_id} has no approved title and script; its work starts from that approval '
                   '(record it first)')
    deadline = spec.deadline_elapsed  # within its output's own deadline (run work: the latest output's)
    if refusal is None and (type(deadline) not in (int, float) or not math.isfinite(deadline)
                            or not elapsed < deadline <= clip_deadlines(record, clip)['deliverySeconds']):
        refusal = f'Task {spec.task_id} deadline must lie after now and no later than the delivery deadline'
    if refusal:
        raise TaskRefused(refusal)


def _check_references(record: dict, spec: TaskSpec, pending: dict) -> list[str]:
    """Prerequisites and parent exist, are alive, and a parent bounds its child's deadline."""
    tasks, ids = tasks_of(record), _prerequisite_ids(record, spec)
    for task_id in ids:
        if task_id not in tasks and task_id not in pending:
            raise TaskRefused(f'Task {spec.task_id} names missing prerequisite {task_id}')
        if task_id in tasks and (tasks[task_id]['state'] in DEAD_PREREQUISITES or tasks[task_id]['revoked']):
            state = 'superseded' if tasks[task_id]['revoked'] else tasks[task_id]['state']
            raise TaskRefused(f'Prerequisite {task_id} is {state}; replacement work names a new input version and '
                              'dependency set')
    if spec.parent is not None:
        _check_parent(record, spec, pending)
    elif TASK_KINDS[spec.kind] == 'ai':
        raise TaskRefused(f'AI task {spec.task_id} names no parent: every AI task the run admits descends from '
                          'the enrolled director')
    return ids


def _check_parent(record: dict, spec: TaskSpec, pending: dict) -> None:
    """The parent exists in this run, has not ended, and is AI work when the child is.

    A child's deadline is bounded by its parent's; the enrolled director (the run's root) bounds its
    children by the run's latest output deadline, so a Long joining later can still descend from it.
    """
    tasks = tasks_of(record)
    parent = tasks.get(spec.parent) or pending.get(spec.parent)
    if parent is None or spec.parent == spec.task_id:
        raise TaskRefused(f'Task {spec.task_id} names missing parent {spec.parent}')
    kind = parent.kind if isinstance(parent, TaskSpec) else parent['kind']
    from studio.production.queue_clock import task_deadline
    deadline = parent.deadline_elapsed if isinstance(parent, TaskSpec) else task_deadline(record, parent)
    ended = not isinstance(parent, TaskSpec) and (parent['state'] in TERMINAL or parent['state'] == 'cancel-requested')
    if ended:
        raise TaskRefused(f'Parent {spec.parent} has ended; an ended request cannot spawn successors')
    if TASK_KINDS[spec.kind] == 'ai' and TASK_KINDS[kind] != 'ai':
        raise TaskRefused(f'AI task {spec.task_id} must descend from AI work, not a {kind} task')
    if kind == 'director':
        deadline = clip_deadlines(record, None)['deliverySeconds']
    if spec.deadline_elapsed > deadline:
        raise TaskRefused(f'Task {spec.task_id} deadline is later than its parent {spec.parent}\'s')


def _check_replacement(record: dict, spec: TaskSpec) -> None:
    """A replacement names an existing, unreplaced task of the same output with a new version."""
    target = tasks_of(record).get(spec.replaces)
    if target is None or target['supersededBy'] is not None:
        raise TaskRefused(f'Task {spec.task_id} replaces {spec.replaces}, which is missing or already replaced')
    from studio.production.section_assignment_repair import allows_kind_replacement
    same_kind = target['kind'] == spec.kind or allows_kind_replacement(record, spec)
    if not same_kind or target['clipId'] != spec.clip_id or target['version'] == spec.version:
        raise TaskRefused(f'Replacement {spec.task_id} must be the same kind of work for the same output with a '
                          f'new input version (not {target["version"]})')


def _depth(record: dict, pending: dict, task_id: str) -> int:
    """Nesting depth along the parent chain; a parent cycle or too deep a chain is refused."""
    tasks, seen, depth, current = tasks_of(record), {task_id}, 0, task_id
    while current in pending and pending[current].parent is not None:
        current = pending[current].parent
        if current in seen:
            raise TaskRefused(f'Task {task_id} parent chain is cyclic')
        seen.add(current)
        depth += 1
    if current not in pending and current not in tasks:
        raise TaskRefused(f'Task {task_id} descends from missing parent {current}')
    total = depth + (tasks[current]['depth'] if current not in pending else 0)
    if total > AI_POLICY['depth']:
        raise TaskRefused(f'Task {task_id} nests deeper than {AI_POLICY["depth"]} levels')
    return total


def _require_acyclic(graph: dict) -> None:
    """Refuse a prerequisite cycle within one submission (existing tasks cannot depend on new ones)."""
    remaining = {node: {item for item in edges if item in graph} for node, edges in graph.items()}
    while remaining:
        free = {node for node, edges in remaining.items() if not edges}
        if not free:
            raise TaskRefused(f'Prerequisites form a cycle through {sorted(remaining)[0]}')
        remaining = {node: edges - free for node, edges in remaining.items() if node not in free}


def new_row(record: dict, spec: TaskSpec, prerequisites: list[str], context: tuple[int, float]) -> dict:
    """A blocked task row; ``refresh`` decides readiness. context = (depth, enqueued elapsed)."""
    depth, elapsed = context
    row = {'id': spec.task_id, 'runId': record['batchId'], 'clipId': spec.clip_id, 'kind': spec.kind,
            'route': spec.route, 'version': spec.version, 'inputFingerprint': spec.input_fingerprint,
            'deadlineElapsed': float(spec.deadline_elapsed), 'prerequisites': prerequisites, 'parent': spec.parent,
            'replaces': spec.replaces, 'supersededBy': None, 'depth': depth, 'state': 'blocked', 'reason': None,
            'enqueuedElapsed': elapsed, 'epochs': 0, 'claim': None, 'handle': None, 'attempt': None, 'owners': [],
            'receipts': [], 'failure': None, 'unresolved': False, 'charged': False, 'cancelRequested': False,
            'endConfirmed': False, 'usage': None, 'terminalElapsed': None, 'approvalStale': False, 'revoked': False}
    if spec.kind != 'director':   # C6: where its credit starts (the director keeps the run's deadline)
        from studio.production.queue_clock import record_task_origin
        record_task_origin(record, spec.task_id, spec.clip_id)
    if spec.section_binding is not None:
        row['sectionBinding'] = deepcopy(spec.section_binding)
    return row


def enqueue(record: dict, specs: tuple[TaskSpec, ...], elapsed: float) -> dict:
    """Add a submission atomically; identical replays are no-ops. Raises on any refusal."""
    tasks = tasks_of(record)
    if not specs or len({spec.task_id for spec in specs}) != len(specs):
        raise ValueError('A submission names one or more distinct task ids')
    fresh = {spec.task_id: spec for spec in specs if spec.task_id not in tasks}
    replayed = [spec for spec in specs if spec.task_id in tasks]
    for spec in replayed:
        if _declared(record, spec) != _definition(tasks[spec.task_id]):
            raise TaskConflict(f'Task {spec.task_id} already exists with a different definition')
    if len(tasks) + len(fresh) > BOUNDS['tasks']:
        raise TaskRefused(f'The run already holds {len(tasks)} of {BOUNDS["tasks"]} tasks')
    rows = {task_id: _checked_row(record, spec, fresh, elapsed) for task_id, spec in fresh.items()}
    replaced = {spec.replaces for spec in fresh.values() if spec.replaces}
    if any(replaced & set(row['prerequisites']) for row in rows.values()):
        raise TaskRefused('A submission cannot depend on a task it replaces; name the replacement instead')
    _require_acyclic({task_id: row['prerequisites'] for task_id, row in rows.items()})
    tasks.update(rows)
    for spec in fresh.values():
        if spec.replaces is not None:
            supersede(record, spec.replaces, (f'replaced by {spec.task_id}', spec.task_id), elapsed)
    refresh(record, elapsed)
    if fresh:
        require_headroom(record)
    return {'enqueued': sorted(fresh), 'replayed': sorted(spec.task_id for spec in replayed),
            'states': {spec.task_id: tasks[spec.task_id]['state'] for spec in specs}}


def _declared(record: dict, spec: TaskSpec) -> tuple:
    """A submitted declaration in stored form, for comparison with an existing row."""
    if spec.run_id != record['batchId']:
        raise TaskRefused(f'Task {spec.task_id} belongs to run {spec.run_id}, not {record["batchId"]}')
    row = new_row(record, spec, _prerequisite_ids(record, spec), (0, 0.0))
    return _definition(row)


def _checked_row(record: dict, spec: TaskSpec, fresh: dict, elapsed: float) -> dict:
    """Validate one new declaration against the run and the submission, then build its row."""
    _check_spec(record, spec, elapsed)
    prerequisites = _check_references(record, spec, fresh)
    if spec.replaces is not None:
        _check_replacement(record, spec)
    return new_row(record, spec, prerequisites, (_depth(record, fresh, spec.task_id), elapsed))


def require_headroom(record: dict) -> None:
    """New tasks must leave room for every open task to record its widest outcome."""
    if len(canonical(record)) + settlement_reserve(record) > MAX_RECORD_BYTES:
        raise TaskRefused('The batch record has no room left to settle more tasks; no new tasks are admitted')
