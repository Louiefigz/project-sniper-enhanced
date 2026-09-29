"""Immutable observation scopes derived from existing preview and section seal readers."""
from __future__ import annotations

from pathlib import Path

from cut_preview_io import bound_json, write_new
from studio.production.section_media import read_index, read_media_manifest, window_observations
from studio.production.section_plan import pin_file
from studio.production.section_results import rehash, require
from studio.production.section_review_inputs import early_inputs, section_windows, window_media
from studio.production.section_scope import join_pairs

KEYS = {'schemaVersion', 'kind', 'request', 'sectionId', 'role', 'scopes'}


def descriptor(name: str, rows: list[dict], observations: list[dict]) -> dict:
    """Name exact reviewed assignment generations separately from the actual observed media."""
    return {'id': name, 'sections': [{key: row[key] for key in
            ('sectionId', 'generation', 'inputIdentity', 'frameRange', 'authorTaskId')} for row in rows],
            'observations': observations}


def early_join(request: dict, left: dict, right: dict) -> list[dict]:
    """Require actual admitted moving media crossing this exact neighboring boundary."""
    from studio.native_motion_previews import current_motion_previews
    from studio.production.section_recovery import original_preview
    value = original_preview(request) or current_motion_previews(request)
    edge = left['frameRange'][1]
    clips = [clip for clip in value['clips'] if clip['absoluteFrameRange'][0] < edge
             and edge < clip['absoluteFrameRange'][1]]
    if request.get('sectionChunks'):
        transitions = [item for row in request['sectionChunks']['assignments']
                       for item in row['transitions'] if item['frame'] == edge]
        require(bool(transitions) and all(item == transitions[0] for item in transitions),
                'early join lacks its current authored transition')
        start, end = transitions[0]['frameRange']
        clips = [clip for clip in clips if clip['absoluteFrameRange'][0] <= start
                 and clip['absoluteFrameRange'][1] >= end]
    require(bool(clips), 'join needs a current continuous preview crossing its boundary')
    bounds = [left['frameRange'][0], right['frameRange'][1]]
    return [{'kind': kind, 'path': clip['path'], 'sha256': clip['sha256'],
             'frameRange': [max(bounds[0], clip['absoluteFrameRange'][0]),
                            min(bounds[1], clip['absoluteFrameRange'][1])]}
            for clip in clips for kind in ('moving-preview', 'audio-listening')]


def encoded_join(request: dict, left: dict, right: dict) -> list[dict]:
    """Reopen both sealed edge windows, including their current mastered PCM excerpts."""
    if request.get('sectionChunks'):
        from studio.native_segments.review_scopes import request_scope
        from studio.production.section_chunk_presentation import manifest_presentation, presentation_observations
        scope = request_scope(request, f"encoded-join:{left['sectionId']}:{right['sectionId']}")
        presentation = manifest_presentation(request, scope)['presentation']
        return presentation_observations(request, presentation, scope['frameRange'])
    windows = [section_windows(request, left)[-1], section_windows(request, right)[0]]
    return [observation for window in windows
            for observation in window_observations(request, window_media(request, window))]


def observation_scopes(request: dict, row: dict, binding: dict) -> list[dict]:
    """Recompute exact interior and assigned join observations from existing media authority."""
    early = binding['role'] == 'early-review'
    interior = early_inputs(request, row)[1] if early else read_media_manifest(binding)
    scopes = [descriptor('interior', [row], interior)]
    if request.get('sectionScope') is not None:
        return scopes
    for left, right in join_pairs(request['sectionProduction'], row):
        name = f"join:{left['sectionId']}:{right['sectionId']}"
        scopes.append(descriptor(f'early-{name}', [left, right], early_join(request, left, right)))
        if not early:
            scopes.append(descriptor(f'encoded-{name}', [left, right], encoded_join(request, left, right)))
    return scopes


def original_request(request: dict, binding: dict) -> dict:
    """Exact resume regenerates the original review index rather than minting another task."""
    if binding['role'] == 'encoded-review':
        pin = read_index(binding['mediaManifest'])['request']
        rehash(pin)
        return bound_json(Path(pin['path']), pin['sha256'])
    retained = request.get('sectionEarlyPreview')
    if retained is not None:
        return bound_json(Path(retained['path']).parent / 'export-request.json')
    return request


def bind_scope(request: dict, row: dict, binding: dict) -> dict:
    """Freeze separately reviewable scopes; no old monolithic pass becomes a scoped judgment."""
    original = original_request(request, binding)
    value = {'schemaVersion': 1, 'kind': 'native-long-review-scopes',
             'request': pin_file(Path(original['output']) / 'export-request.json'),
             'sectionId': row['sectionId'], 'role': binding['role'],
             'scopes': observation_scopes(original, row, binding)}
    file = Path(original['output']) / f"{row['authorTaskId']}-{binding['role']}-scopes.json"
    if file.exists():
        require(read_index(pin_file(file)) == value, 'recorded review scopes changed')
    else:
        write_new(file, value)
    from studio.production.section_plan import unique_pins
    pin = pin_file(file)
    return {**binding, 'reviewScope': pin, 'inputs': unique_pins([*binding['inputs'], pin])}


def read_scope(binding: dict) -> tuple[dict, list[dict]]:
    """Rehash the immutable request and derive observations again at completion and publication."""
    pin = binding['reviewScope']
    require(pin in binding['inputs'], 'review scope is not a task input')
    value = read_index(pin)
    require(set(value) == KEYS and type(value['schemaVersion']) is int and value['schemaVersion'] == 1
            and value['kind'] == 'native-long-review-scopes' and value['role'] == binding['role']
            and value['sectionId'] == binding['sectionId'], 'invalid review scope index')
    rehash(value['request'])
    request = bound_json(Path(value['request']['path']), value['request']['sha256'])
    from studio.production.section_plan import revalidate_context
    context = revalidate_context(request)
    rows = [row for row in context['assignments'] if row['sectionId'] == binding['sectionId']]
    require(len(rows) == 1 and all(rows[0][key] == binding[key]
            for key in ('generation', 'inputIdentity', 'frameRange')), 'review scope generation differs')
    expected = observation_scopes(request, rows[0], binding)
    require(value['scopes'] == expected, 'scope observations differ from current original media proof')
    return request, expected
