"""Run each native export stage inside the existing bounded process owner."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stage_timing import stage_span
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


def execute(request: dict, request_file: Path) -> dict:
    """Retain individual stage timing and fail before publishing any passing result."""
    root, project = Path(request['output']), Path(request['project'])
    plan = json.loads((project / 'SHORT-PROJECT.json').read_text())
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
    with stage_span(str(root), 'native_capture_and_seek_checks'):
        capture = Path(__file__).with_name('native_short_capture.mjs')
        run([request['tools']['node'], str(capture), str(request_file)])
    with stage_span(str(root), 'native_picture_and_full_decode_checks'):
        picture = qualify_picture(root, canvas)
    verify_files(request)
    return {'status': 'checks-passed-awaiting-owned-cleanup', 'output': color['output'],
            'sha256': color['sha256'], 'audioReceipt': str(root / 'audio/receipt.json'),
            'audioReviewRequired': audio['audioReviewRequired'], 'audioQuality': audio['audioQuality'],
            'color': color, 'pictureFramesChecked': len(picture['comparisons']),
            'fullAudioVideoDecodePassed': True, 'humanApproved': False,
            'additionalPictureEncodes': 0 if request.get('pictureDonor') else 1,
            'sourceCurrent': True, 'providerCalls': 0}


def main() -> None:
    """The supervisor owns cancellation, resources and final completion authority."""
    request_file = Path(sys.argv[1])
    request = json.loads(request_file.read_text())
    os.environ['SNIPER_NODE_PATH'] = request['tools']['node']
    started = time.monotonic()
    try:
        result = execute(request, request_file)
    except Exception as error:
        result = {'status': 'failed', 'errorType': type(error).__name__, 'error': str(error)}
        (Path(request['output']) / 'checks.json').write_text(json.dumps(result, indent=2))
        raise
    result['elapsedSeconds'] = time.monotonic() - started
    (Path(request['output']) / 'checks.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
