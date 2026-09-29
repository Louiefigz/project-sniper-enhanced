"""Once-per-identity complete-route canary on a TEST native Short fixture.

``run <fixture-root> <new-run-dir>`` exports the fixture's ``good`` project through
the public exporter (moving preview, TEST-labeled motion review, full export and
all final checks), verifies the SDR/AAC output, and records a pass bound to the
exact engine/runtime/tool/fixture input identity. Later runs with the same
identity reuse that pass without media work. ``status <fixture-root>`` reports
whether a pass exists for the current identity. The generated review records are
explicitly TEST and bind only this fixture's preview; they are never production
authority. Exit status: 0 pass (new or reused), 1 canary failed, 2 invalid use.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cut_preview_io import bound_json, digest as json_digest, real_directory, write_new
from studio.native_runtime import REPO, digest
from studio.native_stage_evidence import require

FIXTURE_SCOPE = 'TEST-native-route-canary-fixture'
PASS_STATUS = 'native-route-canary-pass'
PREVIEW_STATUS, FINAL_STATUS = 'native-motion-previews-complete', 'native-short-checked-for-review'
COVERAGE = ('briefAndRetainedMessage', 'assetsAndSourceEvidence', 'cuesAndSceneCoverage', 'layoutCropAndText',
            'motionAndTransitions', 'pacingAndAudio', 'feasibility', 'visualSourceSelection')
HDR_TRANSFERS = {'arib-std-b67', 'smpte2084'}


@dataclass(frozen=True)
class CanaryBounds:
    """Explicit caller bounds for the two public export invocations."""

    preview_seconds: float = 1200.0
    final_seconds: float = 1800.0


def fixture_project(root: Path) -> tuple[dict, Path]:
    """Admit only a TEST fixture manifest whose good project lies inside the fixture."""
    real_directory(root)
    fixture = bound_json(root / 'FIXTURE.json')
    require(fixture.get('scope') == FIXTURE_SCOPE and fixture.get('productionAuthority') is False,
            'canary requires a TEST native route fixture without production authority')
    project = Path(fixture['variants']['good']['project'])
    require(project.is_relative_to(root) and project.resolve(strict=True) == project, 'canary project escaped its fixture')
    return fixture, project


def canary_identity(project: Path) -> tuple[str, dict[str, str]]:
    """Hash the exporter's complete input pins; repository files are keyed relatively."""
    from studio.native_run_config import local_environment
    from studio.native_runtime import install_runtime
    from studio.native_short_export import input_pins
    tools, _environment = local_environment()
    pins = input_pins(project, install_runtime(), tools)
    normalized = {(f'repo:{Path(name).relative_to(REPO).as_posix()}' if Path(name).is_relative_to(REPO) else name): sha
                  for name, sha in sorted(pins.items())}
    return json_digest(normalized), normalized


def recorded_pass(root: Path, identity: str) -> dict | None:
    """Return a recorded pass for this identity when its final evidence still verifies."""
    file = root / 'canary-passes' / f'{identity}.json'
    if not file.is_file():
        return None
    record = bound_json(file)
    final = Path(record['final']['attempt'])
    require(record.get('status') == PASS_STATUS and record.get('identity') == identity, 'canary pass record is invalid')
    if not (final / 'delivery.json').is_file() or digest(final / 'delivery.json') != record['final']['deliverySha256'] \
            or digest(final / 'review.mp4') != record['final']['reviewSha256']:
        return None
    return record


def export(project: Path, attempt: Path, options: list[str], timeout: float) -> dict:
    """Run the public exporter once and return its terminal receipt summary."""
    started = time.monotonic()
    with (attempt.parent / f'{attempt.name}.log').open('xb') as log:
        completed = subprocess.run([sys.executable, '-B', str(REPO / 'scripts/producer/studio/native_export.py'),
                                    str(project), str(attempt), *options], cwd=REPO, stdout=log,
                                   stderr=subprocess.STDOUT, timeout=timeout, check=False)
    delivery = bound_json(attempt / 'delivery.json')
    return {'attempt': str(attempt), 'exitCode': completed.returncode, 'status': delivery['status'],
            'wallSeconds': time.monotonic() - started, 'exportSeconds': delivery.get('elapsedSeconds'),
            'deliverySha256': digest(attempt / 'delivery.json'), 'error': delivery.get('error'),
            'failedPhase': delivery.get('failedPhase'),
            'stages': [{key: row.get(key) for key in ('phase', 'status', 'elapsedSeconds')} for row in delivery['stages']]}


def write_test_reviews(run: Path, preview: Path) -> Path:
    """Write explicitly TEST motion reviews bound to this fixture preview's exact units."""
    result = preview / 'motion-previews.json'
    packet = bound_json(result)['packet']
    evidence = run / 'TEST-canary-no-playback.txt'
    with evidence.open('x', encoding='utf-8') as handle:
        handle.write('TEST route canary only. No person or agent viewed or listened to these previews; '
                     'this record is not an editorial review and grants no production authority.\n')
    review = {'reviewer': {'identity': 'TEST route canary (not an independent reviewer)',
                           'sessionId': 'TEST-canary-review', 'plannerSessionId': 'TEST-canary-fixture', 'independent': True},
              'coverage': {key: 'TEST route canary; no playback, listening or editorial review occurred' for key in COVERAGE},
              'evidence': [{'path': str(evidence), 'sha256': digest(evidence)}],
              'review': {'schemaVersion': 1, 'stage': 'plan', 'verdict': 'pass', 'materialIssues': [], 'findings': [],
                         'summary': 'TEST route canary structural record only; never production approval'},
              'units': {row['id']: row['hash'] for row in packet['units']},
              'preview': {'path': str(result), 'sha256': digest(result)},
              'assessment': 'TEST canary: exercises the export route only; no media was watched or approved.'}
    file = run / 'TEST-canary-motion-reviews.json'
    write_new(file, {'schemaVersion': 1, 'reviews': [review]})
    return file


def probe(file: Path) -> dict:
    """Read stream facts of the delivered MP4 with the admitted ffprobe."""
    from graphics.render_tools import resolve_tools
    output = subprocess.run([resolve_tools()['ffprobe'], '-v', 'error', '-count_packets', '-show_entries',
                             'stream=codec_type,codec_name,pix_fmt,color_primaries,color_transfer,color_space,'
                             'sample_rate,channels,nb_read_packets:format=duration', '-of', 'json', str(file)],
                            capture_output=True, text=True, check=True, timeout=120).stdout
    return json.loads(output)


def packaged_audio(attempt: Path, depth: int = 0) -> dict:
    """Follow exact preview reuse (restored sections or previewFrom) to the attempt that packaged audio."""
    file = attempt / 'prepared-audio.json'
    if file.is_file():
        return {**bound_json(file)['audioStage'], 'packagedIn': str(attempt)}
    request = bound_json(attempt / 'export-request.json')
    donors = sorted(path for phase, path in (request.get('previewSectionDonors') or {}).items()
                    if phase.startswith('preview-package-'))
    prior = Path(donors[0]).parent if donors else Path(request['previewFrom']).parent if request.get('previewFrom') else None
    require(prior is not None and depth < 256, 'canary preview has neither its own nor a reused audio package')
    return packaged_audio(prior, depth + 1)


def audio_evidence(preview: Path, final: Path) -> dict:
    """Show which sealed master previews and the final consumed, by hash."""
    stages = [packaged_audio(attempt) for attempt in (preview, final)]
    require(all(isinstance(row, dict) for row in stages), 'canary attempts did not import a sealed audio stage')
    delivered = bound_json(final / 'audio/receipt.json').get('masterSha256')
    return {'previewAudioStage': stages[0], 'finalAudioStage': stages[1], 'deliveredMasterSha256': delivered,
            'sameSealedStage': stages[0]['seal'] == stages[1]['seal'],
            'previewAndFinalMasterEqual': stages[0]['masterSha256'] == stages[1]['masterSha256'],
            'deliveredMasterIsSealedMaster': delivered == stages[1]['masterSha256']}


def verify_final(run: Path, fixture: dict) -> dict:
    """Require checked SDR H.264 with 48 kHz stereo AAC at the exact frame count."""
    final = run / 'final'
    streams = {row['codec_type']: row for row in probe(final / 'review.mp4')['streams']}
    video, audio = streams.get('video', {}), streams.get('audio', {})
    checks = {'videoCodec': video.get('codec_name'), 'pixelFormat': video.get('pix_fmt'),
              'colorPrimaries': video.get('color_primaries'), 'colorTransfer': video.get('color_transfer'),
              'videoPackets': int(video.get('nb_read_packets', 0)), 'audioCodec': audio.get('codec_name'),
              'audioSampleRate': audio.get('sample_rate'), 'audioChannels': audio.get('channels'),
              'checksReceipt': bound_json(final / 'checks.json').get('status')}
    require(checks['videoCodec'] == 'h264' and checks['colorTransfer'] not in HDR_TRANSFERS
            and checks['colorPrimaries'] == 'bt709', 'canary output is not the qualified SDR H.264 route')
    require(checks['videoPackets'] == fixture['variants']['good']['totalFrames'] and checks['audioCodec'] == 'aac'
            and checks['audioSampleRate'] == '48000' and checks['audioChannels'] == 2, 'canary output clock/audio differ')
    return {**checks, **audio_evidence(run / 'preview', final)}


def run_canary(root: Path, run: Path, bounds: CanaryBounds) -> dict:
    """Reuse a current pass, else run preview → TEST review → final → checks and record one."""
    fixture, project = fixture_project(root)
    identity, pins = canary_identity(project)
    current = recorded_pass(root, identity)
    if current is not None:
        return {**current, 'reused': True}
    real_directory(run.parent)
    run.mkdir(mode=0o700)
    step = 'preview'
    try:
        preview = export(project, run / 'preview', ['--preview-only'], bounds.preview_seconds)
        require(preview['status'] == PREVIEW_STATUS, f"canary preview failed: {preview['error']}")
        step, reviews = 'final', write_test_reviews(run, run / 'preview')
        final = export(project, run / 'final', ['--preview-reviews', str(reviews)], bounds.final_seconds)
        require(final['status'] == FINAL_STATUS, f"canary final export failed: {final['error']}")
        final['reviewSha256'] = digest(run / 'final/review.mp4')
        step = 'checks'
        checks = verify_final(run, fixture)
        require(canary_identity(project)[0] == identity, 'engine, runtime or fixture changed during the canary')
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as error:
        write_new(run / 'canary-failure.json', {'status': 'failed', 'step': step, 'error': str(error),
                                                'identity': identity, 'passRecorded': False})
        raise
    record = {'schemaVersion': 1, 'scope': 'TEST-native-route-canary-pass', 'status': PASS_STATUS,
              'identity': identity, 'pins': pins, 'fixture': {'root': str(root), 'project': str(project),
              'manifestSha256': digest(root / 'FIXTURE.json')}, 'run': str(run), 'preview': preview, 'final': final,
              'checks': checks, 'productionAuthority': False, 'humanApproved': False,
              'recordedAt': datetime.now(timezone.utc).isoformat()}
    (root / 'canary-passes').mkdir(mode=0o700, exist_ok=True)
    write_new(root / 'canary-passes' / f'{identity}.json', record)
    write_new(run / 'canary-pass.json', record)
    return {**record, 'reused': False}


def canary_status(root: Path) -> dict:
    """Report the current identity and whether a verified pass is recorded for it."""
    _fixture, project = fixture_project(root)
    identity, _pins = canary_identity(project)
    record = recorded_pass(root, identity)
    return {'status': 'pass-current' if record else 'no-current-pass', 'identity': identity,
            'fixture': str(root), 'passRecord': str(root / 'canary-passes' / f'{identity}.json') if record else None,
            'finalAttempt': record['final']['attempt'] if record else None}


def main() -> None:
    """Dispatch status/run and print one compact JSON result."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('status', 'run'))
    parser.add_argument('fixture', type=Path)
    parser.add_argument('run', type=Path, nargs='?')
    parser.add_argument('--preview-seconds', type=float, default=CanaryBounds.preview_seconds)
    parser.add_argument('--final-seconds', type=float, default=CanaryBounds.final_seconds)
    args = parser.parse_args()
    try:
        if args.operation == 'status':
            print(json.dumps(canary_status(args.fixture.resolve(strict=True))))
            return
        require(args.run is not None, 'run needs a new run directory')
        result = run_canary(args.fixture.resolve(strict=True), args.run.absolute(),
                            CanaryBounds(args.preview_seconds, args.final_seconds))
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(json.dumps({'status': 'failed', 'error': str(error)}))
        raise SystemExit(1 if args.operation == 'run' else 2) from error
    print(json.dumps({key: result[key] for key in ('status', 'identity', 'reused', 'run', 'checks')}
                     | {'previewSeconds': result['preview']['wallSeconds'], 'finalSeconds': result['final']['wallSeconds']}))


if __name__ == '__main__':
    main()
