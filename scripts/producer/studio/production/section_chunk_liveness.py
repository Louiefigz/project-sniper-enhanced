"""Reserve authoring progress when an incremental reviewer would occupy the final AI slot.

This is a claim admission check inside the existing transaction, not a scheduler.
Attached reviewers keep their original claim, deadline and charge. Only the
current frozen Long assignment inventory contributes prerequisite work; unrelated
or obsolete author tasks never create a phantom reservation.
"""
from __future__ import annotations

from pathlib import Path

from studio.production.section_chunk_plan import read_chunk_plan
from studio.production.section_plan import read_plan
from studio.production.section_results import rehash, require
from studio.production.task_schema import holds_slot
from studio.production.tasks import active_ai


def current_assignments(record: dict, task: dict) -> tuple[dict | None, list[dict]]:
    """Read the current family's frozen assignment plan, retaining the original request fallback."""
    _plan, request = read_chunk_plan(task['sectionBinding'])
    context = request['sectionProduction']
    require(context['batchId'] == record['batchId'] and context['clipId'] == task['clipId'],
            'chunk reviewer and assignment authority differ')
    families = record['clips'][task['clipId']].get('sectionFamilies', [])
    if families:
        pin = families[-1]['plan']
        rehash(pin)
        context = read_plan(Path(pin['path']))
        require(context['plan'] == pin and context['batchId'] == record['batchId']
                and context['clipId'] == task['clipId'], 'current chunk author plan differs from its family')
    current = request if request['sectionProduction'] == context else None
    return current, context['assignments']


def _needs_slot(task: dict | None) -> bool:
    """Missing or unfinished nonexecuting prerequisite work still needs room to progress."""
    return task is None or task['state'] != 'completed' and not holds_slot(task)


def _early_task(record: dict, row: dict, request: dict | None) -> dict | None:
    """Use actual current or retained early-proof resolution, never the plan's unbound task-name prefix."""
    tasks = record['production']['tasks']
    if request is not None:
        from studio.production.sections import early_result, review_binding, review_task
        from studio.production.section_review_reuse import retained_early
        retained = retained_early(request, row, record)
        if retained is not None:
            return tasks[retained[1].task_id]
        binding, _expected = review_binding(request, row, record)
        actual = tasks.get(review_task(request['sectionProduction'], row, binding).task_id)
        if actual is not None and actual['state'] == 'completed':
            early_result(request, row, record)
        return actual
    matches = [task for task in tasks.values() if task.get('sectionBinding', {}).get('role') == 'early-review'
               and task['sectionBinding'].get('authorTaskId') == row['authorTaskId']
               and all(task['sectionBinding'].get(key) == row[key]
                       for key in ('sectionId', 'generation', 'inputIdentity', 'frameRange'))
               and holds_slot(task)]
    return next(iter(matches), None)


def _pending(record: dict, row: dict, request: dict | None) -> bool:
    """A running prerequisite can finish and free its own slot; dormant work needs one reserved."""
    author = record['production']['tasks'].get(row['authorTaskId'])
    if _needs_slot(author):
        return True
    if author['state'] != 'completed':
        return False
    return _needs_slot(_early_task(record, row, request))


def reviewer_liveness_refusal(record: dict, task: dict) -> str | None:
    """Refuse only a last-slot chunk claim that could prevent current prerequisite AI work."""
    if not task.get('sectionBinding', {}).get('chunkPlan'):
        return None
    if active_ai(record) + 1 < record['production']['ai']['slots']:
        return None
    request, assignments = current_assignments(record, task)
    for row in assignments:
        if _pending(record, row, request):
            return (f'Chunk reviewer {task["id"]} must leave an AI slot for current '
                    f'section {row["sectionId"]} authoring and early review; complete that prerequisite work first')
    return None
