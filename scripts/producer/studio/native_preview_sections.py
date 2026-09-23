"""Independently supervised preview pictures and audio packages with reusable seals."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from cut_preview_io import bound_json, write_new
from studio.native_runtime import digest
from studio.native_review_regions import region_packet, preview_windows
from studio.native_preview_history import prior_preview
from studio.native_stage_evidence import StageEvidence, seal_stage, read_stage, require

STATUS = 'native-preview-section-complete'


def section_phase(phase: str) -> tuple[str, int] | None:
    """Close section names to bounded nonnegative canonical indexes."""
    match = re.fullmatch(r'preview-(picture|package)-(0|[1-9][0-9]{0,2})', phase)
    if not match or int(match[2]) >= 768:
        return None
    return match[1], int(match[2])


def section_output(phase: str) -> str:
    """Use one immutable, owner-bound output receipt per section."""
    require(section_phase(phase) is not None, 'Invalid preview section phase')
    return f'{phase}.json'


def section_windows(request: dict) -> tuple[dict, list[dict]]:
    """Derive the current exact preview schedule through the existing region planner."""
    packet = region_packet(request)
    prior = prior_preview(Path(request['previewFrom']), request['project']) if request.get('previewFrom') else None
    windows = preview_windows(packet, prior['packet'] if prior else None)
    require(len(windows) <= 768, 'Preview schedule exceeds section bound')
    return packet, windows


def execute_section(request: dict, plan: dict, phase: str) -> dict:
    """Render one picture or package it; the common owner qualifies cleanup afterward."""
    from studio.native_motion_previews import prepare_audio, finish_window
    selected = section_phase(phase)
    require(selected is not None, 'Invalid preview section')
    kind, index = selected
    packet, windows = section_windows(request)
    require(index < len(windows), 'Preview section is outside the current schedule')
    root = Path(request['output'])
    if kind == 'picture':
        write_new(root / f'{phase}-input.json', {'window': windows[index]})
        command = [request['tools']['node'], str(Path(__file__).with_name('native_motion_previews.mjs')),
                   str(root / 'export-request.json'), str(index)]
        subprocess.run(command, check=True, timeout=request.get('budget', {}).get('sampleSeconds', 600) - 30)
        row = bound_json(root / f'{phase}-picture.json')
    else:
        from studio.native_preview_recovery import current_section
        picture = current_section(request, f'preview-picture-{index}')
        require(picture['packet'] == packet and picture['window'] == windows[index], 'Preview picture inputs changed')
        require(digest(Path(picture['media']['path'])) == picture['media']['sha256'], 'Preview picture changed')
        row = finish_window(request, prepare_audio(request, plan), picture['media'], plan['canvas'])
    result = {'schemaVersion': 1, 'packet': packet, 'window': windows[index], 'media': row, 'phase': phase}
    require(region_packet(request) == packet, 'Inputs changed during preview section')
    write_new(root / section_output(phase), result)
    return result


def seal_section(pipeline: object, phase: str) -> Path:
    """Seal the completed section's exact media using existing owned-stage authority."""
    root, request = pipeline.root, pipeline.request
    file = root / section_output(phase)
    value = bound_json(file)
    spec = StageEvidence(phase, Path(request['project']), root, root / 'export-request.json',
                         root / f'{phase}.render.json', request['pins'],
                         {'receipt': file, 'media': Path(value['media']['path'])}, STATUS)
    seal_stage(spec)
    seal = root / f'{phase}-stage.json'
    _record, pins = read_stage(seal, request['pins'], phase)
    pipeline.evidence.update(pins)
    return seal


def prepare_sections(pipeline: object) -> None:
    """Release resources, seal each window and re-admit capacity before its successor."""
    from studio.native_preview_recovery import restore_section
    _packet, windows = section_windows(pipeline.request)
    phases = [f'preview-{kind}-{index}' for index in range(len(windows)) for kind in ('picture', 'package')]
    for phase in phases:
        if restore_section(pipeline, phase):
            continue
        pipeline.supervise(phase, pipeline.worker(phase), section_output(phase), STATUS)
        seal_section(pipeline, phase)
