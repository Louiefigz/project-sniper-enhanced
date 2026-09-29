"""Exact-generation continuation of one reviewer across immutable media attempts.

The original task inventory stays frozen. Later receipts may name a registered
exact resume only after its original pins, author scope and actual windows agree.
"""
from __future__ import annotations

from pathlib import Path

from cut_preview_io import bound_json
from studio.native_segments.owners import current_window
from studio.native_stage_evidence import read_stage
from studio.production.section_chunk_plan import read_chunk_plan
from studio.production.section_plan import pin_file
from studio.production.section_results import rehash, require


def plan_binding(row: dict, pin: dict) -> dict:
    """Project the original author scope for the existing immutable inventory reader."""
    return {**row['authorBinding'], 'chunkPlan': pin}


def retain_chunk_plans(current: dict, original: dict) -> None:
    """Pin original complete or partial review inventories without copying task approvals."""
    from studio.production.section_recovery import add_pin
    retained = {}
    for row in original['sectionProduction']['assignments']:
        file = Path(original['output']) / f"{row['encodedTaskId']}-chunks.json"
        pin = original.get('sectionChunkPlans', {}).get(row['encodedTaskId'])
        if pin is None and not file.exists():
            continue
        pin = pin or pin_file(file)
        plan, source = read_chunk_plan(plan_binding(row, pin))
        require(source['revision']['identity'] == current['revision']['identity'], 'chunk recovery changed generation')
        add_pin(current, pin)
        add_pin(current, plan['request'])
        retain_available_windows(current, source, plan)
        retained[row['encodedTaskId']] = pin
    if retained:
        current['sectionChunkPlans'] = retained


def retain_available_windows(current: dict, original: dict, plan: dict) -> None:
    """Carry existing cleanup/media proofs; unfinished scopes remain absent and pending."""
    windows = {row['index'] for scope in plan['scopes'] for row in scope['windows']}
    for index in windows:
        phase = f'segment-picture-{index}'
        file = Path(original['output']) / f'{phase}-stage.json'
        if not file.exists():
            continue
        current_window(original, phase)
        _record, pins = read_stage(file, bound_json(file)['inputs'], phase)
        require(all(current['pins'].get(path, sha) == sha for path, sha in pins.items()),
                'conflicting retained chunk proof')
        current['pins'].update(pins)


def exact_chunk_request(binding: dict, current: dict) -> dict:
    """Require a registered exact continuation with the original frozen scope and source closure."""
    from studio.native_segments.compatibility import _parent
    plan, original = read_chunk_plan(binding)
    if current == original:
        return original
    file = Path(current['output']) / 'export-request.json'
    require(_parent(file.parent, pin_file(file)['sha256']) == current, 'chunk continuation request differs')
    require(all(current.get(key) == original.get(key) for key in
                ('project', 'runtime', 'tools', 'audioProfile', 'preparedMaster', 'audioDonor',
                 'sectionProduction', 'sectionScope', 'sectionChunks')),
            'chunk continuation changed project, tools or assignment authority')
    require(current['revision']['identity'] == original['revision']['identity']
            and current['revision']['renderWindows'] == original['revision']['renderWindows'],
            'chunk continuation changed technical window generation')
    require(all(current['pins'].get(path) == sha for path, sha in original['pins'].items()),
            'chunk continuation dropped original inputs')
    row = next(row for row in original['sectionProduction']['assignments']
               if row['sectionId'] == binding['sectionId'])
    require(current.get('sectionChunkPlans', {}).get(row['encodedTaskId']) == binding['chunkPlan']
            and current['pins'].get(binding['chunkPlan']['path']) == binding['chunkPlan']['sha256']
            and current['pins'].get(plan['request']['path']) == plan['request']['sha256'],
            'chunk continuation lacks its admitted original inventory')
    return original


def scope_request(binding: dict, pin: dict) -> dict:
    """Open the exact original or registered resumed request named by a scope media manifest."""
    rehash(pin)
    request = bound_json(Path(pin['path']), pin['sha256'])
    require(pin['path'] == str(Path(request['output']) / 'export-request.json'),
            'chunk scope names a noncanonical request')
    exact_chunk_request(binding, request)
    return request


def compare_original_window(original: dict, current: dict, phase: str) -> None:
    """An exact resume may fill a missing scope, but cannot change previously sealed picture or PCM."""
    present = current_window(current, phase)
    file = Path(original['output']) / f'{phase}-stage.json'
    if not file.exists() and phase not in original['revision'].get('windowDonors', {}):
        return
    previous = current_window(original, phase)
    require(previous['window'] == present['window']
            and all(previous[key]['sha256'] == present[key]['sha256'] for key in ('piece', 'audio')),
            'exact chunk continuation changed reviewed picture or PCM')


def compare_current_scopes(request: dict, task: dict, scopes: list[dict]) -> None:
    """Compare every actual reviewed scope, including chunks first completed in later attempts."""
    from studio.production.section_chunk_plan import scope_of
    from studio.production.section_media import read_index, read_media_manifest, window_observations
    from studio.production.section_review_inputs import window_media
    from studio.production.section_review_reuse import media_signature
    binding = task['sectionBinding']
    exact_chunk_request(binding, request)
    plan, _original = read_chunk_plan(binding)
    for value in scopes:
        scope = scope_of(plan, value['scopeId'])
        windows = [request['revision']['renderWindows'][row['index']] for row in scope['windows']]
        observations = [item for row in windows for item in window_observations(request, window_media(request, row))]
        previous = read_media_manifest({**binding, 'frameRange': scope['frameRange'],
                                        'mediaManifest': value['mediaManifest']})
        index = read_index(value['mediaManifest'])
        if index.get('presentation'):
            from studio.production.section_chunk_presentation import presentation_observations
            presentation_observations(request, index['presentation'], scope['frameRange'])
        require(media_signature(observations) == media_signature(previous),
                'current resumed chunk picture or PCM differs from reviewed bytes')
