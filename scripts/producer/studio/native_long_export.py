"""Export a declared native long project with reusable stages and early seam checks."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audio.mastering_profile import MASTERING_PROFILE_IDENTITIES, NATIVE_SHORT_MASTERING_PROFILE
from cut_preview_io import real_directory, write_new
from studio.native_long_contract import read_long_plan, sample_frame_count
from studio.native_preflight_inputs import inventory
from studio.native_run import utc
from studio.native_run_config import local_environment
from studio.native_runtime import REPO, digest, install_runtime
from studio.native_short_pipeline import NativeShortPipeline
from studio.native_long_autoresume import recover_automatically, resume_request
from studio.native_long_prebuild import require_long_prebuild, review_implementation_files
from studio.native_export import export_adapter
from studio.native_export_history import register_attempt, attempt_reservation


def implementation_pins(project: Path, runtime: Path, tools: dict) -> dict:
    """Bind the existing shared owners, audio/QC modules and native runtime closure."""
    files, _directories = inventory(project)
    producer = REPO / 'scripts/producer'
    files += [file for file in producer.rglob('*.py') if 'tests' not in file.parts]
    files += list((producer / 'studio').glob('*.mjs'))
    files += list((producer / 'studio/runtime').glob('*.mjs'))
    files.append(producer / 'studio/runtime/patches.json')
    files += [runtime / 'dist' / name for name in ('cli.js', 'native-capture-library.mjs',
              'hyperframe.runtime.iife.js', 'hyperframe.manifest.json', 'frame-source-transport.mjs',
              'native-render-sdk.mjs', 'native-export-guard.mjs')]
    files += [Path(value).resolve(strict=True) for value in tools.values()]
    files += [Path(sys.executable).resolve(strict=True), producer / 'studio/native_localhost_only.sb']
    files += review_implementation_files()
    from graphics.visual_source_project import source_implementation_files
    files += source_implementation_files()
    return {str(file): digest(file) for file in set(files) if file.is_file()}


def prepare(args: argparse.Namespace) -> tuple[dict, dict]:
    """Reject incompatible options and unsafe paths before output or media work."""
    project, output = args.project.resolve(strict=True), args.output.absolute()
    real_directory(project)
    real_directory(output.parent)
    if output.exists() or output.is_symlink() or output.is_relative_to(project) or project.is_relative_to(output):
        raise ValueError('Long export requires a new output directory outside the authored project')
    if args.resume_from and (args.prepared_master or args.audio_donor or args.cache
                            or args.audio_profile != NATIVE_SHORT_MASTERING_PROFILE.identity):
        raise ValueError('Resume preserves the original audio policy, evidence and cache; omit overrides')
    plan = read_long_plan(project)
    if export_adapter(project) != 'native-long':
        raise ValueError('Expected the native long export contract')
    tools, environment = local_environment()
    reviewed = require_long_prebuild(project, tools, environment)
    runtime = install_runtime()
    cache = args.cache.resolve() if args.cache else runtime.parent / 'long-frame-cache'
    cache.mkdir(parents=True, exist_ok=True)
    real_directory(cache)
    request = {'schemaVersion': 1, 'adapter': 'native-long', 'project': str(project), 'output': str(output),
        'runtime': str(runtime), 'cache': str(cache), 'tools': tools, 'captureMode': 'sdk-streaming',
        'sourceCacheMode': 'native-long', 'audioProfile': args.audio_profile, 'audioDonor': None,
        'pictureDonor': None, 'preparedMaster': None, 'pins': implementation_pins(project, runtime, tools),
        'budget': plan['budget'], 'sampleCount': sample_frame_count(plan)}
    for file, sha in reviewed['pins'].items():
        if file in request['pins'] and request['pins'][file] != sha:
            raise ValueError('Reviewed long project changed before export pinning')
    request['pins'].update(reviewed['pins'])
    request['prebuildReview'] = {key: value for key, value in reviewed.items() if key != 'pins'}
    if reviewed.get('referenceMap'):
        request['referenceMap'] = reviewed['referenceMap']
    with attempt_reservation(request):
        request = select_and_publish(args, request)
    return request, environment


def select_and_publish(args: argparse.Namespace, request: dict) -> dict:
    """Choose compatible stages and register a new attempt under the project reservation."""
    if args.resume_from:
        attempt = args.resume_from.resolve(strict=True)
        request = resume_request(request, attempt)
    else:
        add_audio_reuse(args, request)
        if not args.prepared_master and not args.audio_donor and not getattr(args, "preview_only", False) and getattr(args, "preview_reviews", None):
            request = recover_automatically(request)
    from studio.native_motion_previews import bind_preview_options
    request = bind_preview_options(request, args)
    output = Path(request['output'])
    output.mkdir(mode=0o700)
    write_new(output / 'export-request.json', request)
    register_attempt(request)
    return request


def add_audio_reuse(args: argparse.Namespace, request: dict) -> None:
    """Keep explicit audio-only reuse available even after a failed picture attempt."""
    for key, value in (('preparedMaster', args.prepared_master), ('audioDonor', args.audio_donor)):
        if value is None:
            continue
        receipt = value.resolve(strict=True)
        request[key] = str(receipt)
        files = [receipt, receipt.parent / 'program-master.wav']
        if key == 'audioDonor':
            files.append(receipt.parent / 'candidate.mp4')
        request['pins'].update({str(file): digest(file) for file in files})


def main() -> None:
    """One invocation, truthful durable status, preserved failed attempts and no providers."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--cache', type=Path)
    parser.add_argument('--resume-from', type=Path)
    reuse = parser.add_mutually_exclusive_group()
    reuse.add_argument('--prepared-master', type=Path, help='Reuse a checked float master after a picture-only change/failure')
    reuse.add_argument('--audio-donor', type=Path, help='Reuse checked AAC; all final audio and picture checks still run')
    parser.add_argument('--audio-profile', choices=MASTERING_PROFILE_IDENTITIES,
                        default=NATIVE_SHORT_MASTERING_PROFILE.identity)
    from studio.native_motion_previews import preview_options
    preview_options(parser)
    args = parser.parse_args()
    began = time.monotonic(), utc()
    request, environment = prepare(args)
    print(json.dumps({'status': 'prepared-awaiting-resource-admission', 'budget': request['budget']}), flush=True)
    success = NativeShortPipeline(request, environment).execute(invocation=began)
    raise SystemExit(0 if success else 1)


if __name__ == '__main__':
    main()
