"""Select exact completed work from neighboring attempts, then use shared seal readers."""
from __future__ import annotations

from pathlib import Path

from cut_preview_io import bound_json
from studio.native_long_recovery import prepare_picture_recovery, prepare_render_recovery, picture_audio_reuse
from studio.native_stage_evidence import require
from studio.native_export_history import candidate_attempts


def resume_request(current: dict, attempt: Path) -> dict:
    """Delegate proof validation to the existing picture/media recovery boundaries."""
    original = bound_json(attempt / 'export-request.json')
    if (attempt / 'render-stage.json').exists() or original.get('verifyStage'):
        return prepare_render_recovery(current, attempt)
    return prepare_picture_recovery(current, attempt)


def matching_attempt(current: dict, attempt: Path) -> tuple[int, str] | None:
    """Only finished invocations with exact current inputs may be automatic donors."""
    file, delivery_file = attempt / 'export-request.json', attempt / 'delivery.json'
    if not file.is_file():
        return None
    original = bound_json(file)
    if original.get('adapter') != 'native-long' or original.get('project') != current['project']:
        return None
    require(original.get('output') == str(attempt), 'Recovery attempt has moved; select a preserved original explicitly')
    inputs = original.get('renderInputs', original.get('pictureInputs', original['pins']))
    if any(inputs.get(file) != sha for file, sha in current['pins'].items()):
        return None
    if any(original.get(key) != current.get(key) for key in ('runtime', 'tools', 'audioProfile', 'cache')):
        return None
    require(delivery_file.is_file(), 'Compatible attempt is active or interrupted; reconcile its owner before starting again')
    delivery = bound_json(delivery_file)
    if original.get('previewOnly') and delivery.get('status') == 'native-motion-previews-complete':
        return None  # Preview discovery owns these; they have no final-media owner.
    require(delivery.get('status') in {'failed', 'native-long-checked-for-review'}
            and isinstance(delivery.get('completedAt'), str), 'Compatible recovery attempt has no terminal delivery state')
    if (attempt / 'render-stage.json').exists() or original.get('verifyStage'):
        return 3, delivery['completedAt']
    if (attempt / 'picture-stage.json').exists() or original.get('pictureStage'):
        return 2, delivery['completedAt']
    audio = attempt / 'audio-preparation/receipt.json'
    if audio.is_file() and bound_json(audio).get('status') in {
            'float-master-checked-awaiting-aac', 'audio-donor-checked-awaiting-picture'}:
        return 1, delivery['completedAt']
    return None


def recover_automatically(current: dict) -> dict:
    """Bound discovery to sibling attempt folders; never suppress invalid matching seals."""
    parent = Path(current['output']).parent
    candidates = []
    for attempt in candidate_attempts(current):
        rank = matching_attempt(current, attempt)
        if rank:
            candidates.append((*rank, str(attempt)))
    if not candidates:
        return {**current, 'recoverySelection': {'mode': 'fresh', 'searchRoot': str(parent)}}
    rank, _completed, filename = max(candidates)
    attempt = Path(filename)
    if rank == 1:
        original = bound_json(attempt / 'export-request.json')
        fields, pins = picture_audio_reuse(original, attempt)
        result = {**current, **fields, 'pins': {**original['pins'], **current['pins'], **pins}}
    else:
        result = resume_request(current, attempt)
    return {**result, 'recoverySelection': {'mode': 'automatic', 'attempt': filename,
        'reused': {1: 'audio', 2: 'picture-and-audio', 3: 'completed-media'}[rank]}}
