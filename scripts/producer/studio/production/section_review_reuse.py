"""Revalidate explicitly scoped interiors across immutable compatible Long generations."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from studio.production.section_judgments import interior_evidence, read_interior_result
from studio.production.section_media import read_media_manifest
from studio.production.section_results import require


def media_signature(observations: list[dict]) -> list[tuple]:
    """Compare observed media bytes and exact ranges independently from restored file locations."""
    return sorted((item['kind'], tuple(item['frameRange']), item['sha256']) for item in observations)


def compatibility(original: dict, current: dict, bounds: list[int]) -> dict:
    """Require the maintained supported isolation contract, never an inferred DOM locality."""
    from studio.native_segments.compatibility import section_snapshot_compatibility
    return section_snapshot_compatibility(original, current, bounds)


def original_assignment(request: dict, row: dict) -> dict | None:
    """Only an explicitly registered repair parent can supply unchanged author judgments."""
    original = original_request(request, row['sectionId'])
    if original is None:
        return None
    rows = original.get('sectionProduction', {}).get('assignments', [])
    prior = next((item for item in rows if item['sectionId'] == row['sectionId']), None)
    if prior is None or prior['authorBinding'] != row['authorBinding']:
        return None
    require(original['sectionProduction']['sharedPlan'] == request['sectionProduction']['sharedPlan'],
            'retained interior changed shared creative plan')
    return original


def original_request(request: dict, section_id: str) -> dict | None:
    """Reopen only pinned registered repair or ready-section snapshot requests."""
    from studio.native_segments.compatibility import _parent, validate_repair
    parent = validate_repair(request) if request.get('sectionRepair') else None
    if parent is not None and unchanged_assignment(request, parent, section_id):
        return parent
    sources = request.get('sectionIntegrations', [])
    require(type(sources) is list and len(sources) <= 3 and all(type(row) is dict for row in sources),
            'invalid section integration sources')
    matches = [row for row in sources if row.get('sectionId') == section_id]
    require(len(matches) <= 1, 'duplicate section integration source')
    if not matches:
        return parent
    source = matches[0]
    require(set(source) == {'sectionId', 'originalAttempt', 'originalRequestSha256'},
            'invalid section integration pointer')
    file = Path(source['originalAttempt']) / 'export-request.json'
    require(request['pins'].get(str(file)) == source['originalRequestSha256'], 'section snapshot request is not pinned')
    original = _parent(file.parent, source['originalRequestSha256'])
    require(original.get('sectionScope', {}).get('sectionId') == section_id, 'integration donor belongs to another scope')
    return original


def unchanged_assignment(current: dict, original: dict, section_id: str) -> bool:
    """Prefer the full repair parent only for the exact retained logical author binding."""
    rows = current['sectionProduction']['assignments']
    previous = original.get('sectionProduction', {}).get('assignments', [])
    row = next((item for item in rows if item['sectionId'] == section_id), None)
    prior = next((item for item in previous if item['sectionId'] == section_id), None)
    return row is not None and prior is not None and row['authorBinding'] == prior['authorBinding']


def retained_review(request: dict, row: dict, state: tuple[dict, str]) -> dict | None:
    """Read a current explicit interior only after current dependency and media revalidation."""
    record, role = state
    parent = original_assignment(request, row)
    if parent is None:
        return None
    candidates = [task for task in record['production']['tasks'].values()
                  if task.get('sectionBinding', {}).get('authorTaskId') == row['authorTaskId']
                  and task['sectionBinding']['role'] == role
                  and (task['sectionBinding'].get('reviewScope') or task['sectionBinding'].get('chunkPlan'))]
    if not candidates:
        return None
    require(len(candidates) == 1, 'unchanged section has ambiguous original scoped judgments')
    task, document = read_interior_result(record, candidates[0]['id'])
    original, interior, source = interior_evidence(task, document)
    from studio.native_segments.compatibility import _parent
    _parent(Path(original['output']), source['sha256'])
    require(original['sectionProduction']['sharedPlan'] == parent['sectionProduction']['sharedPlan'],
            'retained interior changed the registered shared plan')
    proof = compatibility(original, request, row['frameRange'])
    if role == 'encoded-review':
        compare_current_media(request, row, task['sectionBinding'], interior['observations'])
    return {'task': task, 'document': document, 'scope': interior, 'compatibility': proof}


def compare_current_media(request: dict, row: dict, binding: dict, previous: list[dict] | None = None) -> None:
    """Both picture and mastered PCM must exactly match every previously reviewed interior window."""
    from studio.production.section_review_inputs import section_windows, window_media
    from studio.production.section_media import window_observations
    if binding.get('chunkPlan'):
        require_chunk_geometry(request, row, binding)
        require(previous is not None, 'retained chunks require explicit original scope observations')
    else:
        previous = read_media_manifest(binding)
    current = [item for window in section_windows(request, row)
               for item in window_observations(request, window_media(request, window))]
    require(media_signature(previous) == media_signature(current), 'retained interior picture or PCM changed')


def require_chunk_geometry(request: dict, row: dict, binding: dict) -> None:
    """Require unchanged local chunk semantics before comparing every current picture and PCM range."""
    from studio.native_segments.long_chunks import assignment_chunk_map, derive_long_chunks
    from studio.production.section_chunk_plan import read_chunk_plan
    plan, _original = read_chunk_plan(binding)
    candidate = derive_long_chunks(Path(request['project']), request['sectionProduction']['assignments'],
                                   request['revision'])
    require(assignment_chunk_map(candidate, row['sectionId']) == plan['map'],
            'retained interior chunk geometry or boundary evidence changed')


def retained_early(request: dict, row: dict, record: dict) -> tuple[dict, object] | None:
    """Expose the same task identity to the ordinary early prerequisite barrier."""
    retained = retained_review(request, row, (record, 'early-review'))
    if retained is None:
        return None
    task = retained['task']
    return task['receipts'][0], SimpleNamespace(task_id=task['id'], section_binding=task['sectionBinding'])


def retained_snapshot(request: dict, row: dict, record: dict) -> dict | None:
    """Compose current scope identity with original independently revalidated interior receipts."""
    encoded = retained_review(request, row, (record, 'encoded-review'))
    if encoded is None:
        return None
    early = retained_review(request, row, (record, 'early-review'))
    require(early is not None, 'retained encoded interior has no current early judgment')
    task = encoded['task']
    media = retained_media(task)
    return {key: row[key] for key in ('sectionId', 'generation', 'inputIdentity')} | {
        'earlyReview': early['task']['receipts'][0], 'encodedReview': task['receipts'][0],
        **media,
        'compatibility': encoded['compatibility'], 'interiorOnly': True}


def retained_media(task: dict) -> dict:
    """Keep exact original scope receipts in the final snapshot, never copy an approval to new bytes."""
    binding = task['sectionBinding']
    if not binding.get('chunkPlan'):
        return {'mediaManifest': binding['mediaManifest']}
    from studio.production.section_chunk_dispatch import chunk_snapshot
    return chunk_snapshot(task)
