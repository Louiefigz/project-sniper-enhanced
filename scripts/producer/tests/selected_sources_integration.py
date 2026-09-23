"""Explicit supervised real-media equivalence check; never part of fast unit tests."""
from __future__ import annotations

import argparse
from fractions import Fraction
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from scipy.io import wavfile

from cut_preview_io import bound_json, file_hash, write_new
from edit.selected_sources import read_package
from edit.selected_sources_media import command, decimal
from studio.native_run import NativeRun
from studio.native_run_config import NativeRunConfig, local_environment
from studio.native_runtime import install_runtime
from studio.native_short_delivery import clock, dialogue_reference
from studio.native_short_export import input_pins
from studio.native_stage_evidence import require


def frame_hashes(request: dict, source: Path, start: Fraction, frames: int) -> list[str]:
    """Decode the exact selected window at the output frame rate, without scaling."""
    raw = command([request['tools']['ffmpeg'], '-nostdin', '-v', 'error', '-xerror',
        '-ss', decimal(start), '-i', str(source), '-map', '0:v:0', '-an',
        '-vf', f"fps={request['canvas']['frameRate']}", '-frames:v', str(frames),
        '-pix_fmt', 'rgb24', '-f', 'framemd5', '-'])
    return [line.split(',')[-1].strip() for line in raw.splitlines() if line and not line.startswith('#')]


def compare_picture(request: dict, plan: dict) -> list[dict]:
    """Compare every decoded output-time source frame, including all cut boundaries."""
    result, _pins = read_package(plan['preparedSources'])
    canvas, project = plan['canvas'], Path(request['project'])
    source = next(Path(row['path']) for row in plan['assets'] if row['file'] == canvas['sourceFile'])
    evidence = []
    for index, (cut, segment) in enumerate(zip(canvas['cuts'], canvas['segments'], strict=True)):
        start = Fraction(str(cut['start']))
        frames = segment['endFrameExclusive'] - segment['startFrame']
        end = start + Fraction(frames, 1) / clock(canvas).fps.fraction
        section = next(row for row in result['sections'] if row['sourceFile'] == canvas['sourceFile']
                       and Fraction(row['video']['sourceStart']) <= start
                       and Fraction(row['video']['sourceEnd']) >= end)
        video = section['video']
        before = frame_hashes(request, source, start, frames)
        after = frame_hashes(request, project / video['file'], start - Fraction(video['sourceOrigin']), frames)
        evidence.append({'cut': index, 'expectedFrames': frames, 'originalFrames': len(before),
                         'preparedFrames': len(after), 'allDecodedFramesIdentical': before == after,
                         'mismatches': [i for i, pair in enumerate(zip(before, after)) if pair[0] != pair[1]][:20]})
    return evidence


def compare_audio(request: dict, plan: dict) -> dict:
    """Compare the complete shared dialogue edit sample-for-sample before mastering."""
    root, project, canvas = Path(request['output']), Path(request['project']), plan['canvas']
    prepared, legacy = root / 'prepared-audio', root / 'original-audio'
    prepared.mkdir(); legacy.mkdir()
    source = next(row['path'] for row in plan['assets'] if row['file'] == canvas['sourceFile'])
    after = dialogue_reference(project, canvas, prepared)
    before = dialogue_reference(legacy, {**canvas, 'sourceFile': source}, legacy)
    rate_before, values_before = wavfile.read(before)
    rate_after, values_after = wavfile.read(after)
    same_shape = values_before.shape == values_after.shape
    return {'originalSampleRate': rate_before, 'preparedSampleRate': rate_after,
            'originalShape': list(values_before.shape), 'preparedShape': list(values_after.shape),
            'allSamplesIdentical': same_shape and np.array_equal(values_before, values_after),
            'maximumAbsoluteSampleDifference': float(np.max(np.abs(values_before - values_after))) if same_shape else None}


def worker(request_path: Path) -> None:
    """Record actual decode comparison even when qualification fails."""
    request = bound_json(request_path)
    plan = bound_json(Path(request['project']) / 'SHORT-PROJECT.json')
    evidence = {'picture': compare_picture(request, plan), 'audio': compare_audio(request, plan)}
    evidence['passed'] = all(row['allDecodedFramesIdentical'] and row['originalFrames'] == row['expectedFrames']
                             for row in evidence['picture']) and evidence['audio']['allSamplesIdentical']
    write_new(Path(request['output']) / 'equivalence.json', evidence)
    require(evidence['passed'], 'selected-source decoded equivalence failed; inspect equivalence.json')


def supervise(project: Path, output: Path) -> bool:
    """Use the production resource guard, process ownership and immutable input closure."""
    project, output = project.resolve(strict=True), output.absolute()
    output.mkdir(mode=0o700)
    tools, environment = local_environment()
    runtime = install_runtime()
    pins = input_pins(project, runtime, tools)
    pins[str(Path(__file__).resolve())] = file_hash(Path(__file__).resolve())
    request = {'project': str(project), 'output': str(output), 'tools': tools, 'pins': pins,
               'canvas': bound_json(project / 'SHORT-PROJECT.json')['canvas']}
    request_path = output / 'request.json'
    write_new(request_path, request)
    cli, sandbox = runtime / 'dist/cli.js', Path(__file__).parents[1] / 'studio/native_localhost_only.sb'
    settings = NativeRunConfig(project=project, root=output, cli=cli, environment=environment,
        command=['/usr/bin/sandbox-exec', '-f', str(sandbox), sys.executable, str(Path(__file__).resolve()),
                 'worker', str(request_path)],
        admission={'output': str(output / 'equivalence.json'), 'sdkSha256': file_hash(cli), 'sandboxSha256': file_hash(sandbox)},
        additional_pins={**pins, str(request_path): file_hash(request_path)}, success_status='selected-source-equivalence-passed')
    return NativeRun('equivalence', settings).execute()


def main() -> None:
    """Require explicit paths; this test cannot discover or change production recordings."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('run', 'worker'))
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path, nargs='?')
    args = parser.parse_args()
    if args.operation == 'worker':
        worker(args.input)
        return
    require(args.output is not None, 'integration test needs a new output directory')
    raise SystemExit(0 if supervise(args.input, args.output) else 1)


if __name__ == '__main__':
    main()
