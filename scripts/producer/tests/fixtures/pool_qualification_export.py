"""TEST stand-in for studio/native_export.py used only by harness tests.

Usage: <project> <attempt> --test-root DIR --test-record DIR --pattern NAME [--tone HZ]
[--hold SECONDS] [--preview] [--cache-outcome OUTCOME] [--own-audio [--audio-hold SECONDS]]
[--prepared-audio]. It runs one real NativeRun owner (production admission, sampling and
cleanup) whose child encodes a small deterministic TEST clip with ffmpeg, then writes TEST
checks/delivery receipts shaped like the exporter's, plus a TEST source-cache receipt whose
entries carry OUTCOME (default 'published-by-this-job', a cold cache). --own-audio first
runs a real 'audio'-class 'audio-stage' owner in <attempt>/audio-stage, as the exporter's
own audio stage does; --prepared-audio records an imported (prepared) stage instead. It is
never a production exporter and its receipts are not media qualification.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path[:0] = [str(HERE.parents[2]), str(HERE.parents[1]), str(HERE.parent)]

from native_pool_driver import isolate  # noqa: E402


def child_command(ffmpeg: str, output: Path, args: argparse.Namespace) -> list[str]:
    """Encode two seconds of a lavfi pattern and tone bit-exactly, then hold."""
    encode = [ffmpeg, '-nostdin', '-v', 'error', '-n', '-f', 'lavfi', '-i',
              f'{args.pattern}=size=320x240:rate=30:duration=2', '-f', 'lavfi', '-i',
              f'sine=frequency={args.tone}:duration=2', '-map', '0:v', '-map', '1:a',
              '-c:v', 'libx264', '-threads', '1', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
              '-c:a', 'aac', '-fflags', '+bitexact', '-flags:v', '+bitexact', '-flags:a', '+bitexact',
              '-map_metadata', '-1', '-f', 'mp4', str(output)]
    script = ' '.join(f"'{part}'" for part in encode) + f' && sleep {args.hold}'
    return ['/bin/sh', '-c', script]


def main() -> None:
    """Run the TEST export and publish exporter-shaped receipts."""
    parser = argparse.ArgumentParser()
    for name in ('project', 'attempt'):
        parser.add_argument(name, type=Path)
    for name, default in (('--test-root', None), ('--test-record', '-'), ('--pattern', 'testsrc2'),
                          ('--tone', '440'), ('--hold', '3'), ('--cache-outcome', 'published-by-this-job'),
                          ('--audio-hold', '4')):
        parser.add_argument(name, default=default, required=default is None)
    for flag in ('--preview', '--own-audio', '--prepared-audio'):
        parser.add_argument(flag, action='store_true')
    args = parser.parse_args()
    isolate(args.test_root, args.test_record)
    from cut_preview_io import write_new
    from graphics.render_tools import resolve_tools
    from studio.native_run import NativeRun
    from studio.native_run_config import NativeRunConfig
    from studio.native_runtime import digest
    attempt = args.attempt
    attempt.mkdir(mode=0o700)
    ffmpeg = resolve_tools()['ffmpeg']
    review = attempt / ('clip.mp4' if args.preview else 'review.mp4')
    # The owner writes a non-video name: a TEST plan makes the project native, and the shared
    # export launch check (rightly) sends native video outputs through the real exporter.
    encoded = attempt / 'TEST-encode.bin'
    cli, sandbox = attempt / 'TEST-cli.js', attempt / 'TEST-sandbox.sb'
    cli.write_text('TEST stand-in')
    sandbox.write_text('TEST stand-in')
    settings = NativeRunConfig(args.project, attempt, cli, child_command(ffmpeg, encoded, args),
                               {'PATH': '/usr/bin:/bin'},
                               {'output': str(encoded), 'sdkSha256': digest(cli), 'sandboxSha256': digest(sandbox)},
                               sandbox=sandbox, deadline=300, capacity_wait_seconds=240,
                               success_status='TEST stand-in rendered')
    passed = not args.own_audio or audio_stage(settings, args)
    passed = passed and NativeRun('pipeline', settings).execute()
    if passed:
        encoded.rename(review)
    write_new(attempt / 'export-request.json', {
        'schemaVersion': 1, 'project': str(args.project), 'output': str(attempt), 'tools': {'ffmpeg': ffmpeg},
        'pins': {'TEST-pattern': args.pattern, 'TEST-preview': str(args.preview)},
        'recoverySelection': {'mode': 'fresh'}, 'audioStage': audio_binding(args),
        'scope': 'TEST stand-in export; not media qualification'})
    (attempt / 'native-capture').mkdir()
    write_new(attempt / 'native-capture/source-cache.json', {
        'scope': 'TEST source-cache receipt', 'entries': [{'contentKey': 'TEST-key', 'outcome': args.cache_outcome}]})
    publish(attempt, review, (passed, args.preview), (write_new, digest))
    raise SystemExit(0 if passed else 1)


def audio_binding(args: argparse.Namespace) -> dict | None:
    """The export request's audio-stage binding: own stage, imported TEST stage or none."""
    if args.own_audio:
        return {'mode': 'attempt', 'seal': str(args.attempt / 'audio-stage/TEST-seal.json'), 'sealSha256': None}
    if args.prepared_audio:
        return {'mode': 'explicit', 'seal': '/TEST/prepared/audio-stage.json', 'sealSha256': 'a' * 64}
    return None


def audio_stage(settings: object, args: argparse.Namespace) -> bool:
    """Run one real audio-class owner in <attempt>/audio-stage that holds, then writes a TEST file."""
    from dataclasses import replace
    from studio.native_run import NativeRun
    root = args.attempt / 'audio-stage'
    root.mkdir()
    output = root / 'TEST-audio.bin'
    command = ['/bin/sh', '-c', f"sleep {args.audio_hold} && printf TEST > '{output}'"]
    stage = replace(settings, root=root, command=command, lane='audio', success_status='TEST audio stage prepared',
                    admission={**settings.admission, 'output': str(output)})
    return NativeRun('audio-stage', stage).execute()


def publish(attempt: Path, review: Path, outcome: tuple, helpers: tuple) -> None:
    """Exporter-shaped TEST receipts: checks and delivery, or a moving-preview list."""
    passed, preview = outcome
    write_new, digest = helpers
    if not passed:
        write_new(attempt / 'delivery.json', {'status': 'failed', 'stages': []})
        return
    if preview:
        write_new(attempt / 'motion-previews.json', {'status': 'TEST', 'clips': [{'path': str(review)}]})
        write_new(attempt / 'delivery.json', {'status': 'native-motion-previews-complete', 'stages': []})
        return
    write_new(attempt / 'checks.json', {'status': 'checks-passed-awaiting-owned-cleanup', 'output': str(review),
                                        'sha256': digest(review), 'fullAudioVideoDecodePassed': True,
                                        'elapsedSeconds': 1.0, 'pictureFramesChecked': 60})
    write_new(attempt / 'delivery.json', {'status': 'native-short-checked-for-review', 'output': str(review),
                                          'stages': [{'phase': 'pipeline', 'elapsedSeconds': 1.0}]})


if __name__ == '__main__':
    main()
