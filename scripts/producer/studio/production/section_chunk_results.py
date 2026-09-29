"""Claim-owned incremental judgments and complete current chunk-review inventories."""
from __future__ import annotations

from studio.production.section_chunk_plan import read_chunk_plan, scope_observations
from studio.production.section_media import read_index
from studio.production.section_results import (
    IDENTIFIER, claim_directory, matches, rehash, require, validate_review_shape,
)

PROGRESS_KIND = 'native-long-section-chunk-result'
PROGRESS_KEYS = {'schemaVersion', 'kind', 'taskId', 'epoch', 'token', 'chunkPlan', 'scopeId',
                 'mediaManifest', 'review'}


def read_progress(task: dict, receipt: dict) -> dict:
    """Rehash one exact claim receipt, current scope media and explicit independent judgments."""
    binding = task['sectionBinding']
    value = read_index(receipt)
    require(set(value) == PROGRESS_KEYS and type(value['schemaVersion']) is int
            and value['schemaVersion'] == 1 and value['kind'] == PROGRESS_KIND, 'invalid chunk result fields')
    require(type(value['epoch']) is int and (value['taskId'], value['epoch'], value['token'])
            == (task['id'], task['claim']['epoch'], task['claim']['token']), 'stale chunk result claim')
    scope_id = value['scopeId']
    require(matches(scope_id, IDENTIFIER) and receipt['path']
            == str(claim_directory(task) / 'chunks' / f'{scope_id}.json'), 'chunk result escapes its claim')
    require(value['chunkPlan'] == binding['chunkPlan'], 'chunk result plan differs')
    for pin in binding['inputs']:
        rehash(pin)
    expected = scope_observations(binding, scope_id, value['mediaManifest'])
    bounds = [min(row['frameRange'][0] for row in expected), max(row['frameRange'][1] for row in expected)]
    projected = {key: item for key, item in binding.items() if key != 'chunkPlan'}
    projected.update(frameRange=bounds, mediaManifest=value['mediaManifest'])
    validate_review_shape(value['review'], projected)
    require(value['review']['observations'] == expected, 'chunk observations differ from current scope')
    return value


def read_chunk_completion(task: dict, review: dict) -> list[dict]:
    """Require exactly every current chunk and edge; no progress receipt is a terminal result alone."""
    require(type(review) is dict and set(review) in ({'status', 'progress', 'globalJoins'},
            {'status', 'progress', 'globalJoins', 'retained'}) and review['status'] == 'pass',
            'invalid incremental review completion')
    plan, _request = read_chunk_plan(task['sectionBinding'])
    required = [scope['id'] for scope in plan['scopes']]
    progress = task.get('sectionProgress', {})
    require(set(progress) <= set(required), 'incremental review names an unknown scope')
    pins = review['progress']
    retained = task.get('sectionCarry', {})
    missing = [key for key in required if key not in progress]
    require(all(key in retained for key in missing), 'incremental review is incomplete')
    selected = review.get('retained', [])
    require(type(selected) is list and selected == [retained[key] for key in missing],
            'final review does not explicitly select every retained judgment')
    require(type(pins) is list and pins == [progress[key] for key in required if key in progress],
            'final review does not bind every recorded scope in frozen order')
    from studio.production.section_chunk_carry import read_carry
    return [{**read_progress(task, progress[key]), 'receipt': progress[key]} if key in progress
            else read_carry(task, retained[key]) for key in required]


def completed_scope_snapshot(task: dict) -> list[dict]:
    """Expose verified scope judgments to final adapters without granting sibling-join approval."""
    from studio.production.section_results import read_document
    require(task['state'] == 'completed' and len(task['receipts']) == 1, 'chunk task has no final result')
    value = read_document(task, task['receipts'][0])
    return read_chunk_completion(task, value['review'])


def validate_chunk_review(record: dict, task: dict, document: dict) -> None:
    """Recheck dependency currentness, all interiors, and independently authored full-project joins."""
    from studio.production.dependencies import stale_inputs
    from studio.production.section_chunk_join_inputs import validate_chunk_global_joins
    require(stale_inputs(record).get(task['id']) is None, 'section dependency approval is no longer current')
    review = document['review']
    read_chunk_completion(task, review)
    from studio.production.section_chunk_carry import require_live_carry
    require_live_carry(record, task, review.get('retained', []))
    pin = review['globalJoins']
    require(pin is None or pin in document['artifacts'], 'global join review must be an owned final artifact')
    validate_chunk_global_joins(record, task, pin)
