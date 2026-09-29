"""Retain exact-generation review inputs across registered immutable Long attempts.

Only exact section recovery calls this module. Changed-generation repair receives
new review inputs. Original proofs remain immutable, and every retained encoded
window is compared to this attempt's actual restored bytes before its old review
can satisfy the current barrier.
"""
from __future__ import annotations

from pathlib import Path

from cut_preview_io import bound_json
from studio.native_preview_history import preview_chain, prior_preview
from studio.native_review_regions import region_packet
from studio.native_segments.owners import current_window
from studio.native_stage_evidence import read_stage
from studio.production.section_media import read_index, read_media_manifest
from studio.production.section_plan import pin_file
from studio.production.section_results import rehash, require


def retain_section_reviews(current: dict, original: dict) -> dict:
    """Pin completed exact-generation review sources without transferring any task approval."""
    if not original.get('sectionProduction'):
        return current
    require(current['revision']['identity'] == original['revision']['identity'], 'review recovery changed technical plan')
    result = {**current, 'pins': dict(current['pins'])}
    root = Path(original['output'])
    preview = original.get('sectionEarlyPreview')
    if preview is not None or (root / 'motion-previews.json').exists():
        retain_preview(result, preview or pin_file(root / 'motion-previews.json'))
    manifests = {}
    for row in original['sectionProduction']['assignments']:
        source = original.get('sectionReviewManifests', {}).get(row['encodedTaskId'])
        file = root / f"{row['encodedTaskId']}-media.json"
        if source is None and not file.exists():
            continue
        source = source or pin_file(file)
        retain_manifest(result, source, row)
        manifests[row['encodedTaskId']] = source
    if manifests:
        result['sectionReviewManifests'] = manifests
    from studio.production.section_chunk_recovery import retain_chunk_plans
    retain_chunk_plans(result, original)
    return result


def retain_preview(request: dict, pin: dict) -> None:
    """Preserve the original moving-preview owner, request and transitive media pins."""
    rehash(pin)
    chain = preview_chain(Path(pin['path']), request['project'])
    require(chain[0][1]['packet'] == region_packet(request), 'recovered early preview inputs changed')
    request['sectionEarlyPreview'] = pin
    for file, value in chain:
        for source in (file, file.parent / 'export-request.json', file.parent / 'preview.render.json'):
            add_pin(request, pin_file(source))
        for clip in value['clips']:
            add_pin(request, pin_file(Path(clip['path'])))


def add_pin(request: dict, pin: dict) -> None:
    """Retain an exact reference without replacing a conflicting admitted input."""
    require(request['pins'].get(pin['path'], pin['sha256']) == pin['sha256'], 'conflicting retained review input')
    request['pins'][pin['path']] = pin['sha256']


def retained_binding(row: dict, pin: dict) -> dict:
    """Supply the closed manifest reader's logical scope without manufacturing a review result."""
    return {**{key: row[key] for key in ('sectionId', 'generation', 'inputIdentity', 'frameRange')},
            'mediaManifest': pin}


def retain_manifest(request: dict, pin: dict, row: dict) -> None:
    """Revalidate the original manifest and every real StageEvidence input before retaining it."""
    read_media_manifest(retained_binding(row, pin))
    index = read_index(pin)
    require(index['planIdentity'] == request['revision']['identity'], 'retained encoded review belongs to another plan')
    add_pin(request, pin)
    add_pin(request, index['request'])
    for window in index['windows']:
        file = Path(window['seal']['path'])
        _record, pins = read_stage(file, bound_json(file)['inputs'], window['phase'])
        for name, sha in pins.items():
            require(request['pins'].get(name, sha) == sha, 'conflicting retained section proof')
            request['pins'][name] = sha
        for key in ('seal', 'picture', 'audio'):
            add_pin(request, window[key])


def original_preview(request: dict) -> dict | None:
    """Use stable original early media only after exact current-region and original-owner checks."""
    pin = request.get('sectionEarlyPreview')
    if pin is None:
        return None
    rehash(pin)
    require(request['pins'].get(pin['path']) == pin['sha256'], 'early preview is not admitted')
    value = prior_preview(Path(pin['path']), request['project'])
    require(value['packet'] == region_packet(request), 'early preview belongs to different project inputs')
    return value


def restored_manifest(request: dict, row: dict) -> dict | None:
    """Reuse original review inputs only when every current restored window is exactly compatible."""
    pin = request.get('sectionReviewManifests', {}).get(row['encodedTaskId'])
    if pin is None:
        return None
    require(request['pins'].get(pin['path']) == pin['sha256'], 'encoded review manifest is not admitted')
    read_media_manifest(retained_binding(row, pin))
    index = read_index(pin)
    require(index['planIdentity'] == request['revision']['identity'], 'encoded review technical generation changed')
    original = bound_json(Path(index['request']['path']), index['request']['sha256'])
    for window in index['windows']:
        previous = current_window(original, window['phase'])
        present = current_window(request, window['phase'])
        require(previous['window'] == present['window'], 'encoded review window generation changed')
        require(all(previous[key]['sha256'] == present[key]['sha256'] for key in ('piece', 'audio')),
                'restored picture or audio differs from reviewed bytes')
    return pin
