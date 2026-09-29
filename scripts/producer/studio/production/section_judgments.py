"""Separate interior and neighboring-join judgments over exact observed byte scopes."""
from __future__ import annotations

from studio.production.section_results import CHECKS, read_completed_result, require, task_of
from studio.production.section_review_scope import read_scope


def validate_judgments(review: dict, binding: dict) -> None:
    """Require explicitly authored checks and observations for every independently reusable scope."""
    _request, expected = read_scope(binding)
    judgments = review.get('scopes')
    require(type(judgments) is list and len(judgments) == len(expected), 'missing scoped judgments')
    for value, scope in zip(judgments, expected):
        validate_judgment(value, scope)


def validate_judgment(value: dict, scope: dict) -> None:
    """A global section pass cannot be silently reinterpreted as an interior or join pass."""
    require(type(value) is dict and set(value) == {'id', 'checks', 'assessments', 'observations'}
            and value['id'] == scope['id'] and value['observations'] == scope['observations'],
            'judgment scope or observations differ')
    require(type(value['checks']) is dict and set(value['checks']) == CHECKS
            and all(value is True for value in value['checks'].values()), 'scoped checks are missing or failed')
    require(type(value['assessments']) is dict and set(value['assessments']) == CHECKS
            and all(type(text) is str and 0 < len(text.strip()) <= 2000
                    for text in value['assessments'].values()), 'scoped assessments are required')


def validate_judgment_authors(record: dict, task: dict) -> None:
    """A join reviewer must be independent of every current author on both sides."""
    _request, scopes = read_scope(task['sectionBinding'])
    rows = {section['authorTaskId']: section for scope in scopes for section in scope['sections']}
    for task_id, section in rows.items():
        author = task_of(record, task_id)
        require(author['clipId'] == task['clipId'] and author['sectionBinding']['role'] == 'author'
                and all(author['sectionBinding'][key] == section[key]
                        for key in ('sectionId', 'generation', 'inputIdentity', 'frameRange')),
                'scoped judgment author differs')
        require((author['handle']['host'], author['handle']['thread'])
                != (task['handle']['host'], task['handle']['thread']), 'join reviewer is an involved author')
        read_completed_result(record, task_id, author['sectionBinding'])


def read_interior_result(record: dict, task_id: str) -> tuple[dict, dict]:
    """Read only an explicit original interior; old neighboring approval is never transferred."""
    from studio.production.dependencies import stale_inputs
    from studio.production.section_results import author_for, current, read_document, validate_review_shape
    task = task_of(record, task_id)
    binding = task['sectionBinding']
    require(binding.get('reviewScope') is not None or binding.get('chunkPlan') is not None,
            'monolithic review has no reusable interior')
    require(stale_inputs(record).get(task_id) is None, 'retained interior dependency is stale')
    current(task, ('completed',))
    require(task.get('endConfirmed') is True and len(task.get('receipts', [])) == 1,
            'retained interior has no completed receipt')
    document = read_document(task, task['receipts'][0])
    author_for(record, task)
    if binding.get('chunkPlan'):
        from studio.production.section_chunk_results import read_chunk_completion
        read_chunk_completion(task, document['review'])
        from studio.production.section_chunk_carry import require_live_carry
        require_live_carry(record, task, document['review'].get('retained', []))
    else:
        validate_review_shape(document['review'], binding)
    return task, document


def interior_evidence(task: dict, document: dict) -> tuple[dict, dict, dict]:
    """Expose only explicitly judged interiors, excluding obsolete neighboring approval authority."""
    from studio.production.section_media import read_index, read_media_manifest
    binding = task['sectionBinding']
    if not binding.get('chunkPlan'):
        original, scopes = read_scope(binding)
        return original, scopes[0], read_index(binding['reviewScope'])['request']
    from studio.production.section_chunk_plan import read_chunk_plan
    from studio.production.section_chunk_results import read_chunk_completion
    from studio.production.section_review_scope import descriptor
    plan, original = read_chunk_plan(binding)
    values = read_chunk_completion(task, document['review'])
    chunks = {scope['id']: scope for scope in plan['scopes'] if scope['kind'] == 'chunk'}
    observations = [item for value in values if value['scopeId'] in chunks
                    for item in read_media_manifest({**binding, 'frameRange': chunks[value['scopeId']]['frameRange'],
                                                     'mediaManifest': value['mediaManifest']})]
    row = next(row for row in original['sectionProduction']['assignments']
               if row['sectionId'] == binding['sectionId'])
    return original, descriptor('interior', [row], observations), plan['request']
