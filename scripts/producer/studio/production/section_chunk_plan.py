"""Immutable assignment-local review inventory, never render or transition admission.

This opt-in Python API freezes geometry already matching an admitted request.
Public dispatch must separately admit transitions and preserve author capacity.
"""
from __future__ import annotations

from pathlib import Path

from cut_preview_io import bound_json, write_new
from studio.native_segments.long_chunks import assignment_chunk_map, derive_long_chunks
from studio.native_segments.long_plan import identity
from studio.production.section_media import read_index
from studio.production.section_plan import pin_file
from studio.production.section_results import SCOPE, rehash, require
from studio.production.section_review_inputs import section_windows, window_media

KIND = 'native-long-section-chunk-review-plan'
MAX_SCOPES = 1535


def window_identity(window: dict) -> dict:
    """Bind actual admitted media versions without making sibling plan hashes local inputs."""
    return {key: window[key] for key in ('id', 'index', 'startFrame', 'endFrame', 'generation', 'inputIdentity')}


def scope_inventory(mapping: dict, windows: list[dict]) -> list[dict]:
    """Freeze chunks and each internal neighboring edge, retaining absolute technical windows."""
    by_range = {(row['startFrame'], row['endFrame']): row for row in windows}
    scopes = []
    for chunk in mapping['chunks']:
        ranges = chunk['windowRanges']
        require(all(tuple(bounds) in by_range for bounds in ranges), 'chunk geometry differs from admitted windows')
        scopes.append({'id': chunk['id'], 'kind': 'chunk', 'frameRange': chunk['frameRange'],
                       'windows': [window_identity(by_range[tuple(bounds)]) for bounds in ranges]})
    require([row for scope in scopes for row in scope['windows']] == [window_identity(row) for row in windows],
            'chunks must partition every admitted assignment window exactly once')
    joins = []
    for left, right in zip(scopes, scopes[1:]):
        edges = [left['windows'][-1], right['windows'][0]]
        joins.append({'id': 'join-' + identity([left['id'], right['id']])[:24], 'kind': 'neighboring-edge',
                      'frameRange': [edges[0]['startFrame'], edges[1]['endFrame']], 'windows': edges})
    require(1 <= len(scopes) + len(joins) <= MAX_SCOPES, 'too many chunk review scopes')
    return scopes + joins


def plan_document(request: dict, row: dict) -> dict:
    """Cold derive local geometry and actual versions; no nonexistent future media is read."""
    require(request.get('adapter') == 'native-long' and request['revision']['mode'] == 'initial-long',
            'incremental chunk review is Long only')
    assignments = request['sectionProduction']['assignments']
    require(row in assignments, 'chunk review assignment is not registered in this request')
    candidate = derive_long_chunks(Path(request['project']), assignments, request['revision'])
    mapping = assignment_chunk_map(candidate, row['sectionId'])
    binding = row['authorBinding']
    scopes = scope_inventory(mapping, section_windows(request, row))
    if request.get('sectionChunks'):
        from studio.native_segments.review_scopes import expanded_scope
        scopes = [expanded_scope(request, scope) for scope in scopes]
    return {'schemaVersion': 1, 'kind': KIND, 'request': pin_file(Path(request['output']) / 'export-request.json'),
            'scope': {key: binding[key] for key in SCOPE}, 'map': mapping,
            'scopes': scopes}


def freeze_chunk_plan(request: dict, row: dict, file: Path) -> dict:
    """Publish an immutable experimental QC inventory; it does not authorize rendering."""
    value = plan_document(request, row)
    if file.exists():
        require(read_index(pin_file(file)) == value, 'chunk review plan already differs')
    else:
        write_new(file, value)
    return pin_file(file)


def read_chunk_plan(binding: dict) -> tuple[dict, dict]:
    """Recompute frozen geometry and all current window versions from the pinned original request."""
    value = read_index(binding['chunkPlan'])
    require(set(value) == {'schemaVersion', 'kind', 'request', 'scope', 'map', 'scopes'}
            and value['schemaVersion'] == 1 and type(value['schemaVersion']) is int and value['kind'] == KIND,
            'invalid chunk review plan')
    require(value['scope'] == {key: binding[key] for key in SCOPE}, 'chunk review generation differs')
    rehash(value['request'])
    request = bound_json(Path(value['request']['path']), value['request']['sha256'])
    require(value['request']['path'] == str(Path(request['output']) / 'export-request.json'),
            'chunk plan request is not its immutable export request')
    rows = [row for row in request['sectionProduction']['assignments'] if row['sectionId'] == binding['sectionId']]
    require(len(rows) == 1 and value == plan_document(request, rows[0]), 'chunk plan or current inputs changed')
    return value, request


def scope_of(plan: dict, scope_id: str) -> dict:
    """Resolve only one required immutable scope, never caller-selected ranges."""
    rows = [row for row in plan['scopes'] if row['id'] == scope_id]
    require(len(rows) == 1, 'unknown chunk review scope')
    return rows[0]


def scope_manifest(binding: dict, scope_id: str, file: Path, current: dict | None = None) -> dict:
    """Publish only sealed current windows for a ready chunk or neighboring edge."""
    plan, request = read_chunk_plan(binding)
    if current is not None:
        from studio.production.section_chunk_recovery import exact_chunk_request
        exact_chunk_request(binding, current)
        request = current
    scope = scope_of(plan, scope_id)
    value = scope_media_document(binding, scope, request)
    from studio.production.section_chunk_presentation import manifest_presentation
    value.update(manifest_presentation(request, scope))
    if file.exists():
        require(read_index(pin_file(file)) == value, 'chunk media manifest already differs')
    else:
        write_new(file, value)
    pin = pin_file(file)
    scope_observations(binding, scope_id, pin)
    return pin


def scope_media_document(binding: dict, scope: dict, request: dict) -> dict:
    """Describe current sealed raw media; presentation or retained judgment is a separate proof."""
    windows = [request['revision']['renderWindows'][row['index']] for row in scope['windows']]
    return {'schemaVersion': 1, 'kind': 'native-long-section-media',
             'request': pin_file(Path(request['output']) / 'export-request.json'),
             'planIdentity': request['revision']['identity'], 'sectionId': binding['sectionId'],
             'generation': binding['generation'], 'inputIdentity': binding['inputIdentity'],
             'frameRange': scope['frameRange'], 'windows': [window_media(request, row) for row in windows]}


def scope_observations(binding: dict, scope_id: str, pin: dict) -> list[dict]:
    """Validate exact required current windows with the existing StageEvidence media reader."""
    plan, _request = read_chunk_plan(binding)
    scope = scope_of(plan, scope_id)
    manifest = read_index(pin)
    from studio.production.section_chunk_recovery import scope_request, compare_original_window
    current = scope_request(binding, manifest['request'])
    require([row.get('phase') for row in manifest.get('windows', [])]
            == [f"segment-picture-{row['index']}" for row in scope['windows']], 'chunk media window list differs')
    projected = {**binding, 'frameRange': scope['frameRange'], 'mediaManifest': pin}
    from studio.production.section_chunk_presentation import review_observations
    if current.get('sectionChunks'):
        require(manifest.get('presentation', {}).get('scopeId') == scope_id,
                'chunk review omits its continuous presentation')
    observations = review_observations(projected)
    if current['output'] != _request['output']:
        for row in scope['windows']:
            compare_original_window(_request, current, f"segment-picture-{row['index']}")
    return observations


def ready_chunk_scopes(binding: dict, current: dict | None = None) -> list[dict]:
    """List fully sealed current scopes; absent later windows are pending, corrupt present seals fail."""
    from studio.production.section_chunk_reuse import ready_scopes
    plan, request = read_chunk_plan(binding)
    if current is not None:
        from studio.production.section_chunk_recovery import exact_chunk_request
        exact_chunk_request(binding, current)
        request = current
    return ready_scopes(request, plan['scopes'])
