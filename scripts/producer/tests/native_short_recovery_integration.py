"""Real Short public-command recovery with synthetic TEST review; no production approval."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cut_preview_io import bound_json, write_new
from studio.native_run import NativeRun
from studio.native_run_config import NativeRunConfig, local_environment
from studio.native_runtime import REPO, digest, install_runtime
from studio.native_short_export import prepare
from studio.native_short_pipeline import NativeShortPipeline
from studio.native_review_contract import read_composition

HERE = Path(__file__).resolve()


def fixture_worker(request: dict) -> None:
    """Create tiny local input media under the unchanged shared heavy-work owner."""
    root, source, tools = Path(request['output']), Path(request['source']), request['tools']
    subprocess.run([tools['ffmpeg'], '-nostdin', '-v', 'error', '-n',
        '-i', str(source / 'assets/picture.mp4'), '-i', str(source / 'assets/dialogue.wav'),
        '-t', '2', '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac',
        '-b:a', '320k', '-aac_pns', '0', '-af', 'lowpass=f=6000', str(root / 'source.mp4')], check=True, timeout=60)
    subprocess.run([tools['ffmpeg'], '-nostdin', '-v', 'error', '-n',
        '-i', str(root / 'source.mp4'), '-frames:v', '1', str(root / 'reference.jpg')], check=True, timeout=60)
    write_new(root / 'fixture-result.json', {'status': 'fixture-complete', 'productionDelivery': False})


def make_fixture(root: Path, source: Path, font: Path) -> None:
    """Generate real inputs, then use the normal compiler and strict synthetic review schema."""
    control, output = root / 'fixture-control', root / 'fixture-media'
    control.mkdir(); output.mkdir()
    (control / 'TEST.txt').write_text('Local fixture preparation; no production or human approval.')
    tools, environment = local_environment()
    runtime = install_runtime()
    request = {'project': str(control), 'output': str(output), 'source': str(source), 'tools': tools}
    file = output / 'fixture-request.json'; write_new(file, request)
    cli = runtime / 'dist/cli.js'
    sandbox = REPO / 'scripts/producer/studio/native_localhost_only.sb'
    pins = {str(path): digest(path) for path in (file, HERE, source / 'assets/picture.mp4',
            source / 'assets/dialogue.wav', *map(Path, tools.values()))}
    config = NativeRunConfig(control, output, cli,
        ['/usr/bin/sandbox-exec', '-f', str(sandbox), sys.executable, str(HERE), 'worker', str(file)],
        environment, {'output': str(output / 'fixture-result.json'),
                      'sdkSha256': digest(cli), 'sandboxSha256': digest(sandbox)},
        additional_pins=pins, success_status='short-test-fixture-complete')
    if not NativeRun('fixture', config).execute():
        raise RuntimeError('Short source fixture preparation failed')
    subprocess.run([tools['node'], '--import', 'tsx', str(HERE.with_name('native_short_recovery_fixture.ts')),
        str(root), str(output / 'source.mp4'), str(source / 'assets/gsap.min.js'), str(font),
        str(output / 'reference.jpg'), str(output / 'reference.jpg')],
        check=True, cwd=REPO, env=environment, timeout=60)


def cli(project: Path, output: Path) -> dict:
    """Exercise public selection and the default Short route, without a resume/donor flag."""
    log = output.parent / f'{output.name}.log'
    with log.open('xb') as handle:
        result = subprocess.run([sys.executable, str(REPO / 'scripts/producer/studio/native_export.py'),
            str(project), str(output), '--audio-profile', 'default-v3'],
            cwd=REPO, stdout=handle, stderr=subprocess.STDOUT, timeout=1200)
    if result.returncode:
        raise RuntimeError(f'Public Short export failed; inspect {log}')
    return bound_json(output / 'delivery.json')


def settings(project: Path, output: Path) -> argparse.Namespace:
    """Retain normal CLI defaults apart from this explicit technical fixture's audio profile."""
    return argparse.Namespace(project=project, output=output, cache=None, reference_map=None,
        cached_native_batches=False, acquire_source_cache=False, audio_profile='default-v3',
        audio_donor=None, picture_donor=None, verify_from=None, resume_from=None, render_only=False)


def failed_metadata(project: Path, output: Path) -> None:
    """Force a real exclusive-output failure after SDK picture and AAC qualification."""
    request, environment = prepare(settings(project, output))
    (output / 'review.mp4').write_bytes(b'TEST deliberate output collision; not encoded media')
    if NativeShortPipeline(request, environment).execute():
        raise RuntimeError('The exclusive-output collision unexpectedly succeeded')
    if bound_json(output / 'audio/receipt.json')['status'] != 'audio-qualified':
        raise RuntimeError('Expected real audio qualification before the output collision')


def interrupted_render(project: Path, output: Path) -> None:
    """Leave a real completed render with an intentional later capture failure."""
    request, environment = prepare(settings(project, output))
    pipeline = NativeShortPipeline(request, environment)
    with patch.object(pipeline, 'capture', side_effect=RuntimeError('TEST intentional post-render interruption')):
        if pipeline.execute():
            raise RuntimeError('Expected the deliberately interrupted invocation to fail')
    if not (output / 'render-stage.json').is_file():
        raise RuntimeError('Short media did not finish before the intended interruption')


def run(root: Path, source: Path, font: Path) -> None:
    """Prove real pixels/audio survive repeated automatic retries across output parents."""
    root.mkdir()
    make_fixture(root, source, font)
    project, original = root / 'project', root / 'interrupted'
    partial = root / 'metadata-failure'
    failed_metadata(project, partial)
    partial_hashes = {str(file): digest(file) for file in partial.rglob('*') if file.is_file()}
    interrupted_render(project, original)
    recovered = bound_json(original / 'render-result.json')
    audio = bound_json(original / 'audio/receipt.json')
    if recovered['additionalPictureEncodes'] != 0 or audio['additionalAacEncodes'] != 0:
        raise RuntimeError('Partial Short recovery repeated picture or AAC encoding')
    hashes = {str(file): digest(file) for file in original.rglob('*') if file.is_file()}
    elsewhere = root / 'elsewhere'; elsewhere.mkdir()
    recovered = elsewhere / 'recovered'
    first = cli(project, recovered)
    final = cli(project, root / 'verified')
    if first['status'] != 'native-short-checked-for-review' or not first['renderReused']:
        raise RuntimeError('Automatic Short retry did not qualify reused media')
    if final['sha256'] != first['sha256'] or [row['phase'] for row in final['stages']] != ['capture-reused', 'verification']:
        raise RuntimeError('Repeated Short retry did not preserve media and capture')
    for attempt in (recovered, root / 'verified'):
        request = bound_json(attempt / 'export-request.json')
        if request['recoverySelection']['mode'] != 'automatic' or (attempt / 'picture.mp4').exists():
            raise RuntimeError('Retry did not select automatic completed-media reuse')
    hashes.update(partial_hashes)
    if hashes != {file: digest(Path(file)) for file in hashes}:
        raise RuntimeError('Original attempt changed during automatic recovery')
    review = read_composition({'id': 'TestShort', 'title': 'TEST Short recovery', 'export': str(root / 'verified')})
    if review.video_sha256 != final['sha256']:
        raise RuntimeError('Short review admission changed final bytes')
    write_new(root / 'integration-result.json', {'status': 'short-automatic-recovery-passed',
        'syntheticReview': True, 'productionDelivery': False, 'humanApproved': False,
        'automaticCompletedMediaRecovery': True, 'automaticCompletedCaptureRecovery': True,
        'automaticPartialPictureAndAacRecovery': True,
        'crossParentRecovery': True, 'reviewAdmission': True, 'originalAttemptUnchanged': True,
        'additionalPictureEncodesAfterFailure': 0, 'additionalAudioEncodesAfterFailure': 0,
        'videoSha256': final['sha256']})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('worker', 'run'))
    parser.add_argument('path', type=Path)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--font', type=Path)
    args = parser.parse_args()
    if args.operation == 'worker':
        fixture_worker(bound_json(args.path))
    else:
        run(args.path.absolute(), args.source.resolve(strict=True), args.font.resolve(strict=True))
