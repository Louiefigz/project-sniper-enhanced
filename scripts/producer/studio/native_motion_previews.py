"""Owned continuous preview windows with excerpts of the actual whole-program master."""
from __future__ import annotations

import subprocess
from pathlib import Path

from cut_preview_io import bound_json, write_new
from guided_opening_picture import observe_picture
from guided_opening_mux import mux_ranges
from studio.native_review_regions import region_packet, preview_windows
from studio.native_preview_history import prior_preview, preview_chain, discover_preview
from studio.native_runtime import digest
from studio.native_short_dialogue import clock
from studio.native_stage_evidence import require

STATUS = 'native-motion-previews-complete'


def preview_options(parser: object) -> None:
    """Expose preview-only preparation without implying final or editorial approval."""
    parser.add_argument('--preview-reviews', type=Path, help='Independent region reviews of completed moving previews; required before full rendering')
    parser.add_argument('--preview-only', action='store_true', help='Render continuous review windows and stop before full picture')
    parser.add_argument('--preview-from', type=Path, help='Reuse unchanged regions from a completed motion-previews.json')


def bind_preview_options(request: dict, args: object) -> dict:
    """Pin explicit prior preview evidence before the immutable export request is written."""
    only, prior = getattr(args, 'preview_only', False), getattr(args, 'preview_from', None)
    reviews = getattr(args, 'preview_reviews', None)
    if (only or prior or reviews) and (getattr(args, 'resume_from', None) or getattr(args, 'verify_from', None)):
        raise ValueError('Preview options cannot change a resumed final-media request')
    request['previewOnly'] = only or (not reviews and not request.get('verifyStage'))
    if reviews:
        request['previewReviews'] = str(reviews.resolve(strict=True))
        from studio.native_motion_review import review_input_pins
        request['pins'].update(review_input_pins(Path(request['previewReviews']), request['project']))
    if not prior and not request.get('verifyStage'):
        prior = discover_preview(request)
    if prior:
        file = prior.resolve(strict=True)
        chain = preview_chain(file, request['project'])
        request['previewFrom'] = str(file)
        for source, value in chain:
            files = [source, source.parent / 'preview.render.json', source.parent / 'export-request.json']
            request['pins'].update({str(item): digest(item) for item in files})
            request['pins'].update({row['path']: row['sha256'] for row in value['clips']})
    from studio.native_preview_recovery import bind_section_recovery
    return bind_section_recovery(request)


def require_motion_previews(request: dict) -> dict:
    """No direct picture worker may omit the current continuous-preview result."""
    value = bound_json(Path(request['output']) / 'motion-previews.json')
    require(value.get('status') == STATUS and value['packet'] == region_packet(request)
            and value.get('priorPreview') == request.get('previewFrom'), 'Moving previews are absent or stale')
    prior = prior_preview(Path(request['previewFrom']), request['project']) if request.get('previewFrom') else None
    windows = preview_windows(value['packet'], prior['packet'] if prior else None)
    require([row['absoluteFrameRange'] for row in value['clips']] ==
            [[row['startFrame'], row['endFrame']] for row in windows], 'Moving previews omit changed regions')
    for row in value['clips']:
        require(digest(Path(row['path'])) == row['sha256'], 'Moving preview bytes changed')
    from studio.native_motion_review import require_preview_review
    require_preview_review(request, value['packet'])
    return value


def prepare_audio(request: dict, plan: dict) -> dict:
    """Prepare once before preview and retain it for the final delivery phase."""
    root = Path(request['output'])
    if request.get('adapter') == 'native-long':
        from studio.native_long_worker import read_long_audio
        return read_long_audio(request)
    from studio.native_short_delivery import prepare_dialogue
    file = root / 'prepared-audio.json'
    if not file.exists():
        write_new(file, prepare_dialogue(request, plan['canvas'], plan.get('audioFinishing')))
    return bound_json(file)


def audio_excerpt(request: dict, prepared: dict, window: dict, destination: Path) -> dict:
    """Extract exact PCM after whole-program mastering, with no excerpt normalization."""
    master_receipt = Path(prepared['masterReceipt'])
    require(digest(master_receipt) == prepared['masterReceiptSha256'], 'Prepared master receipt changed')
    master = bound_json(master_receipt)
    file = Path(master['output'])
    require(digest(file) == master['masterSha256'], 'Whole-program master changed before preview')
    audio_clock = clock(window['canvas'])
    start, end = (audio_clock.sample_at_frame(window[key]) for key in ('startFrame', 'endFrame'))
    command = [request['tools']['ffmpeg'], '-nostdin', '-v', 'error', '-xerror', '-n', '-i', str(file),
               '-map', '0:a:0', '-af', f'atrim=start_sample={start}:end_sample={end},asetpts=PTS-STARTPTS',
               '-ar', '48000', '-ac', '2', '-c:a', 'pcm_f32le', str(destination)]
    subprocess.run(command, check=True, timeout=90)
    from audio.program_master_excerpt import _pcm_hash
    span = {'startSample': start, 'endSampleExclusive': end}
    observed = _pcm_hash(str(destination), (request['tools']['ffmpeg'], None))
    require(observed == _pcm_hash(str(file), (request['tools']['ffmpeg'], span)), 'Preview PCM differs from the whole master')
    return {'path': str(destination), 'sha256': digest(destination), 'pcmSha256': observed,
            'samples': end - start, 'startSample': start, 'endSampleExclusive': end,
            'startFrame': window['startFrame'], 'endFrameExclusive': window['endFrame']}


def finish_window(request: dict, prepared: dict, row: dict, canvas: dict) -> dict:
    """Reuse exact picture observation and AAC excerpt qualification from the existing range lane."""
    directory = Path(row['path']).parent
    tools = {key: {'path': value} for key, value in request['tools'].items()}
    dimensions = canvas.get('width', 1080), canvas.get('height', 1920)
    picture = observe_picture(Path(row['path']), (canvas['frameRate'], row['frames'], dimensions), tools, native_srgb=True)
    pcm = audio_excerpt(request, prepared, {**row, 'canvas': canvas}, directory / 'audio.wav')
    result = mux_ranges(directory, {'ranges': {'core': picture, 'review': picture}},
                        {'core': pcm, 'review': pcm}, tools)['review']
    return {**result, 'continuousFrames': row['frames'], 'absoluteFrameRange': [row['startFrame'], row['endFrame']]}


def render_previews(request: dict, plan: dict) -> dict:
    """Produce changed-region clips automatically; editorial judgment stays with the agent."""
    root = Path(request['output'])
    packet = region_packet(request)
    prior = prior_preview(Path(request['previewFrom']), request['project']) if request.get('previewFrom') else None
    previous = prior['packet'] if prior else None
    windows = preview_windows(packet, previous)
    write_new(root / 'motion-preview-input.json', {'packet': packet, 'windows': windows})
    clips = []
    for index, window in enumerate(windows):
        from studio.native_preview_recovery import current_section
        value = current_section(request, f'preview-package-{index}')
        require(value['packet'] == packet and value['window'] == window, 'Preview package is stale')
        row = value['media']
        require(digest(Path(row['path'])) == row['sha256'], 'Preview package media changed')
        clips.append(row)
    require(region_packet(request) == packet, 'Native inputs changed during moving previews')
    old = {row['id']: row['hash'] for row in (previous or {}).get('units', [])}
    changed = [row['id'] for row in packet['units'] if old.get(row['id']) != row['hash']]
    result = {'schemaVersion': 1, 'status': STATUS, 'packet': packet, 'clips': clips,
              'changedUnits': changed, 'reusedUnits': [row['id'] for row in packet['units'] if row['id'] not in changed],
              'priorPreview': request.get('previewFrom'), 'pictureFramesRendered': sum(row['endFrame'] - row['startFrame'] for index, row in enumerate(windows)
                  if f'preview-picture-{index}' not in request.get('previewSectionDonors', {})),
              'pictureFramesReused': sum(row['endFrame'] - row['startFrame'] for index, row in enumerate(windows)
                  if f'preview-picture-{index}' in request.get('previewSectionDonors', {})),
              'fullProgramMasterUsed': True, 'editorialReview': 'pending', 'finalQcRequired': True}
    write_new(root / 'motion-previews.json', result)
    return result


def bound_json_array(file: Path) -> list[dict]:
    """Read the bounded child result without accepting a non-array protocol."""
    import json
    from cut_preview_io import read_bytes
    value = json.loads(read_bytes(file, 16 * 1024 ** 2))
    if not isinstance(value, list) or len(value) > 768:
        raise ValueError('Invalid motion preview picture inventory')
    return value
