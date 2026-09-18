"""Reuse a sealed native media stage without repeating picture or audio work."""
from __future__ import annotations

from pathlib import Path

from cut_preview_io import bound_json
from studio.native_runtime import digest
from studio.native_short_picture_reuse import copy_picture, picture_reuse_pins
from studio.native_stage_evidence import read_stage, require
from studio.native_reference_reuse import bind_reference_map

ARTIFACTS = {'picture', 'review', 'audio', 'media'}


def media_result(record: dict) -> dict:
    """Require the complete audio/color proof bound by the original media owner."""
    artifacts = record['artifacts']
    require(set(artifacts) == ARTIFACTS, 'incomplete native media artifact inventory')
    media = bound_json(Path(artifacts['media']['path']), artifacts['media']['sha256'])
    audio = bound_json(Path(artifacts['audio']['path']), artifacts['audio']['sha256'])
    require(media.get('status') == 'media-complete-awaiting-qc'
            and media.get('sha256') == artifacts['review']['sha256']
            and media.get('output') == artifacts['review']['path']
            and media.get('audioReceipt') == artifacts['audio']['path'],
            'native completed media proof differs from sealed artifacts')
    color = media.get('color', {})
    require(color.get('sha256') == media['sha256'] and color.get('output') == media['output']
            and color.get('aacPacketsIdentical') is True
            and type(color.get('additionalPictureEncodes')) is int
            and color.get('additionalPictureEncodes') == 0
            and type(color.get('additionalAudioEncodes')) is int
            and color.get('additionalAudioEncodes') == 0,
            'native color/payload proof is incomplete')
    require(audio.get('status') == 'audio-qualified'
            and isinstance(media.get('audioQuality'), list)
            and isinstance(audio.get('audioQuality'), list)
            and type(media.get('audioReviewRequired')) is bool
            and type(audio.get('audioReviewRequired')) is bool
            and media.get('audioQuality') == audio.get('audioQuality')
            and media.get('audioReviewRequired') == audio.get('audioReviewRequired'),
            'native completed audio qualification is incomplete')
    return media


def prepare_reverification(current: dict, receipt: Path, attempt: Path | None = None) -> dict:
    """Reconstruct the original route and compare its complete current dependency map."""
    record = bound_json(receipt)
    original = bound_json(Path(record['request']['path']), record['request']['sha256'])
    project, output = Path(current['project']), Path(current['output'])
    donor = Path(record['root'])
    require(output != donor and not output.is_relative_to(donor)
            and not donor.is_relative_to(output), 'verification output must preserve the donor')
    for key in ('project', 'runtime', 'tools'):
        require(original.get(key) == current[key], f'current {key} differs from completed media')
    require(original.get('captureMode') in {'sdk-streaming', 'cached-native-batches'},
            'unsupported completed render route')
    mapping = original.get('referenceMap')
    if current.get('adapter') != 'native-long':
        current = bind_reference_map(current, Path(mapping) if mapping else None)
    inputs = dict(current['pins'])
    if original.get('audioDonor'):
        file = Path(original['audioDonor'])
        inputs[str(file)] = digest(file)
        if current.get('adapter') == 'native-long':
            for name in ('program-master.wav', 'candidate.mp4'):
                artifact = file.parent / name
                inputs[str(artifact)] = digest(artifact)
    if original.get('preparedMaster'):
        file = Path(original['preparedMaster'])
        inputs[str(file)] = digest(file)
        master = file.parent / 'program-master.wav'
        inputs[str(master)] = digest(master)
    if original.get('pictureDonor'):
        inputs.update(picture_reuse_pins(project, Path(original['pictureDonor'])))
    require(all(record['inputs'].get(key) == sha for key, sha in inputs.items()),
            'completed media dependencies differ from current inputs')
    inputs = dict(record['inputs'])
    record, evidence = read_stage(receipt, inputs, 'render')
    media_result(record)
    result = {**original, 'output': str(output), 'verifyStage': str(receipt),
              'renderResult': record['artifacts']['media']['path'],
              'renderInputs': inputs, 'pins': {**inputs, **evidence}}
    if result['captureMode'] == 'cached-native-batches':
        # Preserve the batch route's existing forward-proof admission and source frames.
        picture_donor = Path(original.get('pictureDonor') or donor)
        result['pins'].update(picture_reuse_pins(project, picture_donor))
        result['pictureDonor'] = str(picture_donor)
    from studio.native_short_capture_resume import prepare_capture_reuse
    return prepare_capture_reuse(result, receipt, attempt or receipt.parent)


def render_stage_for_attempt(attempt: Path) -> Path:
    """Resolve one explicitly selected attempt without searching arbitrary siblings."""
    from cut_preview_io import real_directory
    real_directory(attempt)
    request = bound_json(attempt / 'export-request.json')
    require(request.get('output') == str(attempt), 'resume request belongs to another attempt')
    return Path(request['verifyStage']) if request.get('verifyStage') else attempt / 'render-stage.json'


def copy_completed_media(request: dict) -> tuple[dict, dict[str, str]]:
    """Copy only the final bytes into a fresh attempt; original proof stays immutable."""
    receipt = Path(request['verifyStage'])
    record, pins = read_stage(receipt, request['renderInputs'], 'render')
    media_result(record)
    require(all(request['pins'].get(key) == value for key, value in pins.items()),
            'completed media evidence was not pinned before copying')
    review = record['artifacts']['review']
    copy_picture(Path(review['path']), Path(request['output']) / 'review.mp4', review['sha256'])
    read_stage(receipt, request['renderInputs'], 'render')
    return record, pins


def prepared_audio_reuse(original: dict, attempt: Path) -> tuple[dict, dict]:
    """Preserve either qualified AAC or checked float audio, never a failed preparation."""
    prepared = attempt / 'audio-preparation/receipt.json'
    audio = bound_json(prepared)
    if original.get('audioDonor') and audio.get('status') == 'audio-donor-checked-awaiting-picture':
        donor = Path(original['audioDonor'])
        require(audio.get('donorReceipt') == str(donor)
                and digest(donor) == audio.get('donorReceiptSha256')
                and digest(donor.parent / 'program-master.wav') == audio.get('masterSha256'),
                'picture recovery checked audio donor changed')
        return {'preparedMaster': None, 'audioDonor': str(donor)}, {str(prepared): digest(prepared)}
    require(audio.get('status') == 'float-master-checked-awaiting-aac', 'picture recovery needs its checked audio master')
    master = prepared.parent / 'program-master.wav'
    require(digest(master) == audio.get('masterSha256'), 'picture recovery audio master changed')
    return {'preparedMaster': str(prepared), 'audioDonor': None}, {
        str(prepared): digest(prepared), str(master): digest(master)}
