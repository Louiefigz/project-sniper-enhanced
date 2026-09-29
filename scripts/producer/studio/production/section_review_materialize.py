"""Materialize current logical review tasks and optional retained chunk judgments.

The existing production transaction owns all state. Immutable sidecars may be
prepared first, but enqueue and append-only carry commit recheck the original
clock after expensive evidence reads. Neither operation settles a reviewer.
"""
from __future__ import annotations

from studio.native_budget_binding import advance_clock
from studio.production.claims import Outcome
from studio.production.section_chunk_carry import planned_carry
from studio.production.section_chunk_dispatch import chunk_input_state
from studio.production.section_chunk_progress import require_live_review
from studio.production.section_results import current, require
from studio.production.section_scope import selected_assignments
from studio.production.tasks import enqueue


def commit_carry(record: dict, inventories: dict) -> list[str]:
    """Append references once; old claim, counters, slot and deadline stay untouched."""
    changed = []
    for task_id, inventory in inventories.items():
        task = record['production']['tasks'][task_id]
        existing = task.get('sectionCarry', {})
        require(all(key not in existing or existing[key] == pin for key, pin in inventory.items()),
                'recorded chunk carry already differs')
        additions = {key: pin for key, pin in inventory.items() if key not in existing}
        if not additions:
            continue
        current(task, ('blocked', 'ready', 'claimed', 'running'))
        require_live_review(record, task)
        task.setdefault('sectionCarry', {}).update(additions)
        changed.append(task_id)
    return changed


def collect_reviews(record: dict, request: dict, context: dict, stage: str) -> tuple:
    """Discover ready scopes independently; withheld media/presentations defer only their own work."""
    from studio.production.sections import _review_spec, review_ready
    from studio.production.section_review_reuse import retained_review
    specs, pending, ready, presentation, carries = [], [], [], [], {}
    chunks = stage == 'encoded' and bool(request.get('sectionChunks'))
    for row in selected_assignments(request, context):
        if stage == 'encoded' and not chunks and not review_ready(request, row):
            pending.append(row['sectionId'])
            continue
        if retained_review(request, row, (record, f'{stage}-review')) is not None:
            continue
        spec = _review_spec(request, row, (record, stage))
        retained = planned_carry(record, request, row, spec) if chunks else {}
        inputs, awaiting = chunk_input_state(spec, request, retained) if chunks else ([], [])
        presentation.extend(awaiting)
        ready.extend(inputs)
        if chunks and not inputs:
            pending.append(row['sectionId'])
            continue
        specs.append(spec)
        if retained:
            carries[spec.task_id] = retained
    return specs, pending, ready, presentation, carries


def materialize_locked(record: dict, request: dict, context: dict, stage: str) -> Outcome:
    """Commit existing tasks and new carry references under the caller's production lock."""
    from studio.production.section_plan import require_context
    require_context(record, context)
    specs, pending, ready, presentation, carries = collect_reviews(record, request, context, stage)
    elapsed = advance_clock(record)
    result = enqueue(record, tuple(specs), elapsed) if specs else {'enqueued': [], 'replayed': [], 'states': {}}
    changed = commit_carry(record, carries)
    return Outcome(bool(result['enqueued'] or changed),
                   {'event': 'section-reviews-enqueued', 'taskIds': result['enqueued'],
                    'carryTaskIds': changed, 'stage': stage},
                   {**result, 'pendingSections': pending, 'readyChunks': ready,
                    'pendingPresentation': presentation, 'carryUpdated': changed})
