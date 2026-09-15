"""Reuse a sealed native media stage without repeating picture or audio work."""
from __future__ import annotations

from pathlib import Path

from cut_preview_io import bound_json
from studio.native_runtime import digest
from studio.native_short_picture_reuse import copy_picture, picture_reuse_pins
from studio.native_stage_evidence import read_stage, require

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


def prepare_reverification(current: dict, receipt: Path) -> dict:
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
    inputs = dict(current['pins'])
    if original.get('audioDonor'):
        file = Path(original['audioDonor'])
        inputs[str(file)] = digest(file)
    if original.get('pictureDonor'):
        inputs.update(picture_reuse_pins(project, Path(original['pictureDonor'])))
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
    return result


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
