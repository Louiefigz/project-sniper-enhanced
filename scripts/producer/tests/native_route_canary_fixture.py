"""TEST native route canary fixture: regenerate a small current-schema native Short.

``python3 -B scripts/producer/tests/native_route_canary_fixture.py build <new-root>`` (via the launcher, cwd =
checkout): a supervised NativeRun worker stream-copies a real IMG_5954 HEVC HLG extract, the TS builder authors four
variants with synthetic TEST editorial records, and the supported native-short.ts build/check/check-export and
native_preflight.py commands build and check them. Never production, editorial, listening or delivery authority.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cut_preview_io import bound_json, file_hash, real_directory, write_new  # noqa: E402
from edit.selected_sources_media import (  # noqa: E402
    command, decimal, media_info, packet_origin, packets, verify_picture_metadata)
from studio.native_run import NativeRun  # noqa: E402
from studio.native_run_config import NativeRunConfig, local_environment  # noqa: E402
from studio.native_runtime import REPO, digest, install_runtime  # noqa: E402
from studio.native_stage_evidence import require  # noqa: E402
from _private_budget_root import use_private_budget_root  # noqa: E402

HERE = Path(__file__).resolve()
BUILDER = str(HERE.with_suffix('.ts'))
SOURCE = Path('/Users/aaronfigueroa/development/demos/YT-Automation/outputs/project-sniper-release-rc4-work/'
              'qualification-catalog-preview-e7be8ee/project-sniper-0.1.0-rc4/projects/img-5954-walkthrough/'
              'source/.sniper-external-media/51bab3f0259ce16dbb7835310ef512f056d7d08d229060fcf142e6ac342d7c08.media')
SOURCE_SHA = '51bab3f0259ce16dbb7835310ef512f056d7d08d229060fcf142e6ac342d7c08'
CUT_START, KEYFRAME_BOUND, SECONDS = Fraction('166.495'), Fraction('165.4'), 9
REFERENCES = (('TEST-reference-open.jpg', '1.5'), ('TEST-reference-end.jpg', '5.5'))
EXPECTED_PREFLIGHT = {'good': 0, 'graphic-edit': 0, 'bad-audio': 0, 'missing-dependency': 1}
BUSY, ATTEMPTS, BACKOFF = 'already active', 6, 60
NATIVE_SHORT, PREFLIGHT = 'scripts/producer/native-short.ts', 'scripts/producer/studio/native_preflight.py'
VIDEO_FACTS = ('codec_name', 'profile', 'pix_fmt', 'width', 'height', 'color_range', 'color_space',
               'color_transfer', 'color_primaries', 'codec_tag_string', 'r_frame_rate', 'start_time')


def select_keyframe(source: Path, tools: dict) -> tuple[Fraction, list[dict]]:
    """Return the latest source video keyframe within the bound and its packet inventory."""
    inventory = packets(source, tools, (CUT_START - 20, CUT_START + SECONDS + 5))
    keys = [row['ptsTime'] for row in inventory if 'K' in row['flags'] and row['ptsTime'] <= KEYFRAME_BOUND]
    require(bool(keys), 'no IMG_5954 video keyframe precedes the canary bound')
    return max(keys), inventory


def extract_media(source: Path, output: Path, tools: dict, keyframe: Fraction) -> Path:
    """Stream-copy HEVC HLG packets from the keyframe; re-encode only the audio as AAC."""
    target = output / 'source.mp4'
    command([tools['ffmpeg'], '-nostdin', '-v', 'error', '-xerror', '-n', '-ss', decimal(keyframe),
             '-i', str(source), '-t', str(SECONDS), '-map', '0:v:0', '-map', '0:a:0', '-c:v', 'copy',
             '-tag:v', 'hvc1', '-c:a', 'aac', '-b:a', '320k', '-ar', '48000', '-ac', '2', '-aac_pns', '0',
             '-map_metadata', '-1', '-map_chapters', '-1', '-movflags', '+faststart', str(target)])
    return target


def verify_extract(target: Path, tools: dict, source: dict) -> dict:
    """Prove unchanged zero-based HEVC 10-bit HLG packets beside zero-based 48 kHz stereo AAC."""
    info = media_info(target, tools)
    video, audio = info['video'], info['audio'] or {}
    wanted = {'codec_name': 'hevc', 'pix_fmt': 'yuv420p10le', 'color_transfer': 'arib-std-b67', 'codec_tag_string': 'hvc1'}
    require(all(video.get(key) == value for key, value in wanted.items()), 'extract is not hvc1 HEVC 10-bit HLG')
    require(audio.get('codec_name') == 'aac' and audio.get('channels') == 2, 'extract audio is not stereo AAC')
    verify_picture_metadata(target, tools, source['info']['video'])
    selected = packets(target, tools)
    # Open-GOP CRA keyframes keep their discardable RASL leading packets at negative PTS.
    require(selected[0]['ptsTime'] == 0 and packet_origin(source['packets'], selected) == source['keyframe'],
            'extract picture is not the exact source packet run from its keyframe at zero')
    command([tools['ffmpeg'], '-nostdin', '-v', 'error', '-xerror', '-i', str(target), '-f', 'null', '-'])
    return {'video': {key: video.get(key) for key in VIDEO_FACTS},
            'audio': {key: audio.get(key) for key in ('codec_name', 'sample_rate', 'channels', 'start_time')},
            'videoPackets': len(selected), 'leadingDiscardPackets': sum(row['ptsTime'] < 0 for row in selected),
            'presentableFrames': sum(row['ptsTime'] >= 0 for row in selected),
            'durationSeconds': decimal(Fraction(info['duration'])), 'originalPacketsIdentical': True,
            'fullDecodePassed': True}


def reference_frames(target: Path, output: Path, tools: dict) -> list[dict]:
    """Decode two untone-mapped technical JPEG frames used only as TEST reference files."""
    rows = []
    for name, seconds in REFERENCES:
        frame = output / name
        command([tools['ffmpeg'], '-nostdin', '-v', 'error', '-xerror', '-n', '-ss', seconds, '-i', str(target),
                 '-frames:v', '1', '-update', '1', '-q:v', '3', str(frame)])
        rows.append({'path': str(frame), 'sha256': file_hash(frame), 'extractSeconds': seconds})
    return rows


def worker(request: dict) -> None:
    """Create the extract beneath the shared owner; its result approves nothing."""
    output, source, tools = Path(request['output']), Path(request['source']), request['tools']
    keyframe, inventory = select_keyframe(source, tools)
    target = extract_media(source, output, tools, keyframe)
    facts = verify_extract(target, tools, {'info': media_info(source, tools), 'packets': inventory, 'keyframe': keyframe})
    start = CUT_START - keyframe
    write_new(output / 'fixture-result.json', {
        'status': 'fixture-complete', 'scope': 'TEST-native-route-canary-extract',
        'productionDelivery': False, 'humanApproved': False,
        'source': {'path': str(source), 'sha256': request['sourceSha256']},
        'keyframe': {'rational': str(keyframe), 'seconds': decimal(keyframe), 'bound': decimal(KEYFRAME_BOUND)},
        'cutStart': {'sourceSeconds': decimal(CUT_START), 'extractRational': str(start), 'extractSeconds': decimal(start)},
        'extract': {'path': str(target), 'sha256': file_hash(target), 'bytes': target.stat().st_size, **facts},
        'references': reference_frames(target, output, tools)})


def run_owner(base: Path, source: Path) -> bool:
    """Launch one extract attempt beneath the unchanged shared heavy-work owner."""
    control, output = base / 'control', base / 'media'
    for directory in (base, control, output):
        directory.mkdir(mode=0o700)
    (control / 'TEST.txt').write_text('TEST route-canary extract control; no production or human approval.\n')
    tools, environment = local_environment()
    cli, sandbox = install_runtime() / 'dist/cli.js', REPO / 'scripts/producer/studio/native_localhost_only.sb'
    file = output / 'fixture-request.json'
    write_new(file, {'output': str(output), 'source': str(source), 'sourceSha256': SOURCE_SHA, 'tools': tools})
    pins = {str(path): digest(path) for path in (file, HERE, source, Path(tools['ffmpeg']), Path(tools['ffprobe']))}
    require(pins[str(source)] == SOURCE_SHA, 'IMG_5954 bytes differ from their admitted content address')
    config = NativeRunConfig(
        control, output, cli, ['/usr/bin/sandbox-exec', '-f', str(sandbox), sys.executable, '-B', str(HERE),
                               'worker', str(file)], environment,
        {'output': str(output / 'fixture-result.json'), 'sdkSha256': digest(cli), 'sandboxSha256': digest(sandbox)},
        additional_pins=pins, success_status='test-canary-extract-complete', capacity_wait_seconds=300)
    return NativeRun('extract', config).execute()


@dataclass
class Fixture:
    """One new fixture root, its launcher Node and every step timing."""

    root: Path
    node: str
    timings: list[dict] = field(default_factory=list)

    def run(self, name: str, args: list[str]) -> subprocess.CompletedProcess:
        """Run one supported command from the checkout, retaining complete output under logs/."""
        started = time.monotonic()
        result = subprocess.run(args, cwd=REPO, capture_output=True, text=True, timeout=1500, check=False)
        seconds = round(time.monotonic() - started, 3)
        self.timings.append({'step': name, 'seconds': seconds, 'exitCode': result.returncode})
        with (self.root / 'logs' / f'{name}.log').open('x', encoding='utf-8') as handle:
            handle.write(json.dumps({'args': args, 'exitCode': result.returncode, 'seconds': seconds})
                         + f'\n{result.stdout}\n--- stderr ---\n{result.stderr}')
        return result

    def tsx(self, name: str, script: str, *args: str) -> subprocess.CompletedProcess:
        """Run one TypeScript command with the launcher's Node."""
        return self.run(name, [self.node, '--import', 'tsx', script, *args])


def new_fixture(root: Path) -> Fixture:
    """Create a new canonical root; an existing root is never reused or overwritten."""
    require(root.is_absolute(), 'fixture root must be absolute')
    root.parent.mkdir(parents=True, exist_ok=True)
    real_directory(root.parent)
    for name in ('', 'logs', 'extract', 'plans', 'projects', 'preflight'):
        (root / name).mkdir()
    return Fixture(root, local_environment()[0]['node'])


def extract(fixture: Fixture, source: Path) -> Path:
    """Retry only live heavy-lane contention; every other failure stops the fixture."""
    for attempt in range(1, ATTEMPTS + 1):
        base, started = fixture.root / 'extract' / f'attempt-{attempt}', time.monotonic()
        passed = run_owner(base, source)
        fixture.timings.append({'step': f'extract-{attempt}', 'seconds': round(time.monotonic() - started, 3)})
        if passed:
            return base / 'media' / 'fixture-result.json'
        receipt = bound_json(base / 'media' / 'extract.render.json')
        require(BUSY in str(receipt.get('abortReason')), f'extract failed; inspect {base}')
        time.sleep(BACKOFF)
    raise RuntimeError('the shared heavy lane stayed busy for every extract attempt')


def outcome(result: subprocess.CompletedProcess) -> dict:
    """Keep the exit code, the final JSON line's scalar fields and any error tail."""
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    try:
        value = json.loads(lines[-1]) if lines else {}
    except json.JSONDecodeError:
        value = {'text': lines[-1][:400]}
    rows = value.items() if isinstance(value, dict) else ()
    scalars = {key: item for key, item in rows if isinstance(item, (str, int, float, bool))}
    return {'exitCode': result.returncode, **scalars,
            **({'stderrTail': result.stderr[-800:]} if result.returncode else {})}


def retire_busy(fixture: Fixture, project: Path, built: subprocess.CompletedProcess) -> None:
    """Move aside a lease-refused media preparation; any other build failure is final."""
    sources = project.with_name(f'{project.name}.sources')
    receipt = sources / 'package/run/selected-sources.render.json'
    reason = str(bound_json(receipt).get('abortReason')) if receipt.is_file() else ''
    require(not project.exists() and BUSY in built.stdout + built.stderr + reason,
            f'{project.name} build failed; see {fixture.root / "logs"}')
    retired = fixture.root / 'logs' / 'retired-attempts'
    retired.mkdir(exist_ok=True)
    if sources.exists():
        shutil.move(str(sources), str(retired / f'{sources.name}-{len(list(retired.iterdir())) + 1}'))


def build_variant(fixture: Fixture, variant: str) -> dict:
    """Author, then build through native-short.ts; only good prepares (and may wait for) media."""
    authored = fixture.tsx(f'author-{variant}', BUILDER, 'author', str(fixture.root), variant)
    require(authored.returncode == 0, f'{variant} authoring failed; see logs/author-{variant}.log')
    summary = bound_json(fixture.root / 'plans' / f'{variant}.summary.json')
    project = fixture.root / 'projects' / variant
    for attempt in range(1, ATTEMPTS + 1):
        built = fixture.tsx(f'build-{variant}-{attempt}', NATIVE_SHORT, 'build', summary['plan'], str(project))
        if built.returncode == 0:
            prepared = bound_json(project / 'SHORT-PROJECT.json')['preparedSources']
            return {**summary, 'project': str(project), 'preparedSources': prepared, 'build': outcome(built),
                    'buildAttempts': attempt}
        retire_busy(fixture, project, built)
        time.sleep(BACKOFF)
    raise RuntimeError(f'{variant} build stayed blocked by the shared heavy lane')


def findings(output: Path) -> dict:
    """Summarize the SDK totals and dependency findings retained by one preflight attempt."""
    report = output / 'result.json'
    if not report.is_file():
        return {'resultPresent': False}
    sdk = bound_json(report)['sdk']
    rows = [{key: row[key] for key in ('file', 'code', 'reference')} for row in sdk['dependencyFindings']]
    return {'resultPresent': True, 'dependencyFindings': rows,
            **{key: sdk['result'][key] for key in ('totalErrors', 'totalWarnings', 'totalInfos')}}


def verify_variant(fixture: Fixture, variant: str, record: dict) -> dict:
    """Run check, check-export and static preflight; compare exits with the variant's purpose."""
    project = record['project']
    check = outcome(fixture.tsx(f'check-{variant}', NATIVE_SHORT, 'check', project))
    export = outcome(fixture.tsx(f'check-export-{variant}', NATIVE_SHORT, 'check-export', project))
    output = fixture.root / 'preflight' / variant
    preflight = outcome(fixture.run(f'preflight-{variant}', [sys.executable, '-B', PREFLIGHT, project,
                                                             '--output-dir', str(output)]))
    preflight.update(expectedExitCode=EXPECTED_PREFLIGHT[variant], output=str(output), **findings(output))
    met = check['exitCode'] == 0 and export['exitCode'] == 0 and preflight['exitCode'] == EXPECTED_PREFLIGHT[variant]
    return {**record, 'check': check, 'checkExport': export, 'preflight': preflight, 'expectationsMet': met}


def source_extract(staged: dict, result_file: Path) -> dict:
    """Describe the supervised extract, its worker receipt and the staged fixture copy."""
    result, source = bound_json(result_file), staged['source']
    return {'path': source['path'], 'sha256': source['sha256'], 'assetFile': source['file'],
            'origin': source['origin'], 'workerResult': str(result_file), 'workerResultSha256': file_hash(result_file),
            'workerOwner': str(result_file.with_name('extract.render.json')), 'originalSource': result['source'],
            'keyframe': result['keyframe'], 'cutStart': result['cutStart'], 'references': result['references'],
            **{key: value for key, value in result['extract'].items() if key not in {'path', 'sha256'}}}


def write_fixture(fixture: Fixture, result_file: Path, variants: dict) -> bool:
    """Publish FIXTURE.json once; it records TEST scope and never grants any authority."""
    staged, passed = bound_json(fixture.root / 'inputs' / 'STAGED.json'), all(
        row['expectationsMet'] for row in variants.values())
    document = {'schemaVersion': 1, 'scope': 'TEST-native-route-canary-fixture',
                'status': 'fixture-ready' if passed else 'fixture-expectations-failed',
                'productionAuthority': False, 'humanApproved': False, 'checkout': str(REPO),
                'editorialRecords': 'synthetic TEST data; no review, playback, listening or approval occurred',
                'design': staged['design'], 'sourceExtract': source_extract(staged, result_file),
                'variants': variants, 'timings': fixture.timings}
    with (fixture.root / 'FIXTURE.json').open('x', encoding='utf-8') as handle:
        json.dump(document, handle, indent=2)
        handle.write('\n')
    return passed


def build(root: Path, source: Path) -> int:
    """Regenerate every fixture artifact under a new root; nonzero on an unmet expectation."""
    fixture = new_fixture(root)
    result = extract(fixture, source)
    staged = fixture.tsx('stage', BUILDER, 'stage', str(fixture.root), str(result))
    require(staged.returncode == 0, 'staging failed; see logs/stage.log')
    variants = {name: build_variant(fixture, name) for name in EXPECTED_PREFLIGHT}
    variants = {name: verify_variant(fixture, name, row) for name, row in variants.items()}
    passed = write_fixture(fixture, result, variants)
    print(json.dumps({'status': 'fixture-ready' if passed else 'failed', 'fixture': str(fixture.root / 'FIXTURE.json')}))
    return 0 if passed else 1


def main() -> None:
    """Expose the regeneration command and the supervised extract worker."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('build', 'worker'))
    parser.add_argument('path', type=Path)
    parser.add_argument('--source', type=Path, default=SOURCE, help='admitted IMG_5954 original')
    args = parser.parse_args()
    if args.operation == 'worker':
        worker(bound_json(args.path.absolute()))
        return
    raise SystemExit(build(args.path.absolute(), args.source.resolve(strict=True)))


if __name__ == '__main__':
    use_private_budget_root()  # private budget authority; the host pool stays real
    main()
