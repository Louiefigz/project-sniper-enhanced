"""Run each native export stage inside the existing bounded process owner."""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stage_timing import stage_span
from cut_preview_io import bound_json, write_new
from studio.native_preflight import preflight
from studio.native_runtime import digest
from studio.native_short_delivery import finish_dialogue, native_srgb_delivery, qualify_picture, run


def render_command(request: dict, canvas: dict) -> list[str]:
    """Use the qualified full-quality single-worker file-backed native route."""
    mode = request.get('captureMode', 'sdk-streaming')
    if mode == 'cached-native-batches':
        return [request['tools']['node'], str(Path(__file__).with_name('native_short_batched_render.mjs')),
                str(Path(request['output']) / 'export-request.json')]
    if mode != 'sdk-streaming':
        raise ValueError('Unsupported native capture mode')
    return [request['tools']['node'], str(Path(request['runtime']) / 'dist/cli.js'),
            'render', request['project'], '--fps', canvas['frameRate'], '--quality', 'high',
            '--crf', '15', '--workers', '1', '--low-memory-mode', '--no-browser-gpu',
            '--video-frame-format', 'png', '--no-best-effort', '--frames-cache-dir', request['cache'],
            '--output', str(Path(request['output']) / 'picture.mp4')]


def verify_files(request: dict) -> None:
    """Guard the executable package, SDK, inputs and tool identity between stages."""
    for file, expected in request['pins'].items():
        if digest(Path(file)) != expected:
            raise RuntimeError(f'Native export input changed: {file}')


def capture_checks(request: dict, request_file: Path) -> None:
    """Partition existing batch QC sessions under the same owner and child deadlines."""
    legacy = [request['tools']['node'], str(Path(__file__).with_name('native_short_capture.mjs')),
              str(request_file)]
    if request.get('captureMode') != 'cached-native-batches':
        run(legacy)
        return
    capture = Path(__file__).with_name('native_short_qc_phase.mjs')
    command = [request['tools']['node'], str(capture), str(request_file)]
    verify_files(request)
    planned = json.loads(run([*command, 'plan']).splitlines()[-1])
    if planned.get('status') == 'native-qc-phases-ineligible':
        if planned.get('reason') not in ('single-frame-session', 'forward-evidence-unavailable'):
            raise RuntimeError('Native QC phase planner returned an invalid legacy reason')
        verify_files(request)
        run(legacy)
        return
    count, expected = planned.get('chunkCount'), planned.get('scheduleSha256')
    if planned.get('status') != 'native-qc-phases-planned' or type(count) is not int \
            or not 1 <= count <= 128 or not isinstance(expected, str) \
            or re.fullmatch('[a-f0-9]{64}', expected) is None:
        raise RuntimeError('Native QC phase planner returned an invalid bounded schedule')
    root = Path(request['output']) / 'native-qc-phases'
    evidence = {root / 'schedule.json': expected, **compiler_evidence(planned, root)}
    authority = ['--schedule-sha256', expected]
    for index in range(count):
        verify_qc_files(request, evidence)
        with stage_span(request['output'], f'native_qc_chunk_{index}'):
            result = json.loads(run([*command, 'chunk', str(index), *authority]).splitlines()[-1])
        if result.get('status') != 'native-qc-chunk-complete' \
                or type(result.get('index')) is not int or result['index'] != index:
            raise RuntimeError('Native QC chunk did not report successful completion')
        evidence[root / f'chunk-{index:03d}/receipt.json'] = qc_result_hash(result, 'receiptSha256')
    verify_qc_files(request, evidence)
    with stage_span(request['output'], 'native_qc_finish'):
        result = json.loads(run([*command, 'finish', *authority]).splitlines()[-1])
    if result.get('status') != 'native-references-and-seek-states-pass':
        raise RuntimeError('Native QC phase aggregation did not pass')
    evidence[Path(request['output']) / 'native-frames.json'] = qc_result_hash(result, 'sha256')
    verify_qc_files(request, evidence)


def qc_result_hash(result: dict, key: str) -> str:
    """Require a child-returned digest before accepting its on-disk evidence."""
    value = result.get(key)
    if not isinstance(value, str) or re.fullmatch('[a-f0-9]{64}', value) is None:
        raise RuntimeError('Native QC phase returned an invalid receipt digest')
    return value


def compiler_evidence(planned: dict, root: Path) -> dict[Path, str]:
    """Retain the live planner's exact compiler receipt and complete copied file pins."""
    pins, directory = planned.get('compilerPins'), root / 'plan'
    if not isinstance(pins, dict) or not 3 <= len(pins) <= 4096:
        raise RuntimeError('Native QC planner returned invalid compiler evidence')
    required = (directory / 'compiler-result.json', directory / 'compiler-result.bin',
                directory / 'compiled/index.html')
    if any(str(file) not in pins for file in required):
        raise RuntimeError('Native QC compiler evidence omitted its receipt, payload or HTML')
    evidence = {}
    for filename in pins:
        if not isinstance(filename, str):
            raise RuntimeError('Native QC compiler evidence has an invalid path')
        file = Path(filename)
        if not file.is_file() or file.is_symlink() or file.resolve() != file \
                or not file.is_relative_to(directory):
            raise RuntimeError('Native QC compiler evidence escaped the preparation directory')
        evidence[file] = qc_result_hash(pins, filename)
    return evidence


def verify_qc_files(request: dict, evidence: dict[Path, str]) -> None:
    """Bind the schedule and completed children to the live parent's observed digests."""
    verify_files(request)
    for file, expected in evidence.items():
        if digest(file) != expected:
            raise RuntimeError(f'Native QC evidence changed between bounded phases: {file}')


def render_media(request: dict, plan: dict) -> dict:
    """Finish media once; source/render/audio checks do not claim final picture QC."""
    root, project = Path(request['output']), Path(request['project'])
    canvas = plan['canvas']
    verify_files(request)
    with stage_span(str(root), 'native_static_preflight'):
        static = preflight(project, root / 'static')
        if static['status'] != 'static-checks-pass':
            raise RuntimeError('Native static preflight blocked export')
    picture_stage = 'native_picture_reuse' if request.get('pictureDonor') else 'native_picture_render'
    with stage_span(str(root), picture_stage):
        # Stream SDK output into the supervisor log, preserving cache-hit/failure evidence.
        if request.get('pictureDonor'):
            from studio.native_short_picture_reuse import reuse_native_picture
            reuse = reuse_native_picture(request)
            with (root / 'picture-reuse.json').open('x') as handle:
                json.dump(reuse, handle, indent=2)
        else:
            import subprocess
            subprocess.run(render_command(request, canvas), check=True, timeout=480)
    verify_files(request)
    with stage_span(str(root), 'native_dialogue_delivery'):
        audio = finish_dialogue(request, canvas, plan.get('audioFinishing'))
    with stage_span(str(root), 'native_color_metadata'):
        color = native_srgb_delivery(root, audio)
    verify_files(request)
    return {'status': 'media-complete-awaiting-qc', 'output': color['output'],
            'sha256': color['sha256'], 'audioReceipt': str(root / 'audio/receipt.json'),
            'audioReviewRequired': audio['audioReviewRequired'], 'audioQuality': audio['audioQuality'],
            'color': color, 'humanApproved': False,
            'additionalPictureEncodes': 0 if request.get('pictureDonor') else 1,
            'sourceCurrent': True, 'providerCalls': 0}


def verify_media(request: dict, plan: dict) -> dict:
    """Qualify the same encoded bytes using the existing native/encoded checks."""
    root = Path(request['output'])
    media = bound_json(Path(request.get('renderResult', root / 'render-result.json')))
    if media.get('status') != 'media-complete-awaiting-qc' \
            or digest(root / 'review.mp4') != media.get('sha256'):
        raise RuntimeError('Completed native media changed before verification')
    with stage_span(str(root), 'native_picture_and_full_decode_checks'):
        picture = qualify_picture(root, plan['canvas'])
    verify_files(request)
    return {**media, 'status': 'checks-passed-awaiting-owned-cleanup',
            'output': str(root / 'review.mp4'),
            'pictureFramesChecked': len(picture['comparisons']),
            'fullAudioVideoDecodePassed': True,
            'additionalPictureEncodes': 0 if request.get('renderResult') else media['additionalPictureEncodes']}


def execute(request: dict, request_file: Path, phase: str = 'all') -> dict:
    """Keep legacy callers while exposing independently supervised execution phases."""
    if phase not in {'all', 'render', 'capture', 'verify'}:
        raise ValueError('Unsupported native export phase')
    root = Path(request['output'])
    plan = bound_json(Path(request['project']) / 'SHORT-PROJECT.json')
    verify_files(request)
    if phase in {'all', 'render'}:
        media = render_media(request, plan)
        write_new(root / 'render-result.json', media)
        if phase == 'render':
            return media
    if phase in {'all', 'capture'}:
        with stage_span(str(root), 'native_capture_and_seek_checks'):
            capture_checks(request, request_file)
        verify_files(request)
        if phase == 'capture':
            return {'status': 'native-references-and-seek-states-pass'}
    return verify_media(request, plan)


def main() -> None:
    """The supervisor owns cancellation, resources and final completion authority."""
    request_file = Path(sys.argv[1])
    phase = sys.argv[2] if len(sys.argv) == 3 else 'all'
    if len(sys.argv) not in {2, 3}:
        raise ValueError('Expected request path and optional native export phase')
    request = json.loads(request_file.read_text())
    os.environ['SNIPER_NODE_PATH'] = request['tools']['node']
    started = time.monotonic()
    try:
        result = execute(request, request_file, phase)
    except Exception as error:
        result = {'status': 'failed', 'errorType': type(error).__name__, 'error': str(error)}
        write_new(Path(request['output']) / f'{phase}-failure.json', result)
        raise
    result['elapsedSeconds'] = time.monotonic() - started
    if phase in {'all', 'verify'}:
        write_new(Path(request['output']) / 'checks.json', result)
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
