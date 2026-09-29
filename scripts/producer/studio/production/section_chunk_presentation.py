"""Continuous playback inputs backed by the original sealed window and master proofs.

Cold task readers never create media. The existing section supervisor creates
ready packages before acquiring the production task transaction lock.
"""
from __future__ import annotations

from studio.production.section_results import require


def presentation_pin(request: dict, scope_id: str) -> dict | None:
    """Resolve a current or retained owned clip; missing packages remain explicitly pending."""
    from studio.native_segments.review_package import retained_package
    return retained_package(request, scope_id)


def manifest_presentation(request: dict, scope: dict) -> dict:
    """Require a sealed continuous presentation for admitted chunk review inputs."""
    if not request.get('sectionChunks'):
        return {}
    pin = presentation_pin(request, scope['id'])
    require(pin is not None, 'chunk review requires an owned continuous playback package')
    return {'presentation': {'scopeId': scope['id'], 'receipt': pin}}


def presentation_observations(request: dict, presentation: dict, bounds: list[int]) -> list[dict]:
    """Bind actual playback and listening to one cold-validated muxed clip at its absolute origin."""
    from studio.native_segments.review_package import read_package
    require(type(presentation) is dict and set(presentation) == {'scopeId', 'receipt'},
            'invalid chunk presentation fields')
    value = read_package(request, presentation['scopeId'], presentation['receipt'])
    require(value['scope']['frameRange'] == bounds, 'continuous presentation covers another review scope')
    media = value['media']
    return [{'kind': kind, 'path': media['path'], 'sha256': media['sha256'], 'frameRange': bounds}
            for kind in ('encoded-playback', 'audio-listening')]


def review_observations(binding: dict) -> list[dict]:
    """Keep raw window coverage authoritative while directing the reviewer to continuous media."""
    from studio.production.section_media import checked_request, read_index, read_media_manifest
    index = read_index(binding['mediaManifest'])
    observations = read_media_manifest(binding)
    if 'presentation' not in index:
        return observations
    request = checked_request(index, binding)
    return presentation_observations(request, index['presentation'], binding['frameRange'])


def package_ready_scopes(pipeline: object) -> None:
    """Package only fully sealed scopes while unrelated render futures continue executing."""
    from studio.native_segments.review_package import ensure_package
    from studio.native_segments.review_scopes import package_scopes
    from studio.production.section_chunk_reuse import window_ready
    request = pipeline.request
    if not request.get('sectionChunks'):
        return
    ready = {window['index'] for window in request['revision']['renderWindows']
             if window_ready(request, window['index'])}
    from studio.production.section_chunk_carry import retained_scope_ids
    retained = retained_scope_ids(request)
    for scope in package_scopes(request):
        if scope['id'] not in retained and all(window['index'] in ready for window in scope['windows']):
            ensure_package(pipeline, scope['id'])
