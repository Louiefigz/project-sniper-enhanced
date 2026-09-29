"""Actual moving-preview coverage and sealed encoded media for logical section reviews."""
from __future__ import annotations

from pathlib import Path

from cut_preview_io import bound_json, write_new
from studio.native_segments.owners import current_window
from studio.production.section_plan import pin_file, unique_pins
from studio.production.section_results import require


def overlap(left: list[int], right: list[int]) -> list[int] | None:
    """Intersect two half-open absolute frame ranges."""
    start, end = max(left[0], right[0]), min(left[1], right[1])
    return [start, end] if start < end else None


def early_inputs(request: dict, row: dict) -> tuple[list[dict], list[dict]]:
    """Select every required actual moving-preview overlap, with its muxed mastered audio."""
    from studio.native_motion_previews import current_motion_previews
    from studio.production.section_recovery import original_preview
    value = original_preview(request) or current_motion_previews(request)
    clips = [(clip, overlap(clip['absoluteFrameRange'], row['frameRange'])) for clip in value['clips']]
    selected = [(clip, bounds) for clip, bounds in clips if bounds is not None]
    require(bool(selected), 'logical section needs current representative moving previews before rendering')
    pins = unique_pins([pin_file(Path(clip['path'])) for clip, _bounds in selected])
    expected = [{'kind': kind, 'path': clip['path'], 'sha256': clip['sha256'], 'frameRange': bounds}
                for clip, bounds in selected for kind in ('moving-preview', 'audio-listening')]
    return pins, expected


def section_windows(request: dict, row: dict) -> list[dict]:
    """Logical groups must contain whole technical windows and cover their exact range."""
    start, end = row['frameRange']
    windows = [window for window in request['revision']['renderWindows']
               if window['startFrame'] < end and window['endFrame'] > start]
    require(bool(windows) and windows[0]['startFrame'] == start and windows[-1]['endFrame'] == end,
            'logical assignment must align with technical window boundaries')
    return windows


def window_media(request: dict, window: dict) -> dict:
    """Read the actual current sealed picture/PCM and identify its exact technical proof."""
    phase = f"segment-picture-{window['index']}"
    value = current_window(request, phase)
    root = Path(request['output'])
    seal = root / f'{phase}-stage.json'
    if not seal.exists():
        seal = Path(request['revision']['windowDonors'][phase])
    return {'phase': phase, 'seal': pin_file(seal), 'picture': pin_file(Path(value['piece']['path'])),
            'audio': pin_file(Path(value['audio']['path'])),
            'frameRange': [window['startFrame'], window['endFrame']]}


def media_manifest(request: dict, row: dict) -> dict:
    """Publish one immutable manifest only once every logical group's technical window is sealed."""
    from studio.production.section_recovery import restored_manifest
    retained = restored_manifest(request, row)
    if retained is not None:
        return retained
    root = Path(request['output'])
    value = {'schemaVersion': 1, 'kind': 'native-long-section-media',
             'request': pin_file(root / 'export-request.json'), 'planIdentity': request['revision']['identity'],
             **{key: row[key] for key in ('sectionId', 'generation', 'inputIdentity', 'frameRange')},
             'windows': [window_media(request, window) for window in section_windows(request, row)]}
    file = root / f"{row['encodedTaskId']}-media.json"
    if file.exists():
        require(bound_json(file) == value, 'logical encoded media changed after its review task was frozen')
    else:
        write_new(file, value)
    return pin_file(file)


def encoded_ready(request: dict, row: dict) -> bool:
    """Only missing seals defer a group; a present corrupted seal must fail loudly."""
    root = Path(request['output'])
    donors = request['revision'].get('windowDonors', {})
    for window in section_windows(request, row):
        phase = f"segment-picture-{window['index']}"
        if not (root / f'{phase}-stage.json').exists() and phase not in donors:
            return False
        if not (root / f'{phase}.json').exists():
            return False
        if not (root / f'{phase}-stage.json').exists() and not current_donor(request, donors[phase]):
            return False
    return True


def current_donor(request: dict, filename: str) -> bool:
    """A cross-generation picture donor awaits a fresh audio owner seal before review."""
    from studio.native_stage_evidence import read_stage
    file = Path(filename)
    phase = file.name.removesuffix('-stage.json')
    record, _pins = read_stage(file, bound_json(file)['inputs'], phase)
    receipt = record['artifacts']['receipt']
    value = bound_json(Path(receipt['path']), receipt['sha256'])
    return value['planIdentity'] == request['revision']['identity']


def require_early_coverage(document: dict, expected: list[dict]) -> None:
    """Every adapter-selected preview interval must carry explicit playback and listening observations."""
    observed = document['review']['observations']
    require(len(observed) == len(expected) and all(row in observed for row in expected),
            'early section review omits required moving-preview or audio coverage')
