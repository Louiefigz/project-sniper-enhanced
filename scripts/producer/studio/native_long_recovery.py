"""Seal expensive picture separately so failed audio or final QC never forces recapture."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from cut_preview_io import bound_json
from studio.native_runtime import digest
from studio.native_short_resume import prepared_audio_reuse as picture_audio_reuse
from studio.native_short_picture_reuse import copy_picture
from studio.native_stage_evidence import StageEvidence, read_stage, require, seal_stage

if TYPE_CHECKING:
    from studio.native_short_pipeline import NativeShortPipeline

PICTURE_STATUS = 'native-long-picture-awaiting-audio-and-qc'


def ensure_picture(pipeline: NativeShortPipeline) -> None:
    """Retain original ownership for fresh picture and explicit immutable reuse."""
    request, root = pipeline.request, pipeline.root
    if request.get('pictureStage'):
        record, pins = read_stage(Path(request['pictureStage']), request['pictureInputs'], 'picture')
        require(record['successStatus'] == PICTURE_STATUS, 'long picture status differs')
        picture = record['artifacts']['picture']
        copy_picture(Path(picture['path']), root / 'picture.mp4', picture['sha256'])
        pipeline.evidence.update(pins)
        pipeline.evidence[str(root / 'picture.mp4')] = picture['sha256']
        return
    if request.get('revision', {}).get('mode') == 'initial-long':
        from studio.native_segments.owners import run_revision_windows
        from studio.native_segments.reviews import assembly_snapshot
        from studio.native_motion_previews import require_motion_previews
        require_motion_previews(request)
        run_revision_windows(pipeline)
        assembly_snapshot(request)
    pipeline.supervise('picture', pipeline.worker('picture'), 'picture.mp4', PICTURE_STATUS)
    artifacts = {'picture': root / 'picture.mp4'}
    if request.get('revision', {}).get('mode') == 'initial-long':
        artifacts['sections'] = root / 'revision-picture.json'
    seal_stage(StageEvidence('picture', Path(request['project']), root, root / 'export-request.json',
        root / 'picture.render.json', request['pins'], artifacts, PICTURE_STATUS))
    _record, pins = read_stage(root / 'picture-stage.json', request['pins'], 'picture')
    pipeline.evidence.update(pins)


def prepare_section_recovery(current: dict, attempt: Path) -> dict:
    """Preserve admitted preview/audio policy for an exact registered initial-section resume."""
    from studio.native_export_history import known_attempts
    from studio.native_stage_evidence import verify_pins
    require(attempt in known_attempts(current), 'section resume requires a registered original attempt')
    original = bound_json(attempt / 'export-request.json')
    require(original.get('adapter') == 'native-long'
            and original.get('revision', {}).get('mode') == 'initial-long',
            'section resume requires the original Long section plan')
    for key in ('project', 'runtime', 'tools'):
        require(current[key] == original[key], f'section recovery changed {key}')
    require(all(original['pins'].get(key) == sha for key, sha in current['pins'].items()),
            'section recovery changed current project or implementation inputs')
    verify_pins(original['pins'])
    retained = section_recovery_plan(current, original)
    fields = ('audioProfile', 'cache', 'preparedMaster', 'audioDonor', 'previewOnly',
              'previewReviews', 'previewFrom', 'sectionProduction', 'sectionScope',
              'sectionIntegrations', 'sectionPreviewWindows', 'sectionChunks')
    inherited = {key: original[key] for key in fields if key in original}
    result = {**current, **inherited, **retained, 'pins': {**original['pins'], **current['pins']}}
    from studio.production.section_recovery import retain_section_reviews
    return retain_section_reviews(result, original)


def section_recovery_plan(current: dict, original: dict) -> dict:
    """Retain a repaired generation only after its original compatibility relation still holds."""
    if not original.get('sectionRepair'):
        require(original['revision']['identity'] == current['revision']['identity'],
                'section resume changed its shared plan; begin a newly reviewed plan')
        return {'revision': dict(original['revision'])} if original.get('sectionIntegrations') else {}
    from studio.native_segments.compatibility import validate_repair
    validate_repair(original)
    require(current.get('sectionImplementationPins') == original.get('sectionImplementationPins'),
            'section resume changed its implementation partition')
    return {'revision': dict(original['revision']), 'sectionRepair': dict(original['sectionRepair'])}


def prepare_picture_recovery(current: dict, attempt: Path) -> dict:
    """Resume only an exactly matching completed picture; altered edits require a new picture."""
    original = bound_json(attempt / 'export-request.json')
    require(original.get('adapter') == 'native-long', 'expected native long picture attempt')
    for key in ('project', 'runtime', 'tools'):
        require(current[key] == original[key], f'picture recovery changed {key}')
    inputs = dict(current['pins'])
    for field, names in (('preparedMaster', ('program-master.wav',)),
                         ('audioDonor', ('program-master.wav', 'candidate.mp4'))):
        if original.get(field):
            receipt = Path(original[field])
            inputs[str(receipt)] = digest(receipt)
            inputs.update({str(receipt.parent / name): digest(receipt.parent / name) for name in names})
    seal = Path(original.get('pictureStage') or attempt / 'picture-stage.json')
    original_inputs = original.get('pictureInputs', original['pins'])
    require(all(original_inputs.get(key) == value for key, value in current['pins'].items()),
            'picture recovery input changed')
    record, pins = read_stage(seal, original_inputs, 'picture')
    require(record['successStatus'] == PICTURE_STATUS and set(record['artifacts']) == {'picture'},
            'picture recovery has no completed picture')
    audio_fields, audio_pins = picture_audio_reuse(original, attempt)
    return {**original, 'output': current['output'], 'pictureStage': str(seal),
        'pictureInputs': original_inputs, **audio_fields,
        'pins': {**original_inputs, **inputs, **pins, **audio_pins}}


def prepare_render_recovery(current: dict, attempt: Path) -> dict:
    """Read the exact complete long closure, including any earlier picture/audio reuse."""
    from studio.native_short_capture_resume import prepare_capture_reuse
    from studio.native_short_resume import media_result, render_stage_for_attempt
    receipt = render_stage_for_attempt(attempt)
    sealed = bound_json(receipt)
    original = bound_json(Path(sealed['request']['path']), sealed['request']['sha256'])
    require(original.get('adapter') == 'native-long', 'expected a sealed long export')
    for key in ('project', 'runtime', 'tools'):
        require(current[key] == original[key], f'long recovery changed {key}')
    inputs = sealed['inputs']
    require(all(inputs.get(key) == value for key, value in current['pins'].items()),
            'long recovery changed a current input or implementation')
    record, pins = read_stage(receipt, inputs, 'render')
    media_result(record)
    result = {**original, 'output': current['output'], 'verifyStage': str(receipt),
        'renderInputs': inputs, 'renderResult': record['artifacts']['media']['path'],
        'pins': {**inputs, **pins}}
    return prepare_capture_reuse(result, receipt, attempt)
