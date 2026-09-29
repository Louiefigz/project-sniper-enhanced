"""Compose exact current neighboring judgments without transferring stale join approval."""
from __future__ import annotations

from studio.production.section_judgments import read_interior_result
from studio.production.section_results import read_completed_result, require, task_of
from studio.production.section_review_reuse import compatibility, media_signature
from studio.production.section_review_scope import descriptor, early_join, encoded_join, read_scope


def review_scopes(task: dict) -> tuple[dict, list[dict], dict]:
    """Resolve the explicit reviewed request, scopes and immutable approval input."""
    binding = task['sectionBinding']
    if not binding.get('chunkPlan'):
        original, scopes = read_scope(binding)
        return original, scopes, {'reviewScope': binding['reviewScope']}
    from studio.production.section_chunk_plan import read_chunk_plan
    from studio.production.section_chunk_join_inputs import chunk_global_join_inputs
    from studio.production.section_media import read_index
    from studio.production.section_results import read_document
    document = read_document(task, task['receipts'][0])
    pin = document['review']['globalJoins']
    if pin is None:
        _plan, original = read_chunk_plan(binding)
        return original, [], {'chunkPlan': binding['chunkPlan']}
    value = read_index(pin)
    original, scopes = chunk_global_join_inputs(binding, value['request'], retained=task['state'] == 'completed')
    return original, scopes, {'globalJoins': pin}


def task_for_receipt(record: dict, receipt: dict) -> dict:
    """Resolve only a unique registered current result, never an unregistered review document."""
    tasks = [task for task in record['production']['tasks'].values() if task.get('receipts') == [receipt]]
    require(len(tasks) == 1, 'join review receipt has no unique registered task')
    return tasks[0]


def check_authors(record: dict, task: dict, sections: list[dict]) -> None:
    """Independence covers both current authors involved in this particular join."""
    for section in sections:
        author = task_of(record, section['authorTaskId'])
        require(all(author['sectionBinding'][key] == section[key]
                for key in ('sectionId', 'generation', 'inputIdentity', 'frameRange')),
                'join descriptor differs from current author')
        require((task['handle']['host'], task['handle']['thread'])
                != (author['handle']['host'], author['handle']['thread']), 'join reviewer is an involved author')
        read_completed_result(record, author['id'], author['sectionBinding'])


def matching_join(request: dict, task: dict, state: tuple) -> dict | None:
    """Match exact adjacent generations and recompute any retained current media/dependency relation."""
    original, scopes, evidence = review_scopes(task)
    pair, stage = state
    left, right = pair
    wanted = descriptor(f"{stage}-join:{left['sectionId']}:{right['sectionId']}", [left, right], [])
    found = next((scope for scope in scopes if scope['id'] == wanted['id']
                  and scope['sections'] == wanted['sections']), None)
    if found is None:
        return None
    exact = original['project'] == request['project'] and original['revision']['identity'] == request['revision']['identity']
    if original['output'] != request['output'] and not exact:
        compatibility(original, request, [left['frameRange'][0], right['frameRange'][1]])
    if stage == 'encoded':
        require(media_signature(found['observations']) == media_signature(encoded_join(request, left, right)),
                'current neighboring picture or PCM differs from reviewed join')
    elif task['sectionBinding'].get('chunkPlan'):
        require(media_signature(found['observations']) == media_signature(early_join(request, left, right)),
                'current neighboring preview differs from reviewed join')
    return {'join': wanted['id'], 'sections': wanted['sections'], 'receipt': task['receipts'][0],
            **evidence}


def join_snapshot(request: dict, record: dict, assignments: list[dict]) -> list[dict]:
    """Require both early and encoded independent current evidence for every adjacent boundary."""
    rows = request['sectionProduction']['assignments']
    result = []
    for pair in zip(rows, rows[1:]):
        result.extend(pair_snapshot(request, record, (pair, assignments)))
    return result


def pair_snapshot(request: dict, record: dict, state: tuple) -> list[dict]:
    """Inspect only explicitly scoped join judgments, not the obsolete whole-section pass."""
    pair, assignments = state
    result = []
    for stage in ('early', 'encoded'):
        candidates = [task_for_receipt(record, row[key]) for row in assignments
                      for key in ('earlyReview', 'encodedReview')]
        matches = [value for task in candidates if (value := matching_join(request, task, (pair, stage))) is not None]
        require(bool(matches), f'current {stage} judgment is missing for neighboring join')
        selected = matches[0]
        task = task_for_receipt(record, selected['receipt'])
        read_interior_result(record, task['id'])
        if task['sectionBinding'].get('chunkPlan'):
            from studio.production.section_chunk_join_inputs import validate_chunk_global_joins
            validate_chunk_global_joins(record, task, selected['globalJoins'])
        check_authors(record, task, selected['sections'])
        result.append({**selected, 'stage': stage})
    return result
