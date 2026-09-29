"""Nonterminal review callbacks under the existing production lock, claim and clock.

A waiting reviewer still holds its AI slot. The host coordinator must preserve
capacity for unfinished authors; this API never releases an attached claim.
"""
from __future__ import annotations

from studio.native_budget_binding import advance_clock
from studio.native_budget_policy import phase_refusal
from studio.production.claims import ClaimRef, Outcome, check_claim
from studio.production.dependencies import stale_inputs
from studio.production.section_chunk_plan import MAX_SCOPES
from studio.production.section_chunk_results import read_progress
from studio.production.section_results import (
    IDENTIFIER, author_for, claim_directory, current, matches, require, task_of, validate_pin,
)
from studio.production.tasks import TaskConflict, TaskRefused


def valid_progress(task: dict) -> bool:
    """Validate bounded stored references without filesystem access during authority reads."""
    if 'sectionProgress' not in task:
        return True
    value = task['sectionProgress']
    binding = task.get('sectionBinding', {})
    require(binding.get('chunkPlan') is not None and type(value) is dict
            and 1 <= len(value) <= MAX_SCOPES and task.get('claim') is not None,
            'invalid section progress inventory')
    directory = claim_directory(task)
    for scope_id, pin in value.items():
        require(matches(scope_id, IDENTIFIER), 'invalid progress scope id')
        validate_pin(pin)
        require(pin['path'] == str(directory / 'chunks' / f'{scope_id}.json'), 'progress claim path differs')
    return True


def require_live_review(record: dict, task: dict) -> float:
    """Recheck the original output and task grant after every potentially expensive proof."""
    elapsed = advance_clock(record)
    refusal = phase_refusal(record, record['clips'][task['clipId']], elapsed)
    if refusal or elapsed >= task['deadlineElapsed']:
        raise TaskRefused(refusal or 'Section review original task deadline expired')
    return elapsed


def record_progress(record: dict, ref: ClaimRef, receipt: dict) -> Outcome:
    """Commit one current scope once, keeping this reviewer running and its existing charge."""
    task = task_of(record, ref.task_id)
    check_claim(task, ref)
    current(task, ('running',))
    require(task['sectionBinding'].get('chunkPlan') is not None, 'task is not an incremental encoded reviewer')
    require(stale_inputs(record).get(task['id']) is None, 'section dependency approval is no longer current')
    author_for(record, task)
    value = read_progress(task, receipt)
    scope_id = value['scopeId']
    previous = task.get('sectionProgress', {}).get(scope_id)
    if previous is not None and previous != receipt:
        raise TaskConflict('Chunk review scope already recorded different evidence')
    elapsed = require_live_review(record, task)
    if previous is not None:
        return Outcome(False, {}, {'taskId': task['id'], 'scopeId': scope_id, 'replayed': True})
    task.setdefault('sectionProgress', {})[scope_id] = dict(receipt)
    return Outcome(True, {'event': 'section-review-progress', 'taskId': task['id'], 'scopeId': scope_id,
                          'checkedElapsed': elapsed}, {'taskId': task['id'], 'scopeId': scope_id,
                          'state': task['state'], 'checkedElapsed': elapsed})
