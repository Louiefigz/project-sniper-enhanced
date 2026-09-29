"""Existing claim grants and headroom checks, with optional already-validated cold proof."""
from __future__ import annotations

from studio.native_budget_launch import launch_family
from studio.native_budget_policy import admit_dispatch, clip_record, phase_refusal
from studio.native_budget_schema import DISPATCH_KINDS
from studio.production.formats import clip_deadlines, preparation_passed
from studio.production.task_schema import CREATIVE_KINDS, holds_slot, is_ai
from studio.production.tasks import active_ai, tasks_of

LIVE_PARENT = ('claimed', 'running')


def claim_refusal(record: dict, task: dict, elapsed: float, proof_current: bool = False) -> str | None:
    """Why this ready task cannot be claimed now, or None."""
    clip = clip_record(record, task['clipId']) if task['clipId'] else None
    refusal = phase_refusal(record, clip, elapsed)
    if refusal:
        return refusal
    if is_ai(task):
        return _ai_refusal(record, task, elapsed, proof_current)
    if task['kind'] == 'media':
        return _media_refusal(record, task)
    return None


def _ai_refusal(record: dict, task: dict, elapsed: float, proof_current: bool) -> str | None:
    """Enrollment, phase, host slots, run reservations and the per-clip dispatch counters."""
    parent = tasks_of(record).get(task['parent'])
    if parent is None or parent['state'] not in LIVE_PARENT:
        state = f'{parent["id"]} is {parent["state"]}' if parent else 'none'
        return f'AI task {task["id"]} has no live parent ({state}); the authority admits no AI work outside the director\'s tree'
    clip = record['clips'][task['clipId']] if task['clipId'] else None
    if task['kind'] in CREATIVE_KINDS and elapsed >= clip_deadlines(record, clip)['preparationSeconds']:
        return f'{preparation_passed(clip)}: no further authoring, planning, plan review or repair is admitted'
    ai = record['production']['ai']
    if active_ai(record) >= ai['slots']:
        return (f'All {ai["slots"]} AI slots are held (the director and unresolved work included); a slot frees '
                'only on confirmed termination')
    from studio.production.section_chunk_liveness import reviewer_liveness_refusal
    if not proof_current and (refusal := reviewer_liveness_refusal(record, task)):
        return refusal
    if task['charged']:
        return None
    if ai['charged'] >= ai['reservations']:
        return f'The run has charged all {ai["reservations"]} of its AI reservations'
    if task['clipId'] and task['kind'] in DISPATCH_KINDS:
        decision = admit_dispatch(record, task['clipId'], task['kind'], elapsed)
        return None if decision.allowed else decision.reason
    return None


def _media_refusal(record: dict, task: dict) -> str | None:
    """One live media task per clip and launch family, as the exporter runs one launch per family."""
    family = launch_family(task['route'])
    busy = [other['id'] for other in tasks_of(record).values() if other is not task and other['kind'] == 'media'
            and other['clipId'] == task['clipId'] and holds_slot(other) and launch_family(other['route']) == family]
    running = [row['id'] for row in clip_record(record, task['clipId'])['attempts']
               if row['status'] == 'running' and launch_family(row['route']) == family]
    if busy or running:
        return f'Clip {task["clipId"]} already has live {family} work ({(busy + running)[0]}); it waits for its end'
    return None

