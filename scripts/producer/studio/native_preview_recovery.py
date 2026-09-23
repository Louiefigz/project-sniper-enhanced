"""Discover exact-input preview section seals; never reuse failed or unsealed media."""
from __future__ import annotations

from pathlib import Path

from cut_preview_io import bound_json, write_new
from studio.native_export_history import candidate_attempts
from studio.native_runtime import digest
from studio.native_short_picture_reuse import copy_picture
from studio.native_stage_evidence import read_stage, require
from studio.native_preview_sections import section_windows, section_phase, section_output, STATUS


def read_section(file: Path, expected: tuple) -> tuple[dict, dict]:
    """Revalidate source, runtime, media and verified original cleanup before copying."""
    phase, packet, window = expected
    sealed = bound_json(file)
    record, pins = read_stage(file, sealed['inputs'], phase)
    require(record['successStatus'] == STATUS, 'Preview section success status differs')
    receipt = record['artifacts']['receipt']
    value = bound_json(Path(receipt['path']), receipt['sha256'])
    require(value.get('schemaVersion') == 1 and value.get('phase') == phase
            and value.get('packet') == packet and value.get('window') == window,
            'Preview checkpoint inputs or window differ')
    media = record['artifacts']['media']
    require(value['media']['path'] == media['path'] and value['media']['sha256'] == media['sha256'],
            'Preview checkpoint media differs from its sealed artifact')
    return value, pins


def bind_section_recovery(request: dict) -> dict:
    """Pin completed sections before the new immutable export request is published."""
    if request.get('verifyStage'):
        return request
    packet, windows = section_windows(request)
    donors, pins = {}, {}
    for attempt in candidate_attempts(request):
        discover_sections(attempt, (packet, windows), donors, pins)
    request['previewSectionDonors'] = donors
    request['pins'].update(pins)
    return request


def discover_sections(attempt: Path, schedule: tuple, donors: dict, pins: dict) -> None:
    """Ignore incompatible old work; matching seals must pass all integrity checks."""
    packet, windows = schedule
    for file in sorted(attempt.glob('preview-*-stage.json')):
        phase = file.name.removesuffix('-stage.json')
        selected = section_phase(phase)
        if selected is None or selected[1] >= len(windows):
            continue
        record = bound_json(file)
        receipt = record.get('artifacts', {}).get('receipt', {})
        value = bound_json(Path(receipt['path']), receipt['sha256'])
        if value.get('packet') != packet or value.get('window') != windows[selected[1]]:
            continue
        _value, retained = read_section(file, (phase, packet, windows[selected[1]]))
        donors[phase] = str(file)
        pins.update(retained)


def restore_section(pipeline: object, phase: str) -> bool:
    """Copy immutable media into the new attempt; never write into the donor directory."""
    request = pipeline.request
    source = request.get('previewSectionDonors', {}).get(phase)
    if source is None:
        return False
    packet, windows = section_windows(request)
    value, pins = read_section(Path(source), (phase, packet, windows[section_phase(phase)[1]]))
    require(all(request['pins'].get(file) == sha for file, sha in pins.items()), 'Unpinned preview donor')
    destination = pipeline.root / f'{phase}-restored'
    destination.mkdir()
    media = value['media']
    target = destination / Path(media['path']).name
    copy_picture(Path(media['path']), target, media['sha256'])
    result = {**value, 'media': {**media, 'path': str(target)}}
    file = pipeline.root / section_output(phase)
    write_new(file, result)
    pipeline.evidence.update({**pins, str(file): digest(file), str(target): media['sha256']})
    pipeline.stages.append({'phase': phase + '-reused', 'receipt': source,
                            'sha256': digest(Path(source)), 'status': STATUS, 'elapsedSeconds': 0})
    return True


def current_section(request: dict, phase: str) -> dict:
    """Workers independently require a sealed section or an exact pinned donor copy."""
    packet, windows = section_windows(request)
    selected = section_phase(phase)
    require(selected is not None and selected[1] < len(windows), 'Invalid current section')
    root = Path(request['output'])
    donor = request.get('previewSectionDonors', {}).get(phase)
    seal = Path(donor) if donor else root / f'{phase}-stage.json'
    original, pins = read_section(seal, (phase, packet, windows[selected[1]]))
    if not donor:
        return original
    require(all(request['pins'].get(file) == sha for file, sha in pins.items()), 'Unpinned section donor')
    value = bound_json(root / section_output(phase))
    media = Path(value['media']['path'])
    require(media.is_relative_to(root) and media.resolve(strict=True) == media
            and digest(media) == original['media']['sha256'], 'Restored section media changed or escaped')
    expected = {**original, 'media': {**original['media'], 'path': str(media)}}
    require(value == expected, 'Restored section metadata changed')
    return value
