"""Export an assembled native Short locally, with source, audio and picture QC."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audio.mastering_profile import MASTERING_PROFILE_IDENTITIES, NATIVE_SHORT_MASTERING_PROFILE
from audio.dialogue_cleanup import cleanup_model_binding
from audio.native_audio_finishing import native_finishing_request
from cut_preview_io import real_directory, write_new
from studio.native_run_config import local_environment
from studio.native_runtime import REPO, digest, install_runtime
from studio.native_short_delivery import clock
from studio.native_short_pipeline import NativeShortPipeline
from studio.native_short_resume import prepare_reverification
from studio.native_run import utc


def assert_admitted_pins(project: Path, plan: dict, manifest: dict, pins: dict) -> None:
    """A changed admitted file cannot become a new accepted hash while pins are collected."""
    expected = [(str(project / row['file']), row['sha256']) for row in manifest['files']]
    expected += [(asset['path'], asset['sha256']) for asset in plan['assets']]
    if plan['strategy']['schemaVersion'] >= 3:
        report = json.loads((project / 'ASSET-USE-REPORT.json').read_text())
        expected += [(row['path'], row['sha256']) for row in report['originEvidenceFiles']]
    if plan.get('requestPacket'):
        request = plan['requestPacket']
        expected.append((request['path'], request['sha256']))
        packet = json.loads(Path(request['path']).read_text())
        expected += [(row['transcript']['path'], row['transcript']['sha256'])
                     for row in packet['sources'] if row.get('transcript')]
        expected += [(row['path'], row['sha256']) for row in packet.get('availableSupportingAssets', [])
                     if row.get('sha256')]
    for filename, expected_hash in expected:
        if pins.get(filename) != expected_hash:
            raise ValueError(f'Admitted native export input changed before pinning: {filename}')


def input_pins(project: Path, runtime: Path, tools: dict) -> dict[str, str]:
    """Bind source bytes and the shared implementation used for this attempt."""
    manifest = json.loads((project / 'PROJECT-MANIFEST.json').read_text())
    paths = [project / row['file'] for row in manifest['files']]
    paths.append(project / 'PROJECT-MANIFEST.json')
    plan = json.loads((project / 'SHORT-PROJECT.json').read_text())
    paths += [Path(asset['path']) for asset in plan['assets']]
    if plan['strategy']['schemaVersion'] >= 3:
        asset_use = json.loads((project / 'ASSET-USE-REPORT.json').read_text())
        paths += [Path(row['path']) for row in asset_use['originEvidenceFiles']]
    for asset in plan['assets']:
        if asset.get('webCapture'):
            paths += [Path(asset['webCapture'][key]) for key in ('path', 'supervisionPath')]
    if plan.get('requestPacket'):
        packet_path = Path(plan['requestPacket']['path'])
        paths.append(packet_path)
        packet = json.loads(packet_path.read_text())
        paths += [Path(row['transcript']['path']) for row in packet['sources'] if row.get('transcript')]
        paths += [Path(row['path']) for row in packet.get('availableSupportingAssets', [])]
    paths += [Path(value) for value in tools.values()]
    paths += list(Path(__file__).parent.glob('native_*.*'))
    paths += list(Path(__file__).parent.parent.glob('native_render_*.py'))
    paths += list((REPO / 'src/lib/server').glob('native-*.ts'))
    paths += list((REPO / 'src/lib/server').glob('guided-native-*.ts'))
    paths += [REPO / 'scripts/producer/native-short.ts', REPO / 'src/lib/producer/short-direction.ts']
    paths += [REPO / 'src/app/api/producer/ai-edit/caption-text-contract-v1.ts']
    paths += list((REPO / 'src/lib/producer/contracts').glob('*.ts'))
    paths += [runtime / 'dist' / name for name in ('cli.js', 'native-capture-library.mjs',
              'hyperframe.runtime.iife.js', 'hyperframe.manifest.json', 'frame-source-transport.mjs')]
    paths += list((REPO / 'scripts/producer/audio').glob('*.py'))
    paths += list((REPO / 'scripts/producer/audit').glob('*.py'))
    samples = clock(plan['canvas']).sample_at_frame(plan['canvas']['totalFrames'])
    finishing = native_finishing_request(plan.get('audioFinishing'), samples)
    model = cleanup_model_binding(finishing.enhance_chain) if finishing else None
    if model:
        paths.append(Path(model['path']))
    paths += [REPO / 'scripts/producer' / name for name in (
        'producer_config.py', 'fingerprints.py', 'cut_preview_io.py', 'native_work_lease.py',
        'headless/durable_files.py', 'headless/process_runner.py', 'graphics/render_tools.py',
        'edit/exact_timing.py', 'stage_timing.py', 'palmier/process_deadline.py')]
    paths.append(Path(sys.executable).resolve())
    pins = {str(file): digest(file) for file in set(paths) if file.is_file()}
    assert_admitted_pins(project, plan, manifest, pins)
    return pins


def prepare(args: argparse.Namespace) -> tuple[dict, dict]:
    """Require the same shared project reader used by local assembly before heavy work."""
    cache_mode = source_cache_mode(args)
    project, output = args.project.resolve(strict=True), args.output.absolute()
    validate_options(args, project, output)
    tools, environment = local_environment()
    subprocess.run([tools['node'], '--import', 'tsx', str(REPO / 'scripts/producer/native-short.ts'),
                    'check', str(project)], cwd=REPO, env=environment, check=True, timeout=60)
    canvas = json.loads((project / 'SHORT-PROJECT.json').read_text())['canvas']
    rate = clock(canvas).fps.fraction
    if not 1 <= rate <= 60 or not 0 < canvas['totalFrames'] / rate <= 180:
        raise ValueError('Native Short export supports explicit 1–60 fps timelines up to 180 seconds')
    runtime = install_runtime()
    cache = args.cache.resolve() if args.cache else runtime.parent / 'frame-cache'
    cache.mkdir(parents=True, exist_ok=True)
    pins = input_pins(project, runtime, tools)
    request = {'schemaVersion': 1, 'project': str(project), 'output': str(output),
               'runtime': str(runtime), 'cache': str(cache), 'tools': tools,
               'captureMode': 'cached-native-batches' if args.cached_native_batches else 'sdk-streaming',
               'sourceCacheMode': cache_mode,
               'audioProfile': args.audio_profile,
               'pictureDonor': None, 'pins': pins, 'audioDonor': None}
    if getattr(args, 'verify_from', None):
        request = prepare_reverification(request, args.verify_from.absolute())
    else:
        add_donors(args, request)
    output.mkdir(mode=0o700)
    return request, environment


def validate_options(args: argparse.Namespace, project: Path, output: Path) -> None:
    """Reject incompatible recovery options and unsafe destinations before expensive work."""
    real_directory(output.parent)
    if output.exists() or output.is_symlink() or output.is_relative_to(project) \
            or project.is_relative_to(output):
        raise ValueError('Export needs a new directory outside the authored project')
    if getattr(args, 'verify_from', None) and any((args.cache, args.audio_donor,
            args.picture_donor, args.cached_native_batches, args.acquire_source_cache,
            args.audio_profile != NATIVE_SHORT_MASTERING_PROFILE.identity,
            getattr(args, 'render_only', False))):
        raise ValueError('--verify-from preserves the sealed route, cache and audio policy; omit render options')
    if args.picture_donor and not args.cached_native_batches:
        raise ValueError('Picture reuse requires the explicit cached native batch route')


def add_donors(args: argparse.Namespace, request: dict) -> None:
    """Reuse the existing independently qualified picture and AAC donor contracts."""
    if args.audio_donor:
        donor = args.audio_donor.resolve(strict=True)
        request['audioDonor'] = str(donor)
        request['pins'][str(donor)] = digest(donor)
    if args.picture_donor:
        from studio.native_short_picture_reuse import picture_reuse_pins
        donor = args.picture_donor.resolve(strict=True)
        request['pictureDonor'] = str(donor)
        request['pins'].update(picture_reuse_pins(Path(request['project']), donor))


def source_cache_mode(args: argparse.Namespace) -> str:
    """Cold extraction is opt-in and cannot silently change the selected picture route."""
    if not getattr(args, 'acquire_source_cache', False):
        return 'existing-only'
    if not args.cached_native_batches:
        raise ValueError('Source cache acquisition requires --cached-native-batches')
    return 'acquire-sequential-sdr'


def execute(args: argparse.Namespace) -> bool:
    """Separate reusable media generation from independently owned complete verification."""
    invocation = (time.monotonic(), utc())
    request, environment = prepare(args)
    output = Path(request['output'])
    request_file = output / 'export-request.json'
    write_new(request_file, request)
    pipeline = NativeShortPipeline(request, environment, args.unused_ram_advisory)
    return pipeline.execute(args.render_only, invocation)


def main() -> None:
    """One explicit output attempt; failed directories are preserved for diagnosis."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--cache', type=Path)
    stage = parser.add_mutually_exclusive_group()
    stage.add_argument('--render-only', action='store_true',
                       help='Seal completed media for later verification; does not qualify delivery')
    stage.add_argument('--verify-from', type=Path,
                       help='Verify a sealed render-stage.json in a new directory without re-encoding')
    parser.add_argument('--audio-donor', type=Path)
    parser.add_argument('--audio-profile', choices=MASTERING_PROFILE_IDENTITIES, default=NATIVE_SHORT_MASTERING_PROFILE.identity,
                        help='Explicit delivery profile; audio reuse also requires the current recorded AAC encoding policy')
    parser.add_argument('--picture-donor', type=Path,
                        help='Reuse a verified completed batch picture stage; all final audio/picture QC still runs')
    parser.add_argument('--cached-native-batches', action='store_true',
                        help='Opt-in bounded native browser sessions; exact existing source-frame cache required')
    parser.add_argument('--acquire-source-cache', action='store_true',
                        help='With cached batches, acquire exact original-size SDR source PNGs sequentially through the pinned SDK')
    parser.add_argument('--unused-ram-advisory', action='store_true',
                        help='Explicit operator-authorized Short exception; all live tree/swap caps remain')
    args = parser.parse_args()
    raise SystemExit(0 if execute(args) else 1)


if __name__ == '__main__':
    main()
