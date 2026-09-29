"""TEST performance fixture: a dense-caption, six-view native Short from a real IMG_5954 extract.

``python3 -B scripts/producer/tests/native_perf_fixture.py build <new-root>`` (through the
launcher, cwd = checkout) builds a project shaped like audited clip E: 1,369 frames at 30 fps,
six sequential 1080p picture views and 187 native caption words in 69 phrases. A supervised
NativeRun worker stream-copies the IMG_5954 HEVC Main10 HLG packet run covering E's six cuts;
``native_perf_fixture.ts`` re-times E's canvas onto that extract with a built-in title card and
explicitly synthetic TEST editorial records; the supported ``native-short.ts`` build, check and
check-export commands and ``native_preflight.py`` build and check it. The design follows the
route-canary fixture. It measures route cost only: never production, editorial, listening,
playback or delivery authority. Catalog titles and visual-plan application are not exercised.
"""
from __future__ import annotations

import argparse
import json
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
PRODUCTION = Path('/Users/aaronfigueroa/development/demos/YT-Automation/outputs/project-sniper-release-rc4-work/'
                  'qualification-catalog-preview-e7be8ee/project-sniper-0.1.0-rc4/projects/img-5954-walkthrough')
SOURCE = PRODUCTION / 'source/.sniper-external-media/51bab3f0259ce16dbb7835310ef512f056d7d08d229060fcf142e6ac342d7c08.media'
SOURCE_SHA = '51bab3f0259ce16dbb7835310ef512f056d7d08d229060fcf142e6ac342d7c08'
SHAPE = PRODUCTION / 'production/E/native-plan-v6.json'
SHAPE_SHA = '35634ea22cf86f9b5da14a0a2fffa29e186539371c7be952c39c744128b30484'
KEYFRAME_BOUND, EXTRACT_END = Fraction('389.8'), Fraction('657')
REFERENCES = (('TEST-reference-open.jpg', '2'), ('TEST-reference-end.jpg', '250'))
BUSY, ATTEMPTS, BACKOFF = 'already active', 8, 60
NATIVE_SHORT, PREFLIGHT = 'scripts/producer/native-short.ts', 'scripts/producer/studio/native_preflight.py'
VIDEO_FACTS = ('codec_name', 'profile', 'pix_fmt', 'width', 'height', 'color_range', 'color_space',
               'color_transfer', 'color_primaries', 'codec_tag_string', 'r_frame_rate', 'start_time')


def extract_media(source: Path, output: Path, tools: dict) -> tuple[Path, Fraction, list[dict]]:
    """Stream-copy HEVC HLG packets from the latest keyframe before E's first cut; AAC audio."""
    inventory = packets(source, tools, (KEYFRAME_BOUND - 20, EXTRACT_END + 5))
    keys = [row['ptsTime'] for row in inventory if 'K' in row['flags'] and row['ptsTime'] <= KEYFRAME_BOUND]
    require(bool(keys), 'no IMG_5954 video keyframe precedes the fixture bound')
    keyframe, target = max(keys), output / 'source.mp4'
    command([tools['ffmpeg'], '-nostdin', '-v', 'error', '-xerror', '-n', '-ss', decimal(keyframe),
             '-i', str(source), '-t', decimal(EXTRACT_END - keyframe), '-map', '0:v:0', '-map', '0:a:0',
             '-c:v', 'copy', '-tag:v', 'hvc1', '-c:a', 'aac', '-b:a', '320k', '-ar', '48000', '-ac', '2',
             '-aac_pns', '0', '-map_metadata', '-1', '-map_chapters', '-1', '-movflags', '+faststart',
             str(target)], timeout=600)
    return target, keyframe, inventory


def verify_extract(target: Path, tools: dict, source: dict) -> dict:
    """Prove unchanged zero-based HEVC 10-bit HLG packets beside zero-based 48 kHz stereo AAC."""
    info = media_info(target, tools)
    video, audio = info['video'], info['audio'] or {}
    wanted = {'codec_name': 'hevc', 'pix_fmt': 'yuv420p10le', 'color_transfer': 'arib-std-b67', 'codec_tag_string': 'hvc1'}
    require(all(video.get(key) == value for key, value in wanted.items()), 'extract is not hvc1 HEVC 10-bit HLG')
    require(audio.get('codec_name') == 'aac' and audio.get('channels') == 2, 'extract audio is not stereo AAC')
    verify_picture_metadata(target, tools, source['info']['video'])
    selected = packets(target, tools)
    require(selected[0]['ptsTime'] == 0 and packet_origin(source['packets'], selected) == source['keyframe'],
            'extract picture is not the exact source packet run from its keyframe at zero')
    command([tools['ffmpeg'], '-nostdin', '-v', 'error', '-xerror', '-i', str(target), '-f', 'null', '-'], timeout=600)
    return {'video': {key: video.get(key) for key in VIDEO_FACTS},
            'audio': {key: audio.get(key) for key in ('codec_name', 'sample_rate', 'channels', 'start_time')},
            'videoPackets': len(selected), 'presentableFrames': sum(row['ptsTime'] >= 0 for row in selected),
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
    target, keyframe, inventory = extract_media(source, output, tools)
    facts = verify_extract(target, tools, {'info': media_info(source, tools), 'packets': inventory, 'keyframe': keyframe})
    write_new(output / 'fixture-result.json', {
        'status': 'fixture-complete', 'scope': 'TEST-native-perf-extract', 'productionDelivery': False,
        'humanApproved': False, 'source': {'path': str(source), 'sha256': request['sourceSha256']},
        'keyframe': {'rational': str(keyframe), 'seconds': decimal(keyframe), 'bound': decimal(KEYFRAME_BOUND)},
        'extract': {'path': str(target), 'sha256': file_hash(target), 'bytes': target.stat().st_size, **facts},
        'references': reference_frames(target, output, tools)})


def run_owner(base: Path, source: Path) -> bool:
    """Launch one extract attempt beneath the unchanged shared heavy-work owner."""
    control, output = base / 'control', base / 'media'
    for directory in (base, control, output):
        directory.mkdir(mode=0o700)
    (control / 'TEST.txt').write_text('TEST performance-fixture extract control; no production or human approval.\n')
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
        additional_pins=pins, success_status='test-perf-extract-complete', capacity_wait_seconds=300)
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
        result = subprocess.run(args, cwd=REPO, capture_output=True, text=True, timeout=1800, check=False)
        seconds = round(time.monotonic() - started, 3)
        self.timings.append({'step': name, 'seconds': seconds, 'exitCode': result.returncode})
        with (self.root / 'logs' / f'{name}.log').open('x', encoding='utf-8') as handle:
            handle.write(json.dumps({'args': args, 'exitCode': result.returncode, 'seconds': seconds})
                         + f'\n{result.stdout}\n--- stderr ---\n{result.stderr}')
        return result

    def tsx(self, name: str, script: str, *args: str) -> subprocess.CompletedProcess:
        """Run one TypeScript command with the launcher's Node."""
        return self.run(name, [self.node, '--import', 'tsx', script, *args])


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
    return {'exitCode': result.returncode, **scalars, **({'stderrTail': result.stderr[-800:]} if result.returncode else {})}


def build_project(fixture: Fixture) -> dict:
    """Author, then build through native-short.ts; media preparation may wait for the heavy lane."""
    authored = fixture.tsx('author', BUILDER, 'author', str(fixture.root), str(SHAPE))
    require(authored.returncode == 0, 'authoring failed; see logs/author.log')
    summary = bound_json(fixture.root / 'plans' / 'dense.summary.json')
    project = fixture.root / 'projects' / 'dense'
    for attempt in range(1, ATTEMPTS + 1):
        built = fixture.tsx(f'build-{attempt}', NATIVE_SHORT, 'build', summary['plan'], str(project))
        if built.returncode == 0:
            return {**summary, 'project': str(project), 'build': outcome(built), 'buildAttempts': attempt}
        sources = project.with_name('dense.sources')
        receipt = sources / 'package/run/selected-sources.render.json'
        reason = str(bound_json(receipt).get('abortReason')) if receipt.is_file() else ''
        require(not project.exists() and BUSY in built.stdout + built.stderr + reason, 'build failed; see logs/')
        if sources.exists():
            sources.rename(fixture.root / 'logs' / f'retired-sources-{attempt}')
        time.sleep(BACKOFF)
    raise RuntimeError('fixture build stayed blocked by the shared heavy lane')


def verify_project(fixture: Fixture, record: dict) -> dict:
    """Run check, check-export and static preflight; all must pass for a usable fixture."""
    project = record['project']
    check = outcome(fixture.tsx('check', NATIVE_SHORT, 'check', project))
    export = outcome(fixture.tsx('check-export', NATIVE_SHORT, 'check-export', project))
    output = fixture.root / 'preflight'
    preflight = outcome(fixture.run('preflight', [sys.executable, '-B', PREFLIGHT, project, '--output-dir', str(output)]))
    met = check['exitCode'] == 0 and export['exitCode'] == 0 and preflight['exitCode'] == 0
    return {**record, 'check': check, 'checkExport': export, 'preflight': preflight, 'expectationsMet': met}


def build(root: Path, source: Path) -> int:
    """Regenerate the fixture under a new root; nonzero on an unmet expectation."""
    require(root.is_absolute(), 'fixture root must be absolute')
    root.parent.mkdir(parents=True, exist_ok=True)
    real_directory(root.parent)
    for name in ('', 'logs', 'extract', 'plans', 'projects'):
        (root / name).mkdir()
    fixture = Fixture(root, local_environment()[0]['node'])
    require(digest(SHAPE) == SHAPE_SHA, 'the audited clip E canvas changed')
    result = extract(fixture, source)
    staged = fixture.tsx('stage', BUILDER, 'stage', str(root), str(result))
    require(staged.returncode == 0, 'staging failed; see logs/stage.log')
    record = verify_project(fixture, build_project(fixture))
    document = {'schemaVersion': 1, 'scope': 'TEST-native-perf-fixture',
                'status': 'fixture-ready' if record['expectationsMet'] else 'fixture-expectations-failed',
                'productionAuthority': False, 'humanApproved': False, 'checkout': str(REPO),
                'editorialRecords': 'synthetic TEST data; no review, playback, listening or approval occurred',
                'shape': {'path': str(SHAPE), 'sha256': SHAPE_SHA}, 'extractResult': str(result),
                'extractResultSha256': file_hash(result), 'project': record, 'timings': fixture.timings}
    with (root / 'PERF-FIXTURE.json').open('x', encoding='utf-8') as handle:
        json.dump(document, handle, indent=2)
        handle.write('\n')
    print(json.dumps({'status': document['status'], 'fixture': str(root / 'PERF-FIXTURE.json')}))
    return 0 if record['expectationsMet'] else 1


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
