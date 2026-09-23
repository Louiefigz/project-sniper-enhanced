"""Admit and reuse exact completed native capture with its original JPEG evidence."""
from __future__ import annotations

import sys
from pathlib import Path

from cut_preview_io import bound_json, real_directory
from studio.native_runtime import digest
from studio.native_short_picture_reuse import copy_picture
from studio.native_short_resume import media_result
from studio.native_stage_evidence import (
    StageEvidence, read_native_capture_receipt, read_stage, require, seal_stage, verify_pins,
)

CAPTURE_STATUS = 'native-reference-capture-complete'
NATIVE_STATUS = 'native-references-and-seek-states-pass'
STUDIO = Path(__file__).resolve().parent


def capture_artifacts(root: Path, request: dict) -> dict[str, Path]:
    """Bind each actual JPEG, retaining PNG payload paths only as recorded metadata."""
    file = root / 'native-frames.json'
    native = read_native_capture_receipt(file)
    is_long = request.get('adapter') == 'native-long'
    canvas = bound_json(Path(request['project']) / ('LONG-PROJECT.json' if is_long else 'SHORT-PROJECT.json'))['canvas']
    require(native.get('status') == NATIVE_STATUS and native.get('fromEncodedOutput') is False
            and native.get('project') == request['project'] and native.get('failedSceneStates') == [],
            'native reference checks did not independently pass')
    require(native.get('width') == canvas.get('width', 1080) and native.get('height') == canvas.get('height', 1920)
            and native.get('frameRate') == canvas['frameRate']
            and native.get('sourceHtmlSha256') == digest(Path(request['project']) / 'index.html')
            and native.get('runtimeLibrarySha256') == digest(Path(request['runtime']) / 'dist/native-capture-library.mjs'),
            'capture source, runtime or canvas differs')
    rows = native.get('frames')
    require(type(rows) is list and bool(rows) and len(rows) <= 100000, 'missing bounded capture frames')
    require(all(type(row) is dict for row in rows), 'invalid captured frame rows')
    require([row.get('frame') for row in rows] == native.get('expectedCapturePoints'), 'capture schedule differs')
    artifacts = {'native': file}
    for index, row in enumerate(rows):
        frame = row.get('frame')
        require(type(frame) is int and 0 <= frame < canvas['totalFrames']
                and type(row.get('repeat')) is bool, 'invalid captured frame identity')
        image = Path(row['path'])
        require(image.is_absolute() and image.is_relative_to(root) and image.suffix == '.jpg'
                and image.resolve(strict=True) == image and not image.is_symlink(), 'capture JPEG escaped its owner')
        require(digest(image) == row['sha256'], 'captured JPEG changed')
        artifacts[f'frame{index:06d}'] = image
    require(len(set(artifacts.values())) == len(artifacts), 'duplicate capture JPEG path')
    require(any(row['repeat'] for row in rows) and any(not row['repeat'] for row in rows), 'missing forward/reverse proof')
    if is_long:
        artifacts.update({'sample-reel': root / 'seam-samples.mp4', 'sample-qc': root / 'sample-qc/result.json'})
        if not request.get('verifyStage'):
            artifacts.update({'prepared-audio': root / 'prepared-audio.json',
                'audio-preparation': root / 'audio-preparation/receipt.json'})
            if not request.get('audioDonor'):
                artifacts['prepared-master'] = root / 'audio-preparation/program-master.wav'
    elif not request.get('verifyStage'):
        artifacts['sample-reel'] = root / 'seam-samples.mp4'
    return artifacts


def bind_capture_media(root: Path, render_stage: Path) -> tuple[dict, dict]:
    """Require capture and media to originate from the same sealed project and route."""
    sealed = bound_json(render_stage)
    render, pins = read_stage(render_stage, sealed['inputs'], 'render')
    media_result(render)
    request_file = root / 'export-request.json'
    request = bound_json(request_file)
    owner = bound_json(root / 'capture.render.json')
    require_capture_worker(request, request_file, owner)
    original = bound_json(Path(render['request']['path']), render['request']['sha256'])
    for key in ('project', 'runtime', 'tools', 'cache', 'captureMode', 'sourceCacheMode', 'audioProfile'):
        require(request.get(key) == original.get(key), f'capture/media {key} differs')
    if request.get('verifyStage'):
        require(request['verifyStage'] == str(render_stage) and request.get('renderInputs') == render['inputs']
                and request.get('renderResult') == render['artifacts']['media']['path'], 'capture uses another render seal')
        require(all(request['pins'].get(file) == sha for file, sha in pins.items()), 'capture omitted sealed media pins')
    else:
        require(str(request_file) == render['request']['path']
                and digest(request_file) == render['request']['sha256'], 'capture is not the original media attempt')
    return request, render


def complete_capture(root: Path, render_stage: Path) -> tuple[Path, dict[str, str]]:
    """Add only a new immutable capture seal after full original ownership validation."""
    real_directory(root)
    request, _render = bind_capture_media(root, render_stage)
    artifacts = capture_artifacts(root, request)
    receipt = root / 'capture-stage.json'
    if not receipt.exists() and not receipt.is_symlink():
        spec = StageEvidence('capture', Path(request['project']), root, root / 'export-request.json',
                             root / 'capture.render.json', request['pins'], artifacts, CAPTURE_STATUS)
        seal_stage(spec)
    record, pins = read_stage(receipt, request['pins'], 'capture')
    require(record['successStatus'] == CAPTURE_STATUS
            and {name: row['path'] for name, row in record['artifacts'].items()}
            == {name: str(file) for name, file in artifacts.items()}, 'sealed capture inventory differs')
    return receipt, pins


def seal_capture(root: Path, render_stage: Path) -> Path:
    """Expose the legacy path result through the same complete capture admission."""
    receipt, _pins = complete_capture(root, render_stage)
    return receipt


def read_capture(receipt: Path, render_stage: Path) -> tuple[dict, dict]:
    """Reopen the exact capture seal without generating new media or cache entries."""
    require(receipt.name == 'capture-stage.json', 'expected a capture-stage.json seal')
    request, _render = bind_capture_media(receipt.parent, render_stage)
    record, pins = read_stage(receipt, request['pins'], 'capture')
    artifacts = capture_artifacts(receipt.parent, request)
    require(record['successStatus'] == CAPTURE_STATUS
            and {name: row['path'] for name, row in record['artifacts'].items()}
            == {name: str(file) for name, file in artifacts.items()}, 'sealed capture inventory differs')
    return record, pins


def require_capture_worker(request: dict, request_file: Path, owner: dict) -> None:
    """Bind the exact qualified SDK or batch worker and its pinned interpreter."""
    sandbox = STUDIO / 'native_localhost_only.sb'
    mode = request.get('captureMode')
    require(mode in {'sdk-streaming', 'cached-native-batches'}, 'unsupported capture route')
    is_long = request.get('adapter') == 'native-long'
    worker = STUDIO / ('native_long_worker.py' if is_long else
                       'native_short_capture.mjs' if mode == 'sdk-streaming' else 'native_short_worker.py')
    interpreter = request['tools']['node'] if mode == 'sdk-streaming' and not is_long else sys.executable
    child = [interpreter, str(worker), str(request_file)]
    if mode == 'cached-native-batches' or is_long:
        child.append('capture')
    require(owner.get('args') == ['/usr/bin/sandbox-exec', '-f', str(sandbox), *child],
            'capture owner used another worker')
    require(all(request['pins'].get(str(file)) == digest(file)
                for file in (worker, sandbox, Path(interpreter).resolve(strict=True))),
            'capture worker, interpreter or sandbox was not pinned')


def capture_candidate(root: Path, render_stage: Path) -> Path | None:
    """Prefer an immutable seal; an old successful unsealed owner must pass the same checks."""
    receipt = root / 'capture-stage.json'
    if receipt.exists() or receipt.is_symlink():
        return receipt
    owner_file = root / 'capture.render.json'
    if owner_file.exists() or owner_file.is_symlink():
        owner = bound_json(owner_file)
        if owner.get('status') == CAPTURE_STATUS:
            return seal_capture(root, render_stage)
        require(owner.get('status') == 'failed', 'capture owner has no terminal status')
    return None


def prepare_capture_reuse(request: dict, render_stage: Path, attempt: Path) -> dict:
    """Bind a selected attempt's capture without weakening the original render closure."""
    real_directory(attempt)
    selected = bound_json(attempt / 'export-request.json')
    require(selected.get('output') == str(attempt), 'resume request belongs to another attempt')
    for key in ('project', 'runtime', 'tools', 'cache', 'captureMode', 'sourceCacheMode', 'audioProfile'):
        require(selected.get(key) == request.get(key), f'resume attempt {key} differs')
    if selected.get('verifyStage'):
        require(selected['verifyStage'] == str(render_stage)
                and selected.get('renderInputs') == request['renderInputs']
                and selected.get('renderResult') == request['renderResult'],
                'resume attempt uses another render closure')
    else:
        require(attempt == render_stage.parent, 'resume attempt omitted its original render seal')
    source = selected.get('captureStage')
    receipt = Path(source) if source else capture_candidate(attempt, render_stage)
    if receipt is None:
        return request
    record, pins = read_capture(receipt, render_stage)
    if source:
        require(all(selected['pins'].get(file) == sha for file, sha in pins.items()),
                'resume attempt omitted capture pins')
    output, donor = Path(request['output']), Path(record['root'])
    require(output != donor and not output.is_relative_to(donor) and not donor.is_relative_to(output),
            'resume output must preserve the capture donor')
    require(all(file not in request['pins'] or request['pins'][file] == sha for file, sha in pins.items()),
            'capture and render dependency hashes differ')
    return {**request, 'captureStage': str(receipt), 'pins': {**request['pins'], **pins}}


def copy_completed_capture(request: dict) -> tuple[dict, dict[str, str]]:
    """Copy only the native JSON and retain exact original JPEG paths for normal final QC."""
    receipt = Path(request['captureStage'])
    record, pins = read_capture(receipt, Path(request['verifyStage']))
    require(all(request['pins'].get(file) == sha for file, sha in pins.items()),
            'capture evidence was not pinned')
    native = record['artifacts']['native']
    destination = Path(request['output']) / 'native-frames.json'
    copy_picture(Path(native['path']), destination, native['sha256'])
    verify_pins(pins)
    return record, {**pins, str(destination): native['sha256']}
