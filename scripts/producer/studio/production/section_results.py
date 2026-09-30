"""Owned, current section results; recorded host identity is supervised, not authenticated.

Call under the production authority lock before completion and again at assembly.
The adapter selects actual preview/media input pins. Observation declarations bind
those bytes; neither a host handle nor a receipt proves watching or listening.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from cut_preview_io import file_hash, read_bytes, real_directory
from cross_runtime_canonical_json import canonical_compact_json
from studio.production.host_contract import valid_handle

if TYPE_CHECKING:
    from studio.production.claims import ClaimRef

ROLES = ('author', 'early-review', 'encoded-review')
CHECKS = frozenset({'sourceFidelity', 'captions', 'visuals', 'motion', 'audio', 'neighboringContext'})
BINDING_KEYS = frozenset({'role', 'sectionId', 'generation', 'sharedPlanSha256', 'inputIdentity',
                          'frameRange', 'outputRoot', 'authorTaskId', 'inputs', 'mediaManifest'})
RESULT_KEYS = frozenset({'schemaVersion', 'kind', 'taskId', 'epoch', 'token', 'binding', 'artifacts', 'review'})
SCOPE = ('sectionId', 'generation', 'sharedPlanSha256', 'inputIdentity', 'frameRange')
MAX_ARTIFACT_BYTES = 1024 ** 4
MAX_RESULT_BYTES = 4 * 1024 ** 2
IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}')
SHA256 = re.compile(r'[0-9a-f]{64}')
TOKEN = re.compile(r'[0-9a-f]{32}')


def require(condition: bool, message: str) -> None:
    """Refuse invalid ownership, stale generations or incomplete recorded judgments."""
    if not condition:
        raise ValueError(f'Section result: {message}')


def matches(value: object, pattern: re.Pattern) -> bool:
    """Match only an exact string, excluding coercions."""
    return type(value) is str and pattern.fullmatch(value) is not None


def canonical_path(value: object) -> Path:
    """Require lexical absolute canonical form; filesystem links are checked at reading."""
    require(type(value) is str and '\x00' not in value,
            'artifact path must be absolute')
    path = Path(value)
    require(path.is_absolute() and str(path) == value and '..' not in path.parts,
            'artifact path is not canonical')
    return path


def validate_pin(value: object) -> dict:
    """Validate one closed exact-byte reference without touching the filesystem."""
    require(type(value) is dict and set(value) == {'path', 'sha256', 'bytes'}, 'invalid artifact pin')
    canonical_path(value['path'])
    require(matches(value['sha256'], SHA256) and type(value['bytes']) is int
            and 0 < value['bytes'] <= MAX_ARTIFACT_BYTES, 'invalid artifact digest or size')
    return value


def validate_pins(value: object, minimum: int = 0) -> list[dict]:
    """Bound a distinct list by paths, not merely by differing path/hash pairs."""
    require(type(value) is list and minimum <= len(value) <= 64, 'invalid artifact list')
    for pin in value:
        validate_pin(pin)
    require(len({pin['path'] for pin in value}) == len(value), 'duplicate artifact path')
    return value


def validate_binding(value: object) -> bool:
    """Validate the closed task binding for schema readers, without filesystem side effects."""
    require(type(value) is dict and set(value) - {'reviewScope', 'chunkPlan'} == BINDING_KEYS, 'invalid section binding fields')
    require(value['role'] in ROLES and matches(value['sectionId'], IDENTIFIER), 'invalid section role or id')
    require(type(value['generation']) is int and value['generation'] >= 1, 'invalid section generation')
    require(matches(value['sharedPlanSha256'], SHA256) and matches(value['inputIdentity'], SHA256),
            'invalid section input identity')
    bounds = value['frameRange']
    require(type(bounds) is list and len(bounds) == 2 and all(type(item) is int for item in bounds)
            and 0 <= bounds[0] < bounds[1], 'invalid half-open section frame range')
    canonical_path(value['outputRoot'])
    author = value['authorTaskId']
    require(author is None if value['role'] == 'author' else matches(author, IDENTIFIER),
            'review must name its registered author task')
    pins = validate_pins(value['inputs'], 1)
    require(any(pin['sha256'] == value['sharedPlanSha256'] for pin in pins), 'shared plan is not pinned')
    manifest = value['mediaManifest']
    if 'chunkPlan' in value:
        require(value['role'] == 'encoded-review' and manifest is None and 'reviewScope' not in value,
                'incremental encoded review requires its own inventory')
        validate_pin(value['chunkPlan'])
        require(value['chunkPlan'] in pins, 'chunk review plan is not a task input')
    elif value['role'] == 'encoded-review':
        validate_pin(manifest)
    else:
        require(manifest is None, 'only encoded reviews bind a media manifest')
    if 'reviewScope' in value:
        require(value['role'] != 'author', 'authors cannot declare review scopes')
        validate_pin(value['reviewScope'])
    return True


def rehash(pin: dict) -> None:
    """Read current canonical regular bytes, refusing linked or changed artifacts."""
    validate_pin(pin)
    file = Path(pin['path'])
    require(file.resolve(strict=True) == file, 'artifact path contains a link')
    require(file_hash(file, maximum=MAX_ARTIFACT_BYTES) == pin['sha256'], 'artifact bytes changed')
    require(file.stat().st_size == pin['bytes'], 'artifact size changed')


def task_of(record: dict, task_id: str) -> dict:
    """Resolve a registered section task and its live claim, never a caller-invented owner."""
    task = record['production']['tasks'].get(task_id)
    require(task is not None and task.get('id') == task_id and task.get('runId') == record['batchId'],
            'unknown section task')
    validate_binding(task.get('sectionBinding'))
    claim = task.get('claim')
    require(type(claim) is dict and type(claim.get('epoch')) is int and claim['epoch'] > 0
            and matches(claim.get('token'), TOKEN), 'section task has no registered claim')
    handle = task.get('handle')
    require(valid_handle(handle) and handle['type'] == 'host' and handle['turn'] is not None,
            'section author/reviewer requires a registered exact host turn')
    return task


def current(task: dict, states: tuple[str, ...]) -> None:
    """A terminal or superseded task cannot regain publication; a completed one holding its slot (G9) stays current."""
    require(task.get('state') in states and not task.get('supersededBy') and not task.get('revoked')
            and not (task.get('unresolved') and task.get('state') != 'completed') and not task.get('approvalStale')
            and not task.get('cancelRequested'), 'section task is not current')


def claim_directory(task: dict) -> Path:
    """Derive one task/claim namespace; callers cannot choose another owner's directory."""
    root = canonical_path(task['sectionBinding']['outputRoot'])
    require(matches(task['id'], IDENTIFIER), 'invalid registered task id')
    claim = task['claim']
    return root / task['id'] / f"{claim['epoch']}-{claim['token']}"


def owned_artifacts(document: dict, task: dict, receipt: dict) -> None:
    """Rehash inputs and outputs and enforce disjoint claim-owned output paths."""
    directory = claim_directory(task)
    real_directory(directory)
    require(receipt['path'] == str(directory / 'result.json'), 'result is outside its claim directory')
    inputs = task['sectionBinding']['inputs']
    artifacts = validate_pins(document['artifacts'], 1 if task['sectionBinding']['role'] == 'author' else 0)
    reserved = {receipt['path'], *(pin['path'] for pin in inputs)}
    for pin in artifacts:
        path = Path(pin['path'])
        require(path.is_relative_to(directory) and pin['path'] not in reserved, 'artifact escapes its owner')
    for pin in [*inputs, *artifacts]:
        rehash(pin)


def read_document(task: dict, receipt: dict) -> dict:
    """Read exact immutable result bytes once, then validate every nested owned artifact."""
    validate_pin(receipt)
    require(receipt['bytes'] <= MAX_RESULT_BYTES, 'section result is too large')
    raw = read_bytes(Path(receipt['path']), MAX_RESULT_BYTES)
    require(len(raw) == receipt['bytes'] and hashlib.sha256(raw).hexdigest() == receipt['sha256'],
            'result bytes changed')
    document = json.loads(raw)
    require(type(document) is dict and canonical_compact_json(document).encode() == raw.removesuffix(b'\n'),
            'result must be exact canonical JSON without duplicate keys')
    require(set(document) == RESULT_KEYS and type(document['schemaVersion']) is int
            and document['schemaVersion'] == 1 and document['kind'] == 'native-long-section-result',
            'invalid section result fields')
    require((document['taskId'], document['epoch'], document['token'])
            == (task['id'], task['claim']['epoch'], task['claim']['token'])
            and type(document['epoch']) is int, 'stale result claim')
    validate_binding(document['binding'])
    require(document['binding'] == task['sectionBinding'], 'section result binding changed')
    owned_artifacts(document, task, receipt)
    return document


def author_for(record: dict, task: dict) -> dict:
    """Revalidate the completed author and reject a review by that same registered host thread."""
    binding = task['sectionBinding']
    author = task_of(record, binding['authorTaskId'])
    require(author['sectionBinding']['role'] == 'author' and author['clipId'] == task['clipId'],
            'review names another output or non-author task')
    require(all(binding[key] == author['sectionBinding'][key] for key in SCOPE), 'stale reviewed author')
    require(author['id'] in task['prerequisites'], 'review does not depend on its author')
    identity = lambda row: (row['handle']['host'], row['handle']['thread'])
    require(identity(task) != identity(author), 'reviewer is the author host thread')
    read_completed_result(record, author['id'], author['sectionBinding'])
    require(author['receipts'][0] in binding['inputs'], 'review does not pin its author result')
    return author


def validate_observations(review: dict, binding: dict) -> None:
    """Bind encoded coverage or representative early observations to exact current media."""
    from studio.production.section_chunk_presentation import review_observations
    observations = review['observations']
    picture = 'moving-preview' if binding['role'] == 'early-review' else 'encoded-playback'
    require(type(observations) is list and 2 <= len(observations) <= 1536, 'invalid observation count')
    for row in observations:
        require(type(row) is dict and set(row) == {'kind', 'path', 'sha256', 'frameRange'},
                'invalid review observation')
    require({row['kind'] for row in observations} == {picture, 'audio-listening'}
            and len({(row['kind'], row['path']) for row in observations}) == len(observations),
            'review observation kinds or paths differ')
    if binding['role'] == 'encoded-review':
        expected = review_observations(binding)
        require(sorted(observations, key=lambda row: row['path']) == sorted(expected, key=lambda row: row['path']),
                'observation is not complete pinned current media')
        return
    pins = {pin['path']: pin['sha256'] for pin in binding['inputs']}
    for row in observations:
        bounds = row['frameRange']
        require(type(bounds) is list and len(bounds) == 2 and all(type(frame) is int for frame in bounds)
                and binding['frameRange'][0] <= bounds[0] < bounds[1] <= binding['frameRange'][1]
                and pins.get(row['path']) == row['sha256'], 'preview observation is not pinned contained media')


def validate_review(record: dict, task: dict, document: dict) -> None:
    """Require independent current evidence and complete explicit judgments; never infer approval."""
    review, binding = document['review'], task['sectionBinding']
    if binding['role'] == 'author':
        require(review is None, 'an author cannot publish independent approval')
        return
    author_for(record, task)
    if binding.get('chunkPlan'):
        from studio.production.section_chunk_results import validate_chunk_review
        validate_chunk_review(record, task, document)
        return
    validate_review_shape(review, binding)
    if binding.get('reviewScope'):
        from studio.production.section_judgments import validate_judgment_authors
        validate_judgment_authors(record, task)


def validate_review_shape(review: dict | None, binding: dict) -> None:
    """Check the closed review declaration and evidence without granting current publication."""
    if binding['role'] == 'author':
        require(review is None, 'an author cannot publish independent approval')
        return
    fields = {'status', 'checks', 'assessments', 'observations'} | ({'scopes'} if binding.get('reviewScope') else set())
    require(type(review) is dict and set(review) == fields
            and review['status'] == 'pass', 'review is not a closed passing judgment')
    checks, assessments = review['checks'], review['assessments']
    require(type(checks) is dict and set(checks) == CHECKS and all(value is True for value in checks.values()),
            'required section checks are missing or failed')
    require(type(assessments) is dict and set(assessments) == CHECKS
            and all(type(value) is str and 0 < len(value.strip()) <= 2000 for value in assessments.values()),
            'specific section assessments are required')
    validate_observations(review, binding)
    if binding.get('reviewScope'):
        from studio.production.section_judgments import validate_judgments
        validate_judgments(review, binding)


def validate_result(record: dict, ref: ClaimRef, receipt: dict) -> dict:
    """Validate one active claim's result before the ordinary fenced completion callback."""
    task = task_of(record, ref.task_id)
    require(type(ref.epoch) is int and (ref.epoch, ref.token) == (task['claim']['epoch'], task['claim']['token']),
            'stale completion claim')
    current(task, ('running', 'completed'))
    document = read_document(task, receipt)
    validate_review(record, task, document)
    return document


def validate_settlement_result(record: dict, ref: ClaimRef, receipt: dict) -> dict:
    """Rehash a fenced or cancel-requested execution's historical output; no publication permission is renewed."""
    task = task_of(record, ref.task_id)
    require((task['state'] in ('superseded', 'abandoned') or task.get('cancelRequested')) and type(ref.epoch) is int
            and (ref.epoch, ref.token) == (task['claim']['epoch'], task['claim']['token']),
            'invalid historical settlement claim')
    document = read_document(task, receipt)
    if task['sectionBinding'].get('chunkPlan'):
        from studio.production.section_chunk_results import read_chunk_completion
        read_chunk_completion(task, document['review'])
    else:
        validate_review_shape(document['review'], task['sectionBinding'])
    return document


def read_completed_result(record: dict, task_id: str, expected_binding: dict) -> dict:
    """Revalidate current task, exact expected generation and bytes at the assembly barrier."""
    from studio.production.dependencies import stale_inputs
    validate_binding(expected_binding)
    require(stale_inputs(record).get(task_id) is None, 'section dependency approval is no longer current')
    task = task_of(record, task_id)
    current(task, ('completed',))
    require(task['sectionBinding'] == expected_binding and task.get('endConfirmed') is True,
            'completed section binding differs from current assembly')
    receipts = task.get('receipts')
    require(type(receipts) is list and len(receipts) == 1, 'section completion needs exactly one result receipt')
    document = read_document(task, receipts[0])
    validate_review(record, task, document)
    return document
