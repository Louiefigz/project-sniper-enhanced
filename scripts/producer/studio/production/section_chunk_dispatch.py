"""Expose sealed Long chunks through one existing independent reviewer per assignment.

This adapter publishes immutable inputs only. Real reviewer executions retain
their ordinary claim, slot, deadline and cumulative charge until final completion.
"""
from __future__ import annotations

from pathlib import Path

from studio.production.section_chunk_plan import freeze_chunk_plan, ready_chunk_scopes, scope_manifest
from studio.production.section_plan import unique_pins
from studio.production.section_results import validate_binding


def chunk_spec(request: dict, row: dict, record: dict) -> object:
    """Freeze one stable task before future sibling chunks produce their media."""
    from studio.native_long_chunks import require_chunk_request
    from studio.production.sections import early_result, integrated_author, review_task
    require_chunk_request(request)
    early_pin, early = early_result(request, row, record)
    author = integrated_author(request, row, record)
    file = Path(request['output']) / f"{row['encodedTaskId']}-chunks.json"
    plan = request.get('sectionChunkPlans', {}).get(row['encodedTaskId']) or freeze_chunk_plan(request, row, file)
    binding = {**row['authorBinding'], 'role': 'encoded-review', 'authorTaskId': row['authorTaskId'],
               'mediaManifest': None, 'chunkPlan': plan,
               'inputs': unique_pins([*row['authorBinding']['inputs'], author, early_pin, plan])}
    validate_binding(binding)
    from studio.production.section_chunk_recovery import exact_chunk_request
    exact_chunk_request(binding, request)
    return review_task(request['sectionProduction'], {**row, 'earlyTaskId': early.task_id}, binding)


def ready_inputs(spec: object, request: dict | None = None) -> list[dict]:
    """Publish exact current sealed scope media without waiting for unrelated chunks."""
    return chunk_input_state(spec, request)[0]


def chunk_input_state(spec: object, request: dict | None = None, carry: dict | None = None) -> tuple[list[dict], list[dict]]:
    """Distinguish unfinished media from sealed scopes awaiting their existing owned packaging phase."""
    from studio.production.section_chunk_plan import read_chunk_plan
    from studio.production.section_chunk_presentation import presentation_pin
    current = request or read_chunk_plan(spec.section_binding)[1]
    scopes = ready_chunk_scopes(spec.section_binding, request)
    ready, pending = [], []
    for scope in scopes:
        if scope['id'] in (carry or {}):
            from studio.production.section_chunk_carry import carry_input
            ready.append(carry_input(spec, scope, carry[scope['id']]))
            continue
        if current.get('sectionChunks') and presentation_pin(current, scope['id']) is None:
            pending.append({'scopeId': scope['id'], 'frameRange': scope['frameRange'],
                            'sectionId': spec.section_binding['sectionId'], 'status': 'requires-owned-presentation'})
            continue
        ready.append(scope_input(spec, scope, request))
    return ready, pending


def scope_input(spec: object, scope: dict, request: dict | None = None) -> dict:
    """Keep host dispatch tied to the same exact scope the progress callback will verify."""
    binding = spec.section_binding
    directory = Path(request['output']) if request else Path(binding['chunkPlan']['path']).parent
    manifest = scope_manifest(binding, scope['id'], directory / f"{spec.task_id}-{scope['id']}-media.json", request)
    from studio.production.section_chunk_presentation import review_observations
    return {'taskId': spec.task_id, 'scopeId': scope['id'], 'kind': scope['kind'],
            'frameRange': scope['frameRange'], 'mediaManifest': manifest,
            'observations': review_observations({**binding, 'frameRange': scope['frameRange'], 'mediaManifest': manifest})}


def chunk_snapshot(task: dict, request: dict | None = None) -> dict:
    """Retain all completed local media references in the ordinary assembly dependency snapshot."""
    from studio.production.section_chunk_results import completed_scope_snapshot
    scopes = completed_scope_snapshot(task)
    if request is not None:
        from studio.production.section_chunk_recovery import compare_current_scopes
        compare_current_scopes(request, task, scopes)
    return {'chunkPlan': task['sectionBinding']['chunkPlan'],
            'chunkReviews': [{'scopeId': scope['scopeId'], 'mediaManifest': scope['mediaManifest'],
                              'receipt': scope['receipt'],
                              **({'retainedJudgment': scope['retainedJudgment']}
                                 if 'retainedJudgment' in scope else {})} for scope in scopes]}
