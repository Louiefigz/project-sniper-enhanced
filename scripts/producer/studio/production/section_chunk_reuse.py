"""Read-only carry proofs for unchanged scopes within an explicitly repaired author.

The old judgment keeps its original task, claim, receipt and media provenance.
This module does not record progress, complete a new reviewer, release an old
slot or grant a callback to a superseded task. Changed scopes remain unreviewed.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from studio.production.section_chunk_plan import plan_document, read_chunk_plan
from studio.production.section_chunk_results import read_progress
from studio.production.section_chunk_reuse_history import historical_reviewers, repair_authors
from studio.production.section_results import require


def matching_scope(previous: dict, current: dict) -> bool:
    """Geometry may keep its identity while technical versions are independently revalidated."""
    if any(previous[key] != current[key] for key in ('id', 'kind', 'frameRange')):
        return False
    ranges = lambda scope: [(row['startFrame'], row['endFrame']) for row in scope['windows']]
    return ranges(previous) == ranges(current)


def local_compatibility(original: dict, request: dict, bounds: list[int]) -> dict | None:
    """Require actual scoped dependencies, including local chunk and transition decisions."""
    from studio.native_segments.section_closure import section_input_closure
    from studio.native_segments.compatibility import section_snapshot_compatibility
    before = section_input_closure(Path(original['project']), bounds)
    after = section_input_closure(Path(request['project']), bounds)
    if any(before[key] != after[key] for key in ('canvas', 'sharedIdentity', 'sectionIdentity')):
        return None
    return section_snapshot_compatibility(original, request, bounds)


def current_observations(request: dict, scope: dict) -> list[dict]:
    """Read every current picture/PCM through its existing seal and dependency-probe barrier."""
    from studio.production.section_media import window_observations
    from studio.production.section_review_inputs import window_media
    windows = request['revision']['renderWindows']
    return [observation for item in scope['windows']
            for observation in window_observations(request, window_media(request, windows[item['index']]))]


def scope_carry(request: dict, original: dict, task: dict, scopes: tuple[dict, dict]) -> dict | None:
    """Prove one already-recorded judgment still describes the complete current scope."""
    from studio.production.section_media import read_media_manifest
    from studio.production.section_review_reuse import media_signature
    previous, current = scopes
    if not matching_scope(previous, current):
        return None
    pin = task.get('sectionProgress', {}).get(previous['id'])
    if pin is None:
        return None
    value = read_progress(task, pin)
    proof = local_compatibility(original, request, current['frameRange'])
    if proof is None:
        return None
    binding = {**task['sectionBinding'], 'frameRange': previous['frameRange'],
               'mediaManifest': value['mediaManifest']}
    old_media = read_media_manifest(binding)
    now_media = current_observations(request, current)
    if media_signature(old_media) != media_signature(now_media):
        return None
    return {'schemaVersion': 1, 'kind': 'native-long-retained-chunk-judgment', 'scopeId': current['id'],
            'frameRange': current['frameRange'], 'scopeKind': current['kind'],
            'originalTaskId': task['id'], 'originalClaim': {key: task['claim'][key] for key in ('epoch', 'token')},
            'originalReceipt': pin, 'originalManifest': value['mediaManifest'],
            'originalChunkPlan': task['sectionBinding']['chunkPlan'],
            'originalTask': deepcopy({key: task[key] for key in
                                     ('id', 'claim', 'handle', 'sectionBinding', 'sectionProgress')}),
            'currentRequest': current_request_pin(request), 'currentScope': deepcopy(current),
            'currentWindowMedia': now_media, 'compatibility': proof}


def current_request_pin(request: dict) -> dict:
    """Bind an immutable request artifact, never an unrecorded caller-selected current view."""
    from cut_preview_io import bound_json
    from studio.production.section_plan import pin_file
    pin = pin_file(Path(request['output']) / 'export-request.json')
    require(bound_json(Path(pin['path']), pin['sha256']) == request, 'chunk carry request is not published')
    return pin


def read_retained_chunk(proof: dict) -> dict:
    """Cold-reopen an already-authorized proof without inventing live task authority.

    This validates immutable provenance and media only. The live caller must
    separately match retained_chunk_scopes against the actual locked record.
    Historical settlement may use this reader without reviving a superseded
    reviewer or claiming its old callback is current.
    """
    from cut_preview_io import bound_json
    from studio.production.section_results import rehash
    task = proof['originalTask']
    old_plan, original = read_chunk_plan(task['sectionBinding'])
    rehash(proof['currentRequest'])
    request = bound_json(Path(proof['currentRequest']['path']), proof['currentRequest']['sha256'])
    row = next(item for item in request['sectionProduction']['assignments']
               if item['sectionId'] == task['sectionBinding']['sectionId'])
    scopes = {item['id']: item for item in plan_document(request, row)['scopes']}
    previous = next(item for item in old_plan['scopes'] if item['id'] == proof['scopeId'])
    expected = scope_carry(request, original, task, (previous, scopes[proof['scopeId']]))
    require(expected is not None and expected == proof, 'retained chunk proof or current dependencies changed')
    return read_progress(task, proof['originalReceipt'])


def window_ready(request: dict, index: int) -> bool:
    """Reuse existing cold barriers; an old repair donor awaits its current owner reseal."""
    from cut_preview_io import bound_json
    from studio.native_segments.compatibility import compatible_donor
    from studio.native_segments.owners import current_window
    from studio.native_stage_evidence import read_stage
    phase = f'segment-picture-{index}'
    direct = Path(request['output']) / f'{phase}-stage.json'
    if direct.exists() or direct.is_symlink():
        current_window(request, phase)
        return True
    donor = request['revision'].get('windowDonors', {}).get(phase)
    if donor is None:
        return False
    seal = Path(donor)
    record, _pins = read_stage(seal, bound_json(seal)['inputs'], phase)
    receipt = record['artifacts']['receipt']
    value = bound_json(Path(receipt['path']), receipt['sha256'])
    if value.get('planIdentity') != request['revision']['identity']:
        if request.get('sectionIntegrations'):
            from studio.native_long_integration import compatible_integration_donor
            compatible_integration_donor(request, phase)
        else:
            compatible_donor(request, phase)
        return False
    current_window(request, phase)
    return True


def ready_scopes(request: dict, scopes: list[dict]) -> list[dict]:
    """Missing later media is pending; corrupt present evidence cannot hide behind that absence."""
    indexes = {window['index'] for scope in scopes for window in scope['windows']}
    ready = {index for index in indexes if window_ready(request, index)}
    return [scope for scope in scopes if all(window['index'] in ready for window in scope['windows'])]


def retained_chunk_scopes(record: dict, request: dict, row: dict) -> list[dict]:
    """Return original provenance for compatible recorded scopes; never fabricate current reviews."""
    if not request.get('sectionRepair') or row.get('authorKind') != 'repairCycle':
        return []
    original, author, prior = repair_authors(record, request, row)
    reviewers = historical_reviewers(record, (author, prior))
    if not reviewers:
        return []
    task = reviewers[0]
    previous_plan, source = read_chunk_plan(task['sectionBinding'])
    require(source == original, 'chunk carry reviewer belongs to another parent request')
    current_plan = plan_document(request, row)
    previous = {scope['id']: scope for scope in previous_plan['scopes']}
    result = []
    for scope in ready_scopes(request, current_plan['scopes']):
        if scope['id'] not in previous:
            continue
        carried = scope_carry(request, original, task, (previous[scope['id']], scope))
        if carried is not None:
            result.append(carried)
    return result
