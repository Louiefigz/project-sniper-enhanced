"""Supervised real-media equivalence checks for early audio and streaming QC."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audio.mastering_profile import resolve_mastering_profile
from audio.native_master_preparation import NativeMasterPreparation, prepare_native_master
from cut_preview_io import bound_json, file_hash, write_new
from studio.native_run import NativeRun
from studio.native_run_config import NativeRunConfig, local_environment
from studio.native_runtime import digest, install_runtime
from studio.native_short_delivery import qualify_picture


def check_picture(request: dict, root: Path) -> dict:
    """Compare every actual frame metric and concatenated RGB byte with retained QC."""
    spec = request['picture']
    directory = root / 'picture'
    directory.mkdir()
    shutil.copyfile(spec['video'], directory / 'review.mp4')
    shutil.copyfile(spec['capture'], directory / 'native-frames.json')
    expected = bound_json(Path(spec['checks']))
    started = time.monotonic()
    actual = qualify_picture(directory, spec['canvas'])
    for key in ('comparisons', 'reverseSeekComparisons', 'candidateSha256', 'videoPackets'):
        if actual[key] != expected[key]:
            raise RuntimeError(f'Streaming verification changed {key}')
    if actual['batchDecode']['sha256'] != expected['batchDecode']['sha256']:
        raise RuntimeError('Streaming selected decoded pixels differ from original QC')
    if actual['batchDecode']['rgbScratchBytes'] != 0 or not actual['fullAudioVideoDecodePassed']:
        raise RuntimeError('Streaming validation omitted its storage or decode contract')
    return {'status': 'identical-all-comparisons-and-rgb', 'elapsedSeconds': time.monotonic() - started,
            'frames': len(actual['comparisons']), 'reverseFrames': len(actual['reverseSeekComparisons']),
            'videoSha256': actual['candidateSha256'], 'batchDecode': actual['batchDecode'],
            'fullAudioVideoDecodePassed': True}


def check_audio(spec: dict, root: Path, tools: dict) -> dict:
    """Compare the prepared float bytes or reproduce a known early hum rejection."""
    source = Path(spec['premaster'])
    original = bound_json(Path(spec['receipt']))
    if file_hash(source) != original['inputPremasterSha256']:
        raise RuntimeError('Audio fixture source differs from its original finishing receipt')
    settings = NativeMasterPreparation(source, file_hash(source), spec['samples'], root,
        resolve_mastering_profile(original['requestedMasteringProfile']['identity']), tuple(spec['sections']))
    started = time.monotonic()
    failed = False
    try:
        prepare_native_master(settings, (tools['ffmpeg'], tools['ffprobe']))
    except RuntimeError:
        failed = True
    result = bound_json(root / 'receipt.json')
    if spec['expectedFailure']:
        if not failed or not any(row['name'] == 'audio_tonal_hum' and row['status'] == 'fail'
                                 for row in result.get('audioQuality', [])):
            raise RuntimeError('Known audio hum did not fail before picture')
    elif failed or result['masterSha256'] != original['masterSha256']:
        raise RuntimeError('Early float preparation changed mastered audio bytes')
    return {'status': 'expected-hum-rejected' if failed else 'identical-master-bytes',
            'elapsedSeconds': time.monotonic() - started, 'masterSha256': result['masterSha256'],
            'pictureEncodes': 0, 'audioEncodes': 0, 'humanListeningApproved': False}


def child(request_file: Path) -> None:
    """Run only beneath the declared native owner and preserve explicit fixture scope."""
    request = bound_json(request_file)
    root = Path(request['output'])
    tools, _environment = local_environment()
    result = {'scope': 'real-media implementation equivalence, not editorial production benchmark',
              'picture': check_picture(request, root)}
    result['audio'] = [check_audio(spec, root / f'audio-{index}', tools)
                       for index, spec in enumerate(request['audio'])]
    result.update(status='optimization-media-equivalence-pass', humanListeningApproved=False)
    write_new(root / 'result.json', result)
    print(json.dumps(result))


def supervise(request_file: Path) -> None:
    """Pin declared fixtures and implementation under the unchanged shared native policy."""
    request = bound_json(request_file)
    root = Path(request['output'])
    root.mkdir()
    tools, environment = local_environment()
    runtime = install_runtime()
    producer = Path(__file__).resolve().parents[1]
    sandbox = producer / 'studio/native_localhost_only.sb'
    files = [request_file, Path(__file__), *map(Path, request['inputs']),
             *map(Path, tools.values()), producer / 'edit/exact_timing.py',
             producer / 'headless/process_runner.py', producer / 'palmier/process_deadline.py']
    for pattern in ('studio/native_*.py', 'audio/*.py', 'audit/*.py', 'native_render*.py',
                    'cut_preview_io.py', 'stage_timing*.py', 'native_work_lease.py'):
        files.extend(path for path in producer.glob(pattern) if not path.name.startswith('native_review_'))
    pins = {str(path.resolve(strict=True)): digest(path) for path in files}
    command = ['/usr/bin/sandbox-exec', '-f', str(sandbox), sys.executable,
               str(Path(__file__).resolve()), '--child', str(request_file)]
    cli = runtime / 'dist/cli.js'
    config = NativeRunConfig(request_file.parent, root, cli, command, environment,
        {'output': str(root / 'result.json'), 'sdkSha256': digest(cli), 'sandboxSha256': digest(sandbox)},
        additional_pins=pins, success_status='optimization-media-equivalence-pass')
    owner = NativeRun('equivalence', config)
    if not owner.execute():
        raise SystemExit(1)


def main() -> None:
    """One fresh output per test; no overwrite, provider calls or renderer bypass."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child', action='store_true')
    parser.add_argument('request', type=Path)
    args = parser.parse_args()
    (child if args.child else supervise)(args.request.resolve(strict=True))


if __name__ == '__main__':
    main()
