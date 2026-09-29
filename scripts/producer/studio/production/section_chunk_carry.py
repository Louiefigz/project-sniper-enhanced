"""Append-only retained judgments beside current claim progress, under existing task authority.

Sidecars preserve the original reviewer/claim/receipt, plus current sealed media.
They do not impersonate a new review or release/charge a task. Cold evidence alone
never authorizes carry: publication also rechecks the actual locked task graph.
"""
from __future__ import annotations

from pathlib import Path

from cut_preview_io import bound_json, write_new
from studio.production.section_chunk_plan import (
    MAX_SCOPES, read_chunk_plan, scope_media_document, scope_of,
)
from studio.production.section_chunk_reuse import read_retained_chunk, retained_chunk_scopes
from studio.production.section_media import read_index, read_media_manifest
from studio.production.section_plan import pin_file
from studio.production.section_results import IDENTIFIER, matches, require, validate_pin

KIND = 'native-long-current-chunk-carry'
KEYS = {'schemaVersion', 'kind', 'taskId', 'chunkPlan', 'scopeId', 'mediaManifest', 'proof'}


def carry_path(task: dict, scope_id: str) -> Path:
    """Use the immutable plan's attempt namespace, independently of mutable reviewer claims."""
    return Path(task['sectionBinding']['chunkPlan']['path']).parent / f"{task['id']}-{scope_id}-carry.json"


def valid_carry(task: dict) -> bool:
    """Check bounded reference shapes without opening media during task-schema validation."""
    if 'sectionCarry' not in task:
        return True
    value = task['sectionCarry']
    require(task.get('sectionBinding', {}).get('chunkPlan') is not None and type(value) is dict
            and 1 <= len(value) <= MAX_SCOPES, 'invalid retained chunk inventory')
    for scope_id, pin in value.items():
        require(matches(scope_id, IDENTIFIER), 'invalid retained scope id')
        validate_pin(pin)
        require(pin['path'] == str(carry_path(task, scope_id)), 'retained chunk escapes task plan')
    return True


def write_once(file: Path, value: dict) -> dict:
    """Replay identical immutable evidence, refusing a conflicting or corrupt retained sidecar."""
    if file.exists():
        require(read_index(pin_file(file)) == value, 'retained chunk sidecar already differs')
    else:
        write_new(file, value)
    return pin_file(file)


def store_carry(task: dict, request: dict, proof: dict) -> dict:
    """Freeze current raw media without pretending the old continuous presentation is new."""
    scope_id, scope = proof['scopeId'], proof['currentScope']
    file = carry_path(task, scope_id)
    manifest = write_once(file.with_name(file.stem + '-media.json'),
                          scope_media_document(task['sectionBinding'], scope, request))
    value = {'schemaVersion': 1, 'kind': KIND, 'taskId': task['id'],
             'chunkPlan': task['sectionBinding']['chunkPlan'], 'scopeId': scope_id,
             'mediaManifest': manifest, 'proof': proof}
    pin = write_once(file, value)
    read_carry(task, pin)
    return pin


def read_carry(task: dict, pin: dict) -> dict:
    """Cold-check historical judgment and its exact current raw-media projection, not live authority."""
    value = read_index(pin)
    require(set(value) == KEYS and type(value['schemaVersion']) is int and value['schemaVersion'] == 1
            and value['kind'] == KIND and value['taskId'] == task['id']
            and value['chunkPlan'] == task['sectionBinding']['chunkPlan'], 'invalid retained chunk binding')
    scope_id, proof = value['scopeId'], value['proof']
    require(matches(scope_id, IDENTIFIER) and pin['path'] == str(carry_path(task, scope_id))
            and proof['scopeId'] == scope_id, 'retained chunk scope differs')
    original = read_retained_chunk(proof)
    plan, _request = read_chunk_plan(task['sectionBinding'])
    scope = scope_of(plan, scope_id)
    require(proof['currentScope'] == scope, 'retained chunk has another current generation')
    from studio.production.section_chunk_recovery import scope_request
    request = scope_request(task['sectionBinding'], proof['currentRequest'])
    require(read_index(value['mediaManifest']) == scope_media_document(task['sectionBinding'], scope, request),
            'retained chunk current media projection differs')
    observations = read_media_manifest({**task['sectionBinding'], 'frameRange': scope['frameRange'],
                                       'mediaManifest': value['mediaManifest']})
    require(observations == proof['currentWindowMedia'], 'retained chunk current media differs')
    return {'scopeId': scope_id, 'mediaManifest': value['mediaManifest'],
            'receipt': proof['originalReceipt'], 'retainedJudgment': pin, 'originalReview': original,
            'proof': proof}


def require_live_carry(record: dict, task: dict, pins: list[dict]) -> list[dict]:
    """Revalidate each selected original judgment against actual author/withdrawal authority."""
    values, candidates = [], {}
    for pin in pins:
        value = read_carry(task, pin)
        require(authorized_carry(record, task, value, candidates), 'retained judgment is no longer authorized')
        values.append(value)
    return values


def authorized_carry(record: dict, task: dict, value: dict, candidates: dict) -> bool:
    """Cache only within this locked read, so later explicit withdrawal is always observed."""
    source = value['proof']['currentRequest']
    key = source['sha256'], source['path']
    if key not in candidates:
        request = bound_json(Path(source['path']), source['sha256'])
        row = next(row for row in request['sectionProduction']['assignments']
                   if row['sectionId'] == task['sectionBinding']['sectionId'])
        candidates[key] = retained_chunk_scopes(record, request, row)
    return value['proof'] in candidates[key]


def planned_carry(record: dict, request: dict, row: dict, spec: object) -> dict:
    """Prepare sidecars before mutation; existing references never change on dispatch replay."""
    task = record['production']['tasks'].get(spec.task_id) or {
        'id': spec.task_id, 'sectionBinding': spec.section_binding}
    retained, current, candidates = {}, [], {}
    for scope_id, pin in task.get('sectionCarry', {}).items():
        value = read_carry(task, pin)
        if scope_id not in task.get('sectionProgress', {}) and authorized_carry(record, task, value, candidates):
            retained[scope_id] = pin
            current.append(value)
    if current:
        from studio.production.section_chunk_recovery import compare_current_scopes
        compare_current_scopes(request, task, current)
    for proof in retained_chunk_scopes(record, request, row):
        if proof['scopeId'] not in retained and proof['scopeId'] not in task.get('sectionProgress', {}):
            retained[proof['scopeId']] = store_carry(task, request, proof)
    return retained


def carry_input(spec: object, scope: dict, pin: dict) -> dict:
    """Tell the host exactly which old review is retained without claiming a fresh observation."""
    value = read_carry({'id': spec.task_id, 'sectionBinding': spec.section_binding}, pin)
    proof = value['proof']
    return {'taskId': spec.task_id, 'scopeId': scope['id'], 'kind': scope['kind'],
            'frameRange': scope['frameRange'], 'mediaManifest': value['mediaManifest'],
            'status': 'retained-judgment', 'retainedJudgment': pin,
            'originalTaskId': proof['originalTaskId'], 'originalClaim': proof['originalClaim'],
            'originalReceipt': proof['originalReceipt'],
            'observations': value['originalReview']['review']['observations']}


def retained_scope_ids(request: dict) -> set[str]:
    """Avoid rebuilding an unchanged review clip while its original judgment remains authorized."""
    if not request.get('sectionRepair') or not request.get('sectionProduction'):
        return set()
    from studio.native_budget_store import locked_batch
    from studio.production.section_plan import require_context, revalidate_context
    from studio.production.section_scope import selected_assignments
    context = revalidate_context(request)
    with locked_batch(Path(context['authority']), context['batchId']) as session:
        record = session.read()
        require_context(record, context)
        return {proof['scopeId'] for row in selected_assignments(request, context)
                for proof in retained_chunk_scopes(record, request, row)}
