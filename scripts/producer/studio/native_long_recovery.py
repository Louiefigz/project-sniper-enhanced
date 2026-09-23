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
    pipeline.supervise('picture', pipeline.worker('picture'), 'picture.mp4', PICTURE_STATUS)
    seal_stage(StageEvidence('picture', Path(request['project']), root, root / 'export-request.json',
        root / 'picture.render.json', request['pins'], {'picture': root / 'picture.mp4'}, PICTURE_STATUS))
    _record, pins = read_stage(root / 'picture-stage.json', request['pins'], 'picture')
    pipeline.evidence.update(pins)


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
