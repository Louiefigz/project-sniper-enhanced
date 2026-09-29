"""Integrate current sealed immutable section snapshots under full-project admission."""
from __future__ import annotations

from pathlib import Path

from cut_preview_io import bound_json
from studio.native_runtime import digest
from studio.native_segments.compatibility import _merge_pins, _parent, _seal, section_snapshot_compatibility
from studio.native_stage_evidence import read_stage, require

POINTER_KEYS = {'sectionId', 'originalAttempt', 'originalRequestSha256'}


def integration_source(request: dict, pointer: dict) -> tuple[dict, dict]:
    """Reopen the registered original scope and prove its current shared/section dependencies."""
    require(type(pointer) is dict and set(pointer) == POINTER_KEYS, 'invalid section integration pointer')
    parent = Path(pointer['originalAttempt'])
    original = _parent(parent, pointer['originalRequestSha256'])
    scope = original.get('sectionScope')
    require(scope is not None and scope['sectionId'] == pointer['sectionId'], 'integration source has no selected scope')
    context = request['sectionProduction']
    rows = [row for row in context['assignments'] if row['sectionId'] == pointer['sectionId']]
    require(len(rows) == 1, 'integration section is outside the current assignments')
    row = rows[0]
    require(all(scope[key] == row[key] for key in ('generation', 'inputIdentity', 'frameRange'))
            and scope['sharedPlan'] == context['sharedPlan'], 'integration source has stale assignment inputs')
    budget, prior = request.get('productionBudget', {}), original.get('productionBudget', {})
    require(budget.get('familyId') and prior.get('familyId')
            and all(budget.get(key) == prior.get(key) for key in ('authority', 'batchId', 'clipId')),
            'integration source belongs to another production authority')
    section_snapshot_compatibility(original, request, row['frameRange'])
    return original, row


def prepare_section_integrations(request: dict, attempts: list[Path]) -> dict:
    """Bind every current logical section to complete original seals before final registration."""
    require(not request.get('sectionScope') and request.get('sectionProduction')
            and request.get('prebuildReview', {}).get('scope') == 'native-long-full-project',
            'section integration requires full admitted current project and registered assignments')
    require(1 <= len(attempts) <= 3, 'integration requires one to three original section attempts')
    result = {**request, 'pins': dict(request['pins'])}
    pointers, donors = [], {}
    for attempt in attempts:
        original = _parent(attempt)
        scope = original.get('sectionScope')
        require(scope is not None, 'integration source must be an explicitly scoped immutable snapshot')
        pointer = {'sectionId': scope['sectionId'], 'originalAttempt': str(attempt),
                   'originalRequestSha256': digest(attempt / 'export-request.json')}
        admitted, row = integration_source(result, pointer)
        retain_windows(result, admitted, row, donors)
        _merge_pins(result, {**admitted['pins'], str(attempt / 'export-request.json'): pointer['originalRequestSha256']})
        pointers.append(pointer)
    require(sorted(row['sectionId'] for row in pointers) == sorted(
        row['sectionId'] for row in result['sectionProduction']['assignments']),
        'final integration requires every current logical section exactly once')
    result['sectionIntegrations'] = pointers
    result['revision'] = {**result['revision'], 'windowDonors': donors}
    return result


def retain_windows(current: dict, original: dict, row: dict, donors: dict) -> None:
    """Retain exact original StageEvidence and reject incomplete or overlapping source selections."""
    from studio.native_segments.owners import current_window
    start, end = row['frameRange']
    windows = [window for window in current['revision']['renderWindows']
               if window['startFrame'] < end and window['endFrame'] > start]
    require(windows and windows[0]['startFrame'] == start and windows[-1]['endFrame'] == end,
            'integration section crosses a technical owner boundary')
    for window in windows:
        phase = f"segment-picture-{window['index']}"
        value = current_window(original, phase)
        require(all(value['window'][key] == window[key] for key in ('index', 'startFrame', 'endFrame')),
                'integration changes the original technical geometry')
        file = _seal(original, phase)
        require(file is not None and phase not in donors, 'missing or overlapping integration seal')
        _record, pins = read_stage(file, bound_json(file)['inputs'], phase)
        _merge_pins(current, pins)
        donors[phase] = str(file)


def compatible_integration_donor(request: dict, phase: str) -> tuple[dict, dict]:
    """Cold-revalidate the actual source seal and dependency proof immediately before copying."""
    from studio.native_segments.owners import current_window, segment_phase
    index = segment_phase(phase)
    require(index is not None and index < len(request['revision']['renderWindows']), 'invalid integration window')
    window = request['revision']['renderWindows'][index]
    rows = [row for row in request['sectionProduction']['assignments']
            if row['frameRange'][0] <= window['startFrame'] < window['endFrame'] <= row['frameRange'][1]]
    require(len(rows) == 1, 'integration window has ambiguous logical owner')
    pointers = [row for row in request.get('sectionIntegrations', []) if row['sectionId'] == rows[0]['sectionId']]
    require(len(pointers) == 1, 'integration window lacks one admitted source')
    pointer = pointers[0]
    file = Path(pointer['originalAttempt']) / 'export-request.json'
    require(request['pins'].get(str(file)) == pointer['originalRequestSha256'], 'integration request is unpinned')
    original, _row = integration_source(request, pointer)
    value = current_window(original, phase)
    seal = _seal(original, phase)
    require(seal is not None and request['revision']['windowDonors'].get(phase) == str(seal),
            'integration donor differs from its admitted original seal')
    record, pins = read_stage(seal, bound_json(seal)['inputs'], phase)
    require(all(request['pins'].get(name) == sha for name, sha in pins.items()), 'integration donor is unpinned')
    return record, value
