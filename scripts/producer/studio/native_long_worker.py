"""Long export adapter: shared audio, SDK picture, exact seams and shared final QC."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from dataclasses import replace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audio.mastering_profile import resolve_mastering_profile
from audio.native_audio_donor import prepare_audio_donor
from audio.native_master_preparation import NativeMasterPreparation, prepare_native_master
from cut_preview_io import bound_json, write_new
from stage_timing import stage_span
from studio.native_long_contract import read_long_plan, long_audio_canvas
from studio.native_preflight import preflight
from studio.native_picture_references import check_samples
from studio.native_short_delivery import finish_dialogue, native_srgb_delivery, clock, dialogue_review_sections
from studio.native_short_worker import render_command, verify_files, verify_media
from studio.native_stage_evidence import read_stage
from studio.native_runtime import digest


def capture(request: dict, plan: dict) -> None:
    """Put inexpensive failures and full-context seams before the full picture pass."""
    root = Path(request['output'])
    with stage_span(str(root), 'native_static_preflight'):
        if preflight(Path(request['project']), root / 'static')['status'] != 'static-checks-pass':
            raise RuntimeError('Long static preflight failed')
    if not request.get('verifyStage'):
        with stage_span(str(root), 'native_dialogue_preparation'):
            prepare_long_audio(request, plan)
    print('SNIPER_PROGRESS preparation 1', flush=True)
    command = [request['tools']['node'], str(Path(__file__).with_name('native_long_capture.mjs')),
               str(root / 'export-request.json')]
    with stage_span(str(root), 'native_full_context_seam_samples'):
        subprocess.run(command, check=True, timeout=request['budget']['sampleSeconds'] - 30)
        check_samples(request, plan)
    print('SNIPER_PROGRESS preparation 2', flush=True)


def render(request: dict, plan: dict) -> dict:
    """Use the unchanged full-quality SDK command only after early checks passed."""
    root = Path(request['output'])
    if bound_json(root / 'sample-qc/result.json').get('passed') is not True:
        raise RuntimeError('Long render requires encoded seam samples')
    prepared = read_long_audio(request)
    seal = Path(request.get('pictureStage') or root / 'picture-stage.json')
    record, _pins = read_stage(seal, request.get('pictureInputs', request['pins']), 'picture')
    if digest(root / 'picture.mp4') != record['artifacts']['picture']['sha256']:
        raise RuntimeError('Sealed long picture changed before final audio')
    verify_files(request)
    with stage_span(str(root), 'native_dialogue_delivery'):
        audio = finish_dialogue(request, long_audio_canvas(plan), None, prepared)
    print('SNIPER_PROGRESS delivery 1', flush=True)
    with stage_span(str(root), 'native_color_metadata'):
        color = native_srgb_delivery(root, audio)
    return {'status': 'media-complete-awaiting-qc', 'output': color['output'], 'sha256': color['sha256'],
            'audioReceipt': str(root / 'audio/receipt.json'), 'audioReviewRequired': audio['audioReviewRequired'],
            'audioQuality': audio['audioQuality'], 'color': color, 'humanApproved': False,
            'additionalPictureEncodes': 0 if request.get('pictureStage') else 1,
            'sourceCurrent': True, 'providerCalls': 0}


def execute(request: dict, phase: str) -> None:
    """Retain the shared supervisor, immutable request and final verification authority."""
    os.environ['SNIPER_NODE_PATH'] = request['tools']['node']
    os.environ['FFMPEG_PROCESS_TIMEOUT_MS'] = str(source_process_timeout_ms(request, phase))
    plan = read_long_plan(Path(request['project']))
    verify_files(request)
    if phase == 'capture':
        capture(request, plan)
    elif phase.startswith(('preview-picture-', 'preview-package-')):
        from studio.native_preview_sections import execute_section
        execute_section(request, plan, phase)
    elif phase == 'preview':
        from studio.native_motion_previews import render_previews
        render_previews(request, plan)
    elif phase == 'picture':
        from studio.native_motion_previews import require_motion_previews
        require_motion_previews(request)
        if bound_json(Path(request['output']) / 'sample-qc/result.json').get('passed') is not True:
            raise RuntimeError('Long picture requires passed encoded seam samples')
        with stage_span(request['output'], 'native_picture_render'):
            subprocess.run([*render_command(request, plan['canvas']), '--sdr'], check=True,
                           timeout=request['budget']['pictureSeconds'])
    elif phase == 'render':
        write_new(Path(request['output']) / 'render-result.json', render(request, plan))
    elif phase == 'verify':
        write_new(Path(request['output']) / 'checks.json', verify_media(request, plan))
    else:
        raise ValueError('Unknown long export phase')
    verify_files(request)
    print(f'SNIPER_PROGRESS {phase} 1', flush=True)


def source_process_timeout_ms(request: dict, phase: str) -> int:
    """Do not leave long source extraction behind the SDK's five-minute default."""
    budget = request['budget']
    seconds = budget['pictureSeconds']
    if phase == 'capture':
        seconds = min(seconds, budget['sampleSeconds'] - 30)
    if seconds <= 0:
        raise ValueError('Long source extraction requires a positive owned time budget')
    return int(seconds * 1000)


def prepare_long_audio(request: dict, plan: dict) -> dict:
    """Admit an exact full-program premaster before any source-frame extraction."""
    root = Path(request['output'])
    reference = Path(request['project']) / plan['audio']['file']
    canvas = long_audio_canvas(plan)
    master = NativeMasterPreparation(reference, digest(reference),
        clock(canvas).sample_at_frame(canvas['totalFrames']), root / 'audio-preparation',
        resolve_mastering_profile(request['audioProfile']), dialogue_review_sections(canvas))
    tools = request['tools']['ffmpeg'], request['tools']['ffprobe']
    prior = request.get('preparedMaster')
    if prior:
        master = replace(master, prepared_master=(Path(prior), request['pins'][prior]))
    donor = request.get('audioDonor')
    receipt, sha = prepare_audio_donor(master, Path(donor), tools) if donor else prepare_native_master(master, tools)
    result = {'kind': 'donor' if donor else 'master', 'reference': str(reference),
              'referenceSha256': master.premaster_sha256, 'masterReceipt': str(receipt),
              'masterReceiptSha256': sha, 'audioFinishing': None}
    write_new(root / 'prepared-audio.json', result)
    return result


def read_long_audio(request: dict) -> dict:
    """Require the exact early preparation instead of repeating it after picture."""
    result = bound_json(Path(request['output']) / 'prepared-audio.json')
    if digest(Path(result['reference'])) != result['referenceSha256'] \
            or digest(Path(result['masterReceipt'])) != result['masterReceiptSha256']:
        raise RuntimeError('Prepared long audio changed before picture delivery')
    return result


if __name__ == '__main__':
    from studio.native_export import require_owned_worker
    request = bound_json(Path(sys.argv[1]))
    require_owned_worker(request)
    execute(request, sys.argv[2])
