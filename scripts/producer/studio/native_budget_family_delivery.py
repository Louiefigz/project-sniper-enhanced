"""Read the existing final media/capture/verification proof before family settlement.

A delivery document is an output, not authority by itself. This reader reuses the
same sealed media and supervised worker contracts as the ordinary pipeline and
performs no rendering, sealing, or publication.
"""
from __future__ import annotations

import sys
from pathlib import Path

from cut_preview_io import bound_json
from studio.native_runtime import digest
from studio.native_short_capture_resume import read_capture
from studio.native_short_resume import media_result
from studio.native_stage_evidence import StageEvidence, _build_record, read_stage, require

CHECKED = 'native-long-checked-for-review'


def require_checked_media(request: dict, result: dict) -> None:
    """Reopen completed render, capture and exact owned verifier before recording final authority."""
    root = Path(request['output'])
    render_file = Path(request.get('verifyStage') or root / 'render-stage.json')
    render, render_pins = read_stage(render_file, bound_json(render_file)['inputs'], 'render')
    media_result(render)
    require_current_stage(request, render, render_pins)
    expected = render['artifacts']['review']['sha256']
    require(result.get('output') == str(root / 'review.mp4') and result.get('sha256') == expected
            and digest(root / 'review.mp4') == expected, 'Family final delivery differs from sealed rendered media')
    capture_file = Path(request.get('captureStage') or root / 'capture-stage.json')
    capture, capture_pins = read_capture(capture_file, render_file)
    require_current_stage(request, capture, capture_pins)
    spec = StageEvidence('verification', Path(request['project']), root, root / 'export-request.json',
                         root / 'verification.render.json', request['pins'],
                         {'checks': root / 'checks.json', 'review': root / 'review.mp4'}, CHECKED)
    verification, pins = _build_record(spec)
    require(all(pins.get(name) == sha for name, sha in {**render_pins, **capture_pins}.items()),
            'Family verifier did not supervise the completed media/capture closure')
    checks = bound_json(root / 'checks.json', verification['artifacts']['checks']['sha256'])
    require(checks.get('status') == 'checks-passed-awaiting-owned-cleanup'
            and checks.get('sha256') == expected and checks.get('fullAudioVideoDecodePassed') is True,
            'Family final encoded verification is incomplete')
    require_verifier(request, bound_json(root / 'verification.render.json'))


def require_verifier(request: dict, owner: dict) -> None:
    """Require the maintained sandboxed verification worker and interpreter in admitted pins."""
    studio = Path(__file__).resolve().parent
    sandbox, worker = studio / 'native_localhost_only.sb', studio / 'native_long_worker.py'
    request_file = Path(request['output']) / 'export-request.json'
    command = ['/usr/bin/sandbox-exec', '-f', str(sandbox), sys.executable,
               str(worker), str(request_file), 'verify']
    require(owner.get('args') == command and owner.get('output') == str(request_file.parent / 'checks.json'),
            'Family final verification used another worker or output')
    required = (sandbox, worker, Path(sys.executable).resolve(strict=True))
    require(all(request['pins'].get(str(file)) == digest(file) for file in required),
            'Family final verifier, interpreter or sandbox was not pinned')


def require_current_stage(request: dict, stage: dict, pins: dict) -> None:
    """Bind same-attempt stages or the explicit already-admitted original recovery closure."""
    original = bound_json(Path(stage['request']['path']), stage['request']['sha256'])
    if original == request:
        return
    for key in ('project', 'runtime', 'tools', 'cache', 'captureMode', 'sourceCacheMode', 'audioProfile'):
        require(request.get(key) == original.get(key), f'Family final recovered {key} differs')
    require(all(request['pins'].get(name) == sha for name, sha in pins.items()),
            'Family final recovered stage was not admitted in the immutable current request')
    expected = request.get('verifyStage' if stage['stage'] == 'render' else 'captureStage')
    require(expected == str(Path(stage['root']) / f"{stage['stage']}-stage.json"),
            'Family final stage is not the explicitly admitted recovery source')
